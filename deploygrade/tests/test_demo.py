import subprocess,unittest
class DemoTests(unittest.TestCase):
 def test_hero_beats_and_determinism(self):
  runs=[subprocess.check_output(['python3','-m','deploygrade.harness.demo'],text=True) for _ in range(3)];self.assertTrue(all(x==runs[0] for x in runs));self.assertIn('ROLLBACK FIRED',runs[0]);self.assertIn('2026.07.1',runs[0]);self.assertIn('REFUSED',runs[0])
