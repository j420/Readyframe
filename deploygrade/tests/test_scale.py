import json,unittest
from deploygrade.engine.scale import recommend
from deploygrade.engine.discovery import discover
from deploygrade.engine.score import score_inventory
R=score_inventory(discover('deploygrade/fixtures/discovery_repos/mature'))
def card(**x): return {'$schema':'../schemas/pilot_scorecard.schema.json','schema_version':'1.0','deployment_id':'p','readiness_score':512,'observations':['pilot observation'],'metrics':{'throughput':100,'error_rate':.01,'silent_rollbacks':0,'evidence_coverage':.9,'samples':30}|x}
class ScaleTests(unittest.TestCase):
 def test_good_go(self): self.assertEqual(recommend(card(),R)['decision'],'GO')
 def test_rollback_no_go(self):
  d=recommend(card(silent_rollbacks=1),R);self.assertEqual(d['decision'],'NO_GO');self.assertIn('silent rollback',d['memo'][0]['claim'])
 def test_thin_hold(self): self.assertEqual(recommend(card(evidence_coverage=.2),R)['decision'],'HOLD')
