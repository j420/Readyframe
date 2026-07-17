import json
import unittest
from deploygrade.engine.blueprint import compile_blueprint

READINESS = json.load(open("deploygrade/sites/dashboard/readiness_score.json"))
POLICY = json.load(open("deploygrade/fixtures/policy_pack.json"))


class BlueprintTests(unittest.TestCase):
    def test_bare_blueprint_has_because_trace_and_lowest_blast_radius_first(self):
        blueprint = compile_blueprint(READINESS, POLICY, "bare")
        self.assertEqual(blueprint["autonomy_level"], "SUPERVISED")
        self.assertEqual(blueprint["pilot_repos"][0]["blast_radius"], "LOW")
        self.assertTrue(all(gate["because"]["sub_score"] and gate["because"]["control_clause"] for gate in blueprint["rollback_rules"] + blueprint["approval_gates"]))
        rollback = next(gate for gate in blueprint["rollback_rules"] if gate["because"]["sub_score"] == "rollback_recovery")
        self.assertEqual(rollback["effect"], "DENY")

    def test_dangerous_autonomy_request_is_clamped_for_not_ready_customer(self):
        from deploygrade.engine.discovery import discover
        from deploygrade.engine.score import score_inventory
        low = score_inventory(discover("deploygrade/fixtures/discovery_repos/bare"))
        blueprint = compile_blueprint(low, POLICY, "low", requested_autonomy="AUTONOMOUS")
        self.assertEqual(blueprint["autonomy_level"], "OBSERVE")

    def test_policy_override_cannot_loosen_budget(self):
        unsafe = {**POLICY, "overrides": [{"field": "max_goal_token_budget", "value": 12001, "justification": "more", "approved_by": "human"}]}
        with self.assertRaisesRegex(ValueError, "only tighten"):
            compile_blueprint(READINESS, unsafe, "bare")

    def test_semantic_validation_rejects_saved_blocked_autonomous_blueprint(self):
        from deploygrade.engine.contracts import validate_artifact
        blueprint = compile_blueprint(READINESS, POLICY, "bare")
        blueprint["source_band"] = "BLOCKED"
        blueprint["autonomy_level"] = "AUTONOMOUS"
        with self.assertRaisesRegex(ValueError, "autonomy exceeds"):
            validate_artifact(blueprint)
