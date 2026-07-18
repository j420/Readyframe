import hashlib
import hmac
import json
import unittest
from datetime import datetime, timezone

from deploygrade.engine.callback_ingestion import CallbackAuthorization, CallbackIngestionAdapter
from deploygrade.engine.control_plane import ControlPlaneStore
from deploygrade.engine.demo_flow import run


class CallbackIngestionAdapterTests(unittest.TestCase):
    now = datetime(2026, 7, 18, 12, 0, tzinfo=timezone.utc)

    def setUp(self):
        self.store = ControlPlaneStore()
        self.store.create_organization("org-a")
        self.store.create_engagement("org-a", "eng-a", "healthcare")
        blueprint_hash = self.store.store_artifact("org-a", "eng-a", run("mature")["blueprint"])
        approval = self.store.approve("org-a", "eng-a", blueprint_hash, "reviewer")
        self.job = self.store.create_pilot_job("org-a", "eng-a", blueprint_hash, approval, "approved-repository")
        self.authorization = CallbackAuthorization("org-a", self.job, blueprint_hash, "route-secret")
        self.adapter = CallbackIngestionAdapter(self.store, {"worker-route": self.authorization}, clock=lambda: self.now)

    def tearDown(self):
        self.store.close()

    def signed_event(self, **changes):
        event = {
            "event_id": "123e4567-e89b-12d3-a456-426614174100",
            "occurred_at": "2026-07-18T12:00:00Z",
            "event_type": "PILOT_STARTED",
            "pilot_job_id": self.job,
            "blueprint_hash": self.authorization.blueprint_hash,
        }
        event.update(changes)
        raw = json.dumps(event, sort_keys=True, separators=(",", ":")).encode()
        signature = hmac.new(b"route-secret", raw, hashlib.sha256).hexdigest()
        return raw, signature

    def test_authorized_signed_event_is_durable_and_replay_fails_closed(self):
        raw, signature = self.signed_event()
        receipt = self.adapter.ingest("worker-route", raw, signature)
        self.assertTrue(receipt["accepted"])
        self.assertEqual("RUNNING", self.store.job_status("org-a", self.job))
        metric_raw, metric_signature = self.signed_event(
            event_id="123e4567-e89b-12d3-a456-426614174103", event_type="METRIC_RECORDED"
        )
        self.adapter.ingest("worker-route", metric_raw, metric_signature)
        with self.assertRaisesRegex(ValueError, "duplicate callback event"):
            self.adapter.ingest("worker-route", metric_raw, metric_signature)

    def test_body_cannot_select_another_job_or_blueprint(self):
        raw, signature = self.signed_event(pilot_job_id="attacker-job")
        with self.assertRaisesRegex(ValueError, "configured Pilot authorization"):
            self.adapter.ingest("worker-route", raw, signature)
        raw, signature = self.signed_event(blueprint_hash="attacker-blueprint")
        with self.assertRaisesRegex(ValueError, "configured Pilot authorization"):
            self.adapter.ingest("worker-route", raw, signature)

    def test_unknown_route_bad_signature_stale_event_and_paused_resume_are_rejected(self):
        raw, signature = self.signed_event()
        with self.assertRaisesRegex(ValueError, "unknown callback authorization route"):
            self.adapter.ingest("unknown", raw, signature)
        with self.assertRaisesRegex(ValueError, "invalid callback signature"):
            self.adapter.ingest("worker-route", raw, "0" * 64)
        contract_raw, contract_signature = self.signed_event(**{"$schema": "../schemas/api_error.schema.json"})
        with self.assertRaisesRegex(ValueError, "must not supply artifact contract"):
            self.adapter.ingest("worker-route", contract_raw, contract_signature)
        stale_raw, stale_signature = self.signed_event(occurred_at="2026-07-18T11:54:59Z")
        with self.assertRaisesRegex(ValueError, "delivery window"):
            self.adapter.ingest("worker-route", stale_raw, stale_signature)
        breach_raw, breach_signature = self.signed_event(event_id="123e4567-e89b-12d3-a456-426614174101", event_type="THRESHOLD_BREACHED")
        self.adapter.ingest("worker-route", breach_raw, breach_signature)
        restart_raw, restart_signature = self.signed_event(event_id="123e4567-e89b-12d3-a456-426614174102")
        with self.assertRaisesRegex(ValueError, "not allowed"):
            self.adapter.ingest("worker-route", restart_raw, restart_signature)

    def test_configuration_fails_closed(self):
        with self.assertRaises(ValueError):
            CallbackIngestionAdapter(self.store, {})
        with self.assertRaises(ValueError):
            CallbackIngestionAdapter(self.store, {"": self.authorization})
        with self.assertRaises(ValueError):
            CallbackAuthorization("org-a", self.job, self.authorization.blueprint_hash, "")
