"""Anonymized deployment knowledge graph with deterministic quality quarantine."""
import hashlib,json
from pathlib import Path
from deploygrade.engine.contracts import validate_artifact

def anonymize(customer_id,salt='deploygrade-v1'): return hashlib.sha256(f'{salt}:{customer_id}'.encode()).hexdigest()
def quality_gate(record):
    try: validate_artifact(record)
    except ValueError: return False,'malformed'
    q=record['prediction_evidence_quality']['value']
    if q < .5: return False,'low_evidence_quality'
    if record['source_tag'] != 'customer-anonymized': return False,'untrusted_source'
    return True,'accepted'
def load(path):
    accepted=[]; quarantined=[]
    for line in Path(path).read_text().splitlines():
      r=json.loads(line); ok,reason=quality_gate(r); (accepted if ok else quarantined).append((r,reason))
    return accepted,quarantined
def pattern(records):
    low=[r for r,_ in records if r['predicted']['outcome']=='low_rollback']
    return {'accepted':len(records),'low_rollback_records':len(low),'mean_predicted_score':round(sum(r['predicted']['score'] for r in low)/len(low),1)}
