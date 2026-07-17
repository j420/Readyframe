import unittest
from deploygrade.engine.portfolio import aggregate
from deploygrade.engine.risk import cost_spike
class PortfolioTests(unittest.TestCase):
 def test_sort_and_actionable_alert(self):
  rows=aggregate([{'deployment_id':'a','risk':1,'velocity':2},{'deployment_id':'b','risk':2,'velocity':1}]);self.assertEqual(rows[0]['deployment_id'],'b');a=cost_spike('x',512,2000);self.assertEqual(a['severity'],'CRITICAL');self.assertIn('investigate',a['investigate_handoff'])
