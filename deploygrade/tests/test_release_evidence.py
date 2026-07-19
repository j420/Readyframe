import json
import tempfile
import unittest
from pathlib import Path

from deploygrade.harness.verify_release_evidence import verify


def evidence(**overrides):
    value = {
        "$schema": "../schemas/production_release_evidence.schema.json", "schema_version": "1.0",
        "release_commit": "a" * 40, "deployed_origin": "https://deploygrade.test",
        "control_plane_backend": "supabase_postgres", "database_migration": "0001_deploygrade_core.sql",
        "worker_image_digest": "sha256:" + "b" * 64, "worker_endpoint": "https://worker.deploygrade.test",
        "verified_by": "release-operator", "verified_at": "2026-07-18T00:00:00Z",
    }
    value.update(overrides)
    return value


class ReleaseEvidenceTests(unittest.TestCase):
    def write(self, payload):
        handle = tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False)
        with handle:
            json.dump(payload, handle)
        return Path(handle.name)

    def test_accepts_complete_matching_production_attestation(self):
        path = self.write(evidence())
        self.assertEqual(verify(path, expected_commit="a" * 40)["control_plane_backend"], "supabase_postgres")

    def test_refuses_placeholder_bad_endpoint_future_or_wrong_commit(self):
        for payload in (
            evidence(deployed_origin="https://example.invalid"),
            evidence(worker_endpoint="https://worker.test/path"),
            evidence(verified_at="2999-01-01T00:00:00Z"),
        ):
            with self.assertRaises(ValueError):
                verify(self.write(payload))
        with self.assertRaisesRegex(ValueError, "does not match"):
            verify(self.write(evidence()), expected_commit="c" * 40)
