import unittest
from deploygrade.engine.fallbacks import network_off_demo
class FallbackTests(unittest.TestCase):
 def test_golden_and_perturbation(self):
  h=network_off_demo();self.assertEqual(h['refit']['rubric_version'],'2026.07.2');self.assertEqual(h['refit']['status'],'PUBLISHED');self.assertEqual(h['refit']['diff']['rollback_recovery'],.05)
