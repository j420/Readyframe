import unittest
from deploygrade.engine.score import score_readiness


class ScoreDeterminismTests(unittest.TestCase):
    def test_same_versioned_input_has_identical_result(self):
        payload = {
            "$schema": "../schemas/readiness-input.schema.json",
            "rubric_version": "2026.07.0",
            "controls": {"access_control": .95, "rollback_plan": .8, "observability": .9},
        }
        self.assertEqual(score_readiness(payload), score_readiness(payload))  # deterministic across repeated invocations and discovery integrations

    def test_user_facing_score_has_required_metadata(self):
        result = score_readiness({"$schema": "../schemas/readiness-input.schema.json", "rubric_version": "r1", "controls": {"a": 1}})
        self.assertEqual(set(result["score"]), {"value", "confidence", "evidence_uris", "rubric_version"})
        self.assertIn("audit", result)
        self.assertIn("counterfactual", result)
        self.assertEqual(result["audit"]["generated_at"], "1970-01-01T00:00:00Z")

    def test_direct_controls_still_emit_six_deterministic_dimensions(self):
        result = score_readiness({"$schema": "../schemas/readiness-input.schema.json", "rubric_version": "r1", "controls": {"access_control": 1, "rollback_plan": 1, "observability": 1}})
        self.assertEqual(len(result["sub_scores"]), 6)
        self.assertTrue(all("evidence_quality" in item for item in result["sub_scores"]))

    def test_blueprint_source_score_is_deterministic_input(self):
        from deploygrade.engine.blueprint import compile_blueprint
        import json
        from pathlib import Path
        readiness = json.loads(Path("deploygrade/sites/dashboard/readiness_score.json").read_text())
        policy = json.loads(Path("deploygrade/fixtures/policy_pack.json").read_text())
        self.assertEqual(compile_blueprint(readiness, policy, "pilot"), compile_blueprint(readiness, policy, "pilot"))

    def test_pilot_metric_decision_is_deterministic(self):
        from deploygrade.engine.pilot import blast_radius
        action = {"files": ["a"], "services": ["api"], "data_touched": False}
        self.assertEqual(blast_radius(action), blast_radius(action))

    def test_scale_projection_is_deterministic_contract(self):
        from deploygrade.engine.scale import recommend
        from deploygrade.engine.discovery import discover
        from deploygrade.engine.score import score_inventory
        card = {"$schema":"../schemas/pilot_scorecard.schema.json","schema_version":"1.0","deployment_id":"p","readiness_score":1,"observations":["x"],"metrics":{"throughput":1,"error_rate":0,"silent_rollbacks":0,"evidence_coverage":1,"samples":20}}
        readiness = score_inventory(discover("deploygrade/fixtures/discovery_repos/mature"))
        self.assertEqual(recommend(card, readiness), recommend(card, readiness))

    def test_knowledge_anonymization_is_deterministic(self):
        from deploygrade.engine.knowledge import anonymize
        self.assertEqual(anonymize('customer'), anonymize('customer'))
