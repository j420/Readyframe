import json
import unittest
from pathlib import Path

from deploygrade.engine.contracts import validate_artifact


class StandardTests(unittest.TestCase):
    def test_conformance(self):
        validate_artifact(json.loads(Path('deploygrade/sites/dashboard/readiness_score.json').read_text()))
        standard = Path('deploygrade/standard/DEPLOYGRADE_STANDARD_V1.md').read_text().lower()
        self.assertIn('open', standard)
