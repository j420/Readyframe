import unittest
from deploygrade.engine.fallbacks import network_off_demo
class FallbackTests(unittest.TestCase):
 def test_golden_and_perturbation(self):
  h=network_off_demo();self.assertEqual((h['v1_score'],h['v2_score']),(512,547));self.assertNotEqual(h['v2_score'],548)
