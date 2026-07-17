"""Deterministic scaling recommendation; prose is a metric-linked memo only."""
from deploygrade.engine.contracts import validate_artifact

def recommend(scorecard, readiness):
    validate_artifact(scorecard); validate_artifact(readiness)
    m=scorecard['metrics']; red=m['silent_rollbacks']; coverage=m['evidence_coverage']; score=readiness['score']['value']; confidence=min(coverage,readiness['score']['confidence'])
    if red: decision='NO_GO'; why='silent rollback detected'
    elif coverage < .6 or m['samples'] < 20: decision='HOLD'; why='insufficient signal'
    elif score >= 600 and m['error_rate'] <= .02: decision='GO'; why='stable pilot metrics'
    else: decision='HOLD'; why='readiness or error threshold unmet'
    gain=round(m['throughput']*.1) if decision=='GO' else 0; risk=round(red*.5+m['error_rate']*100,2)
    meta=lambda v:{'value':v,'confidence':confidence,'evidence_uris':['metric://pilot/throughput','metric://pilot/rollbacks'],'rubric_version':readiness['score']['rubric_version']}
    return {'$schema':'../schemas/scaling_decision.schema.json','schema_version':'2.0','decision':decision,'predicted_gain':meta(gain),'risk_delta':meta(risk),'next_repo_batch':['sandbox-next'] if decision=='GO' else [],'updated_policy':'retain pilot gates' if decision!='GO' else 'expand to next low-blast batch','confidence':meta(confidence),'what_would_change_my_mind':['zero silent rollbacks over 20 samples','evidence coverage >= 0.60'],'memo':[{'claim':why,'metric_uri':'metric://pilot/rollbacks'},{'claim':f"throughput={m['throughput']}",'metric_uri':'metric://pilot/throughput'}]}
