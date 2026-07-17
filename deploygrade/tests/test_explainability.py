import json
import unittest
from pathlib import Path


class ExplainabilityTests(unittest.TestCase):
    def test_portfolio_numbers_have_full_coverage(self):
        path = Path('deploygrade/sites/dashboard/portfolio.json')
        for item in json.loads(path.read_text()):
            self.assertTrue(item['evidence_uris'])
            self.assertIn('confidence', item)
            self.assertTrue(item['counterfactual'])
            self.assertTrue(item['audit_record'])
