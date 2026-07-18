import unittest
from deploygrade.engine.contracts import validate_artifact
from deploygrade.engine.replay import investigate
from deploygrade.engine.risk import cost_spike


def number(value):
    return {"value": value, "confidence": .9, "evidence_uris": ["metric://cost"], "rubric_version": "2026.07.2"}


class ReplayTests(unittest.TestCase):
    def test_audit_grade(self):
        alert = cost_spike("deployment", number(512), number(2000))
        report = investigate(alert, "outcome://o")
        validate_artifact(report)
        self.assertIn("NIST", report["failed_control"])
        self.assertEqual(report["outcome_record"], "outcome://o")

    def test_unvalidated_event_is_denied(self):
        with self.assertRaises(ValueError):
            investigate({"outcome_record": {"id": "o"}})
