import copy
import unittest

from deploygrade.engine.contracts import validate_artifact
from deploygrade.engine.discovery import discover_approved
from deploygrade.engine.repository_connector import approved_fixture, resolve_approved_fixture


class ApprovedRepositoryConnectorTests(unittest.TestCase):
    def test_discovery_uses_only_an_approved_read_only_fixture(self):
        connector = approved_fixture("mature-v1", organization_id="tenant-a", engagement_id="engagement-a")
        inventory = discover_approved(connector, environment="staging")
        self.assertEqual(len(inventory["collected_facts"]), 6)
        self.assertEqual(inventory["missing_evidence"], [])
        self.assertEqual(connector["access"], {"mode": "READ_ONLY", "network_egress": "DENY_ALL"})

    def test_rejects_path_escape_and_unapproved_revision(self):
        connector = approved_fixture("mature-v1")
        escaped = copy.deepcopy(connector)
        escaped["repository"]["path"] = "/etc"
        with self.assertRaises(ValueError):
            validate_artifact(escaped)
        changed_revision = copy.deepcopy(connector)
        changed_revision["repository"]["revision"] = "unapproved"
        with self.assertRaises(ValueError):
            resolve_approved_fixture(changed_revision)

    def test_rejects_tampered_or_ambiguous_manifest(self):
        connector = approved_fixture("mature-v1")
        tampered = copy.deepcopy(connector)
        tampered["evidence_manifest"]["files"][0]["sha256"] = "0" * 64
        with self.assertRaises(ValueError):
            discover_approved(tampered)
        unordered = copy.deepcopy(connector)
        unordered["evidence_manifest"]["files"].reverse()
        with self.assertRaises(ValueError):
            validate_artifact(unordered)

    def test_public_discovery_entrypoint_accepts_no_arbitrary_path(self):
        with self.assertRaises((TypeError, ValueError)):
            discover_approved({"root": "deploygrade/fixtures/discovery_repos/mature"})
