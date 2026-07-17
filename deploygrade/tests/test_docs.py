import unittest
from pathlib import Path
class DocsTests(unittest.TestCase):
 def test_docs(self):
  r=Path('README.md').read_text();self.assertIn('WHY THIS IS OUTSTANDING',r);self.assertGreaterEqual(r.count('|'),12);self.assertIn('make demo',Path('deploygrade/harness/DEMO_SCRIPT.md').read_text());self.assertIn('audit spine',Path('ARCHITECTURE.md').read_text())
