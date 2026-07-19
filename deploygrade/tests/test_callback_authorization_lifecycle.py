import hashlib
import hmac
import json
import unittest
from datetime import datetime, timezone

from deploygrade.engine.callback_ingestion import StoreCallbackIngestionAdapter
from deploygrade.engine.control_plane import ControlPlaneStore
from deploygrade.engine.demo_flow import run


class CallbackAuthorizationLifecycleTests(unittest.TestCase):
    now = datetime(2026, 7, 18, 12, 0, tzinfo=timezone.utc)

    def setUp(self):
        self.store = ControlPlaneStore()
        self.store.create_organization("org-a")
        self.store.create_engagement("org-a", "eng-a", "healthcare")
        blueprint_hash = self.store.store_artifact("org-a", "eng-a", run("mature")["blueprint"])
        approval = self.store.approve("org-a", "eng-a", blueprint_hash, "reviewer")
        self.job = self.store.create_pilot_job("org-a", "eng-a", blueprint_hash, approval, "approved-repository")
        self.authorization = self.store.issue_callback_authorization("org-a", self.job, ttl_seconds=300)
        self.adapter = StoreCallbackIngestionAdapter(self.store, clock=lambda: self.now)

    def tearDown(self):
        self.store.close()

    def signed_event(self, **changes):
        event = {
            "event_id": "123e4567-e89b-12d3-a456-426614174400",
            "occurred_at": "2026-07-18T12:00:00Z", "event_type": "PILOT_STARTED",
            "pilot_job_id": self.job, "blueprint_hash": self.authorization["blueprint_hash"],
        }
        event.update(changes)
        raw = json.dumps(event, sort_keys=True, separators=(",", ":")).encode()
        return raw, hmac.new(self.authorization["signing_secret"].encode(), raw, hashlib.sha256).hexdigest()

    def test_issued_authorization_is_job_scoped_durable_and_replay_protected(self):
        raw, signature = self.signed_event()
        self.assertTrue(self.adapter.ingest(self.authorization["route_id"], raw, signature)["accepted"])
        self.assertEqual("RUNNING", self.store.job_status("org-a", self.job))
        with self.assertRaisesRegex(ValueError, "duplicate"):
            self.adapter.ingest(self.authorization["route_id"], raw, signature)

    def test_revocation_and_cross_tenant_or_lineage_attempts_fail_closed(self):
        self.store.create_organization("org-b")
        with self.assertRaisesRegex(ValueError, "unknown tenant"):
            self.store.revoke_callback_authorization("org-b", self.authorization["route_id"])
        raw, signature = self.signed_event(pilot_job_id="attacker-job")
        with self.assertRaisesRegex(ValueError, "configured Pilot authorization"):
            self.adapter.ingest(self.authorization["route_id"], raw, signature)
        self.store.revoke_callback_authorization("org-a", self.authorization["route_id"])
        raw, signature = self.signed_event()
        with self.assertRaisesRegex(ValueError, "unknown callback authorization route"):
            self.adapter.ingest(self.authorization["route_id"], raw, signature)

    def test_authorization_ttl_and_terminal_job_are_denied(self):
        with self.assertRaisesRegex(ValueError, "ttl"):
            self.store.issue_callback_authorization("org-a", self.job, ttl_seconds=1)
        raw, signature = self.signed_event(event_type="THRESHOLD_BREACHED")
        self.adapter.ingest(self.authorization["route_id"], raw, signature)
        revert_raw, revert_signature = self.signed_event(
            event_id="123e4567-e89b-12d3-a456-426614174401", event_type="COMPENSATING_REVERTED"
        )
        self.adapter.ingest(self.authorization["route_id"], revert_raw, revert_signature)
        with self.assertRaisesRegex(ValueError, "non-terminal"):
            self.store.issue_callback_authorization("org-a", self.job)
