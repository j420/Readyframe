"""Cached deterministic hero narrative; no live model calls."""
import json
from deploygrade.engine.blueprint import compile_blueprint
from deploygrade.engine.flywheel import hero,refit
from deploygrade.engine.network import readout
r=json.load(open('deploygrade/sites/dashboard/readiness_score.json'));p=json.load(open('deploygrade/fixtures/policy_pack.json'));b=compile_blueprint(r,p,'hero');
print(json.dumps({'score':r['score'],'confidence':r['confidence'],'counterfactual':r['counterfactual'],'rollback_rule':next(x for x in b['rollback_rules'] if x['because']['sub_score']=='rollback_recovery'),'rollback_signal':'ROLLBACK FIRED','flywheel':hero(),'poison':refit('deploygrade/knowledge/outcome_records.jsonl','finance'),'network':readout()},sort_keys=True))
