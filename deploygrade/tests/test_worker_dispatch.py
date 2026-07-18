import copy
import json
import unittest
from deploygrade.engine.contracts import validate_artifact
from deploygrade.engine.worker_dispatch import create_dispatch, status_event

BLUEPRINT = json.load(open("deploygrade/fixtures/rollout_blueprint.json"))
APPROVED = [{"repository_id": "repo-mature", "connector_id": "github-app-tenant-a", "revisions": ["a" * 40]}]
REPOSITORY = {"repository_id": "repo-mature", "connector_id": "github-app-tenant-a", "revision": "a" * 40}


class WorkerDispatchTests(unittest.TestCase):
    def dispatch(self):
        from deploygrade.engine.audit_log import canonical_hash
        blueprint_hash = canonical_hash(BLUEPRINT)
        approval = {"approval_id": "approval://human/pilot-owner", "blueprint_hash": blueprint_hash,
                    "status": "APPROVED", "approver_id": "operator-1"}
        return create_dispatch(dispatch_id="dispatch-1", execution_kind="PILOT", repository=REPOSITORY,
                               approved_repositories=APPROVED, blueprint=BLUEPRINT, approval=approval,
                               credential_ref="secret://worker/tenant-a")

    def test_dispatch_is_schema_valid_and_path_free(self):
        dispatch = self.dispatch()
        validate_artifact(dispatch)
        self.assertNotIn("path", json.dumps(dispatch).lower())
        self.assertEqual(dispatch["sandbox"]["filesystem_mode"], "READ_ONLY")
        self.assertEqual(dispatch["sandbox"]["network_egress"], "DENY_ALL")

    def test_refuses_unapproved_repository_revision_and_mismatched_approval(self):
        from deploygrade.engine.audit_log import canonical_hash
        approval = {"approval_id": "a", "blueprint_hash": canonical_hash(BLUEPRINT), "status": "APPROVED", "approver_id": "u"}
        bad_repo = {**REPOSITORY, "revision": "b" * 40}
        with self.assertRaises(ValueError):
            create_dispatch(dispatch_id="d", execution_kind="DISCOVERY", repository=bad_repo, approved_repositories=APPROVED, blueprint=BLUEPRINT, approval=approval, credential_ref="secret://x")
        approval["blueprint_hash"] = "0" * 64
        with self.assertRaises(ValueError):
            create_dispatch(dispatch_id="d", execution_kind="PILOT", repository=REPOSITORY, approved_repositories=APPROVED, blueprint=BLUEPRINT, approval=approval, credential_ref="secret://x")

    def test_refuses_malformed_approved_repository_configuration(self):
        from deploygrade.engine.audit_log import canonical_hash
        approval = {"approval_id": "a", "blueprint_hash": canonical_hash(BLUEPRINT), "status": "APPROVED", "approver_id": "u"}
        for repositories in (None, "repo-mature", ["repo-mature"]):
            with self.assertRaises(ValueError):
                create_dispatch(dispatch_id="d", execution_kind="PILOT", repository=REPOSITORY,
                                approved_repositories=repositories, blueprint=BLUEPRINT, approval=approval,
                                credential_ref="secret://x")

    def test_tampered_lineage_and_failed_sandbox_state_fail_closed(self):
        dispatch = self.dispatch()
        tampered = copy.deepcopy(dispatch)
        tampered["approval"]["blueprint_hash"] = "0" * 64
        with self.assertRaises(ValueError): validate_artifact(tampered)
        event = status_event(event_id="event-1", dispatch=dispatch, state="FAILED", reason="worker state unknown")
        self.assertTrue(event["human_escalation_required"])
        event["human_escalation_required"] = False
        with self.assertRaises(ValueError): validate_artifact(event)

    def test_refuses_non_blueprint_artifact_before_worker_dispatch(self):
        from deploygrade.engine.audit_log import canonical_hash
        non_blueprint = {"$schema": "../schemas/readiness-input.schema.json", "rubric_version": "r1", "controls": {"a": 1}}
        approval = {"approval_id": "a", "blueprint_hash": canonical_hash(non_blueprint), "status": "APPROVED", "approver_id": "u"}
        with self.assertRaisesRegex(ValueError, "rollout blueprint"):
            create_dispatch(dispatch_id="d", execution_kind="PILOT", repository=REPOSITORY,
                            approved_repositories=APPROVED, blueprint=non_blueprint,
                            approval=approval, credential_ref="secret://x")
