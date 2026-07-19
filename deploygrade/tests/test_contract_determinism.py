import unittest

from deploygrade.engine.contracts import validate_schema_shape


class ContractDeterminismTests(unittest.TestCase):
    def test_non_finite_values_are_rejected_deterministically(self):
        artifact = {"$schema": "../schemas/readiness-input.schema.json", "rubric_version": "2026.07.0", "controls": {"access_control": float("nan")}}
        for _ in range(2):
            with self.assertRaisesRegex(ValueError, "finite number"):
                validate_schema_shape(artifact)

    def test_worker_dispatch_hash_validation_is_deterministic(self):
        from deploygrade.engine.worker_dispatch import create_dispatch
        import json

        blueprint = json.load(open("deploygrade/fixtures/rollout_blueprint.json"))
        approval = {"approval_id": "approval://human/test", "blueprint_hash": "", "status": "APPROVED", "approver_id": "human"}
        from deploygrade.engine.audit_log import canonical_hash
        approval["blueprint_hash"] = canonical_hash(blueprint)
        arguments = {"dispatch_id": "dispatch-1", "execution_kind": "DISCOVERY", "repository": {"repository_id": "repo-1", "connector_id": "github", "revision": "abc123"}, "approved_repositories": [{"repository_id": "repo-1", "connector_id": "github", "revisions": ["abc123"]}], "blueprint": blueprint, "approval": approval, "credential_ref": "credential://sandbox/read-only"}
        self.assertEqual(create_dispatch(**arguments), create_dispatch(**arguments))

    def test_approved_connector_discovery_is_deterministic(self):
        from deploygrade.engine.repository_connector import approved_fixture
        from deploygrade.engine.discovery import discover_approved

        connector = approved_fixture("mature-v1", organization_id="org-test", engagement_id="engagement-test")
        self.assertEqual(discover_approved(connector, "sandbox"), discover_approved(connector, "sandbox"))

    def test_manifest_min_properties_is_enforced(self):
        artifact = {
            "$schema": "../schemas/rubric_manifest.schema.json",
            "schema_version": "1.0",
            "rubric_hashes": {},
            "publications": {},
        }
        with self.assertRaisesRegex(ValueError, "at least 1 properties"):
            validate_schema_shape(artifact)

    def test_published_refit_requires_complete_provenance_and_improvement(self):
        from deploygrade.engine.contracts import validate_artifact
        refit = {
            "$schema": "../schemas/rubric_refit.schema.json", "schema_version": "1.0",
            "status": "PUBLISHED", "vertical": "healthcare", "corpus_hash": "a" * 64,
            "split_version": "test-v1", "accepted_records": 20, "holdout_records": 4,
        }
        with self.assertRaisesRegex(ValueError, "published refit missing provenance"):
            validate_artifact(refit)
