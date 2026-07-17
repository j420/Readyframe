import unittest
from deploygrade.engine.replay import investigate
class ReplayTests(unittest.TestCase):
 def test_audit_grade(self):
  r=investigate({'outcome_record':{'id':'o'}});self.assertIn('NIST',r['failed_control']);self.assertEqual(r['outcome_record']['id'],'o')
