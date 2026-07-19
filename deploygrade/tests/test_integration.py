import json,unittest,hashlib
from deploygrade.engine.blueprint import compile_blueprint
from deploygrade.engine.network import readout
class IntegrationTests(unittest.TestCase):
 def test_v2_shift_tightens_rollback_gate(self):
  r=json.load(open('deploygrade/sites/dashboard/readiness_score.json'));p=json.load(open('deploygrade/fixtures/policy_pack.json'));v1=compile_blueprint(r,p,'x');r2={**r,'score':{**r['score'],'rubric_version':'v2','value':494},'sub_scores':[dict(x) for x in r['sub_scores']]};r2['sub_scores'][2]['raw']=10;r2['confidence']={**r['confidence'],'interval_low':99};r2['audit']={**r['audit'],'rubric_version':'v2'};a={k:v for k,v in r2['audit'].items() if k!='signature'};r2['audit']['signature']=hashlib.sha256(json.dumps(a,sort_keys=True,separators=(',',':')).encode()).hexdigest();v2=compile_blueprint(r2,p,'x');self.assertEqual(next(x for x in v2['rollback_rules'] if x['because']['sub_score']=='rollback_recovery')['effect'],'DENY');self.assertLess(r2['sub_scores'][2]['raw'],r['sub_scores'][2]['raw'])
 def test_network_value(self):
  n=readout();self.assertEqual(n['prior_deployments']['value'],181);self.assertGreater(n['holdout_accuracy_after']['value'],n['holdout_accuracy_before']['value'])
