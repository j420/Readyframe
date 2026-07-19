import copy
import json
import unittest

from deploygrade.engine.audit_log import canonical_hash
from deploygrade.engine.contracts import validate_artifact
from deploygrade.engine.repository_connector import approved_fixture
from deploygrade.engine.worker_dispatch import create_dispatch
from deploygrade.engine.worker_runtime import run
from deploygrade.engine.github_connector import GitHubRepositoryConnector
from deploygrade.tests.test_github_connector import APPROVAL, transport_for

BLUEPRINT = json.load(open("deploygrade/fixtures/rollout_blueprint.json"))


def dispatch(kind: str, fixture_id: str = "mature-v1"):
    connector = approved_fixture(fixture_id)
    repository = connector["repository"]
    approval = {"approval_id": "approval-runtime", "blueprint_hash": canonical_hash(BLUEPRINT),
                "status": "APPROVED", "approver_id": "operator-runtime"}
    approved = [{**repository, "revisions": [repository["revision"]]}]
    return create_dispatch(dispatch_id=f"runtime-{kind.lower()}", execution_kind=kind,
                           repository=repository, approved_repositories=approved,
                           blueprint=BLUEPRINT, approval=approval, credential_ref="secret://runtime"), connector


class WorkerRuntimeTests(unittest.TestCase):
    def test_discovery_consumes_only_matching_approved_evidence(self):
        worker_dispatch, connector = dispatch("DISCOVERY")
        result = run(worker_dispatch, connector, environment="staging")
        validate_artifact(result)
        self.assertEqual(result["outcome"], "DISCOVERY_COMPLETED")
        self.assertEqual([event["state"] for event in result["events"]], ["RECEIVED", "RUNNING", "COMPLETED"])
        self.assertEqual(result["inventory"]["environment"], "staging")
        self.assertFalse(result["human_escalation_required"])
        self.assertEqual(run(worker_dispatch, connector, environment="staging"), result)

    def test_pilot_is_denied_before_action_and_escalated(self):
        worker_dispatch, connector = dispatch("PILOT")
        result = run(worker_dispatch, connector)
        validate_artifact(result)
        self.assertEqual(result["outcome"], "PILOT_DENIED")
        self.assertEqual([event["state"] for event in result["events"]], ["RECEIVED", "FAILED"])
        self.assertTrue(result["human_escalation_required"])
        self.assertNotIn("inventory", result)
        self.assertIn("denied before execution", result["events"][-1]["reason"])

    def test_github_snapshot_emits_only_honest_missing_evidence(self):
        snapshot = GitHubRepositoryConnector(lambda: "x" * 24, transport=transport_for()).snapshot(APPROVAL)
        approval = {"approval_id": "approval-github-runtime", "blueprint_hash": canonical_hash(BLUEPRINT),
                    "status": "APPROVED", "approver_id": "operator-runtime"}
        repository = {"repository_id": snapshot["repository"]["repository_id"], "connector_id": "github",
                      "revision": snapshot["repository"]["revision"]}
        worker_dispatch = create_dispatch(
            dispatch_id="runtime-github-discovery", execution_kind="DISCOVERY", repository=repository,
            approved_repositories=[{**repository, "revisions": [repository["revision"]]}], blueprint=BLUEPRINT,
            approval=approval, credential_ref="secret://runtime")
        result = run(worker_dispatch, snapshot, environment="production")
        self.assertEqual(result["outcome"], "DISCOVERY_COMPLETED")
        self.assertEqual(result["inventory"]["collected_facts"], [])
        self.assertEqual(len(result["inventory"]["missing_evidence"]), 6)

    def test_github_redacted_content_evidence_can_create_only_bound_findings(self):
        entries = [
            {"path": "rollback.sh", "type": "blob", "sha": "c" * 40, "size": 30},
            {"path": "tests/test_ready.py", "type": "blob", "sha": "d" * 40, "size": 24},
        ]
        blobs = {"c" * 40: b"#!/bin/sh\nset -e\ngit revert x\n", "d" * 40: b"def test_x():\n assert x\n"}
        connector = GitHubRepositoryConnector(lambda: "x" * 24, transport=transport_for(entries=entries, blobs=blobs))
        snapshot = connector.snapshot(APPROVAL)
        evidence = connector.content_evidence(snapshot)
        approval = {"approval_id": "approval-github-content", "blueprint_hash": canonical_hash(BLUEPRINT),
                    "status": "APPROVED", "approver_id": "operator-runtime"}
        repository = {"repository_id": snapshot["repository"]["repository_id"], "connector_id": "github",
                      "revision": snapshot["repository"]["revision"]}
        worker_dispatch = create_dispatch(dispatch_id="runtime-github-content", execution_kind="DISCOVERY",
                                          repository=repository, approved_repositories=[{**repository, "revisions": [repository["revision"]]}],
                                          blueprint=BLUEPRINT, approval=approval, credential_ref="secret://runtime")
        result = run(worker_dispatch, snapshot, environment="production", github_content_evidence=evidence)
        self.assertEqual([fact["category"] for fact in result["inventory"]["collected_facts"]], ["rollback", "tests"])
        self.assertEqual(len(result["inventory"]["missing_evidence"]), 4)
        self.assertNotIn("git revert x", json.dumps(result))
        tampered = copy.deepcopy(evidence)
        tampered["snapshot_manifest_hash"] = "0" * 64
        with self.assertRaises(ValueError):
            run(worker_dispatch, snapshot, github_content_evidence=tampered)

    def test_rejects_mismatched_or_tampered_connector_before_scan(self):
        worker_dispatch, connector = dispatch("DISCOVERY")
        other = approved_fixture("deceptive-v1")
        with self.assertRaisesRegex(ValueError, "does not match"):
            run(worker_dispatch, other)
        tampered = copy.deepcopy(connector)
        tampered["access"]["network_egress"] = "ALLOW_ALL"
        with self.assertRaises(ValueError):
            run(worker_dispatch, tampered)
        tampered = copy.deepcopy(connector)
        tampered["evidence_manifest"]["files"][0]["sha256"] = "0" * 64
        with self.assertRaises(ValueError):
            run(worker_dispatch, tampered)

    def test_result_contract_rejects_invalid_pilot_or_discovery_sequences(self):
        worker_dispatch, connector = dispatch("PILOT")
        result = run(worker_dispatch, connector)
        result["human_escalation_required"] = False
        with self.assertRaises(ValueError):
            validate_artifact(result)
        worker_dispatch, connector = dispatch("DISCOVERY")
        result = run(worker_dispatch, connector)
        result["events"].pop()
        with self.assertRaises(ValueError):
            validate_artifact(result)
