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

    def test_operator_console_requires_runtime_auth_without_token_persistence(self):
        page = (DASHBOARD / "index.html").read_text()
        script = (DASHBOARD / "app.js").read_text()
        self.assertIn('id="control-plane-form"', page)
        self.assertIn("does not start, execute, or claim a live worker", page)
        self.assertIn("DEPLOYGRADE_OPERATOR_RUNTIME", script)
        self.assertIn("CONTROL_PLANE_REQUEST_SCHEMA", script)
        self.assertNotIn("localStorage", script)
        self.assertNotIn("sessionStorage", script)
