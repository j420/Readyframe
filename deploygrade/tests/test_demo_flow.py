import unittest

from deploygrade.engine.demo_flow import run


class DemoFlowTests(unittest.TestCase):
    def test_live_demo_chain_is_deterministic_and_score_drives_blueprint(self):
        first = run("deceptive")
        self.assertEqual(first, run("deceptive"))
        self.assertEqual(first["blueprint"]["source_readiness_audit"]["signature"], first["readiness_score"]["audit"]["signature"])
        self.assertTrue(first["blueprint"]["rollback_rules"])
        self.assertEqual(first["flywheel"]["refit"]["status"], "PUBLISHED")

    def test_demo_refuses_unapproved_repository_profile(self):
        with self.assertRaisesRegex(ValueError, "repo_profile"):
            run("../../etc")

    def test_demo_contract_rejects_tampered_nested_artifact(self):
        from deploygrade.engine.contracts import validate_artifact

        result = run("mature")
        result["blueprint"]["source_readiness_audit"]["signature"] = "tampered"
        with self.assertRaisesRegex(ValueError, "does not retain"):
            validate_artifact(result)
