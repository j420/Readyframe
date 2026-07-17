import unittest,json
from deploygrade.engine.contracts import validate_artifact
class StandardTests(unittest.TestCase):
 def test_conformance(self):
  validate_artifact(json.load(open('deploygrade/sites/dashboard/readiness_score.json')))
  self.assertIn('open',open('deploygrade/standard/DEPLOYGRADE_STANDARD_V1.md').read().lower())
