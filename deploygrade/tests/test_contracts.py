import json
import unittest
from pathlib import Path

from deploygrade.engine.contracts import validate_artifact, validate_schema_shape

FIXTURES = Path(__file__).parents[1] / "fixtures"


class ContractTests(unittest.TestCase):
    def test_all_example_fixtures_validate(self):
        for path in sorted(FIXTURES.glob("*.json")):
            with self.subTest(path=path.name):
                validate_artifact(json.loads(path.read_text()))

    def test_older_readiness_artifact_still_loads(self):
        artifact = json.loads((FIXTURES / "readiness_score.v1.json").read_text())
        validate_artifact(artifact)
        self.assertEqual(artifact["score"], 750)

    def test_semantic_validator_rejects_schema_valid_nonsense(self):
        artifact = {
            "$schema": "../schemas/readiness_score.schema.json", "schema_version": "2.0",
            "score": {"value": 900, "confidence": .9, "evidence_uris": ["evidence://score"], "rubric_version": "r2"},
            "band": "SCALE",
            "sub_scores": [{"name": "safety", "raw": 0, "weight": 1, "controls": ["c1"], "control_clauses": ["NIST CM-3"], "evidence_uris": ["evidence://c1"], "evidence_quality": {"source": "test", "freshness": "current", "confidence": 1}}],
            "confidence": {"interval_low": 800, "interval_high": 950, "method": "test", "drivers": [{"kind": "coverage", "detail": "test"}]},
            "counterfactual": [{"action": "fix safety", "sub_score_affected": "safety", "projected_score_delta": 1, "cost": 1}],
            "audit": {"rubric_version": "r2", "inputs_hash": "abc", "engine_version": "2", "generated_at": "1970-01-01T00:00:00Z", "signature": "sig"},
        }
        validate_schema_shape(artifact)  # Shape is valid: only semantic validation must reject it.
        with self.assertRaisesRegex(ValueError, "semantic mismatch"):
            validate_artifact(artifact)

    def test_semantic_validator_rejects_tampered_audit(self):
        from deploygrade.engine.score import score_readiness
        artifact = score_readiness({"$schema": "../schemas/readiness-input.schema.json", "rubric_version": "r1", "controls": {"a": 1}})
        artifact["audit"]["engine_version"] = "tampered"
        with self.assertRaisesRegex(ValueError, "audit signature"):
            validate_artifact(artifact)
