import unittest
from deploygrade.engine.contracts import validate_artifact
from deploygrade.engine.portfolio import aggregate
from deploygrade.engine.risk import cost_spike


def number(value, evidence="evidence://test"):
    return {"value": value, "confidence": .9, "evidence_uris": [evidence], "rubric_version": "2026.07.2"}


def row(deployment_id, risk, velocity):
    return {"deployment_id": deployment_id, "vertical": "healthcare", "risk": number(risk), "velocity": number(velocity), "confidence": number(.9), "evidence_uris": ["evidence://test"], "counterfactual": "reduce risk", "audit_record": f"audit://{deployment_id}", "action": "pause"}


class PortfolioTests(unittest.TestCase):
    def test_sort_and_actionable_alert(self):
        portfolio = aggregate([row("a", 1, 2), row("b", 2, 1)], "tenant-a")
        validate_artifact(portfolio)
        self.assertEqual(portfolio["rows"][0]["deployment_id"], "b")
        alert = cost_spike("x", number(512), number(2000, "metric://cost"))
        validate_artifact(alert)
        self.assertEqual(alert["severity"], "CRITICAL")
        self.assertIn("investigate", alert["investigate_handoff"])

    def test_metadata_free_numbers_fail_closed(self):
        with self.assertRaises((KeyError, ValueError)):
            aggregate([{**row("a", 1, 2), "risk": 1}])
        with self.assertRaises(ValueError):
            cost_spike("x", 512, number(2000))
