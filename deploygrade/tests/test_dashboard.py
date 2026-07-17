import json
import unittest
from pathlib import Path
from deploygrade.engine.contracts import validate_artifact

DASHBOARD = Path("deploygrade/sites/dashboard")


class DashboardTests(unittest.TestCase):
    def test_dashboard_score_artifact_is_schema_and_semantic_valid(self):
        artifact = json.loads((DASHBOARD / "readiness_score.json").read_text())
        validate_artifact(artifact)
        self.assertEqual(artifact["score"]["value"], 512)
        self.assertEqual(artifact["band"], "CONDITIONAL")

    def test_trust_surface_answers_skeptical_ciso_objections(self):
        page = (DASHBOARD / "index.html").read_text()
        for text in ("This looks made up", "Why trust one number", "What do we do next", "Show me the audit record", "NETWORK VALUE", "Non-copyable asset"):
            self.assertIn(text, page)
