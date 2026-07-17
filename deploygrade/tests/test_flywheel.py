import unittest
from deploygrade.engine.flywheel import refit,hero
class FlywheelTests(unittest.TestCase):
 def test_clean_publishes_and_isolates(self):
  h=refit('deploygrade/knowledge/outcome_records_clean.jsonl','healthcare');f=refit('deploygrade/knowledge/outcome_records_clean.jsonl','finance');self.assertEqual(h['status'],'PUBLISHED');self.assertGreater(h['holdout_accuracy'],h['baseline_accuracy']);self.assertEqual(h['weights'],f['weights'])
 def test_poison_refused(self):
  self.assertEqual(refit('deploygrade/knowledge/outcome_records.jsonl','finance')['status'],'REFUSED')
 def test_hero(self):self.assertEqual(hero()['v2_score'],547)
