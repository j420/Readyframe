"""Visible data-network-effect metrics, derived only from accepted anonymized records."""
from deploygrade.engine.knowledge import load
from deploygrade.engine.flywheel import refit
def readout(path='deploygrade/knowledge/outcome_records_clean.jsonl'):
 a,_=load(path); r=refit(path,'healthcare'); return {'customers_graded':len({x['anonymized_id'] for x,_ in a}),'holdout_accuracy_before':r['baseline_accuracy'],'holdout_accuracy_after':r['holdout_accuracy'],'prior_deployments':len(a)}
