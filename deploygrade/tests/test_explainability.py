import json,unittest
class ExplainabilityTests(unittest.TestCase):
 def test_portfolio_numbers_have_full_coverage(self):
  for x in json.load(open('deploygrade/sites/dashboard/portfolio.json')):
   self.assertTrue(x['evidence_uris']);self.assertIn('confidence',x);self.assertTrue(x['counterfactual']);self.assertTrue(x['audit_record'])
