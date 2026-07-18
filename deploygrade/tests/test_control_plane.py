import unittest

from deploygrade.engine.control_plane import ControlPlaneStore
from deploygrade.engine.demo_flow import run


class ControlPlaneStoreTests(unittest.TestCase):
    def setUp(self):
        self.store = ControlPlaneStore()
        self.store.create_organization("org-a")
        self.store.create_organization("org-b")
        self.store.create_engagement("org-a", "eng-a", "healthcare")
        self.store.create_engagement("org-b", "eng-b", "healthcare")
        self.blueprint = run("mature")["blueprint"]
        self.blueprint_hash = self.store.store_artifact("org-a", "eng-a", self.blueprint)

    def tearDown(self):
        self.store.close()

    def test_artifacts_are_validated_immutable_and_tenant_scoped(self):
        self.assertEqual(self.blueprint_hash, self.store.store_artifact("org-a", "eng-a", self.blueprint))
        with self.assertRaises(ValueError):
            self.store.store_artifact("org-b", "eng-b", self.blueprint)
        with self.assertRaises(ValueError):
            self.store.store_artifact("org-a", "eng-a", {"$schema": "../schemas/nope.schema.json"})

    def test_job_requires_exact_approved_blueprint(self):
        rejected = self.store.approve("org-a", "eng-a", self.blueprint_hash, "reviewer", "REJECTED")
        with self.assertRaises(ValueError):
            self.store.create_pilot_job("org-a", "eng-a", self.blueprint_hash, rejected, "/sandbox/repo")
        approved = self.store.approve("org-a", "eng-a", self.blueprint_hash, "reviewer")
        job = self.store.create_pilot_job("org-a", "eng-a", self.blueprint_hash, approved, "/sandbox/repo")
        self.assertEqual("QUEUED", self.store.job_status("org-a", job))
        with self.assertRaises(ValueError):
            self.store.create_pilot_job("org-b", "eng-b", self.blueprint_hash, approved, "/sandbox/repo")

    def test_callback_lineage_replay_and_pause_are_fail_closed(self):
        approval = self.store.approve("org-a", "eng-a", self.blueprint_hash, "reviewer")
        job = self.store.create_pilot_job("org-a", "eng-a", self.blueprint_hash, approval, "/sandbox/repo")
        event = {"$schema": "../schemas/pilot_callback.schema.json", "schema_version": "1.0", "event_id": "123e4567-e89b-12d3-a456-426614174000", "occurred_at": "2026-07-18T00:00:00Z", "event_type": "THRESHOLD_BREACHED", "pilot_job_id": job, "blueprint_hash": self.blueprint_hash}
        self.store.record_callback("org-a", event)
        self.assertEqual("PAUSED", self.store.job_status("org-a", job))
        with self.assertRaises(ValueError):
            self.store.record_callback("org-a", event)
        event["event_id"] = "123e4567-e89b-12d3-a456-426614174001"
        event["blueprint_hash"] = "wrong"
        with self.assertRaises(ValueError):
            self.store.record_callback("org-a", event)
        malformed = {**event, "event_id": "not-a-uuid", "blueprint_hash": self.blueprint_hash}
        with self.assertRaisesRegex(ValueError, "canonical UUID"):
            self.store.record_callback("org-a", malformed)

    def test_breach_cannot_be_silently_resumed_and_rollback_pauses(self):
        approval = self.store.approve("org-a", "eng-a", self.blueprint_hash, "reviewer")
        job = self.store.create_pilot_job("org-a", "eng-a", self.blueprint_hash, approval, "/sandbox/repo")

        def event(event_id, event_type):
            return {"$schema": "../schemas/pilot_callback.schema.json", "schema_version": "1.0", "event_id": event_id,
                    "occurred_at": "2026-07-18T00:00:00Z", "event_type": event_type, "pilot_job_id": job,
                    "blueprint_hash": self.blueprint_hash}

        self.store.record_callback("org-a", event("123e4567-e89b-12d3-a456-426614174010", "PILOT_STARTED"))
        self.store.record_callback("org-a", event("123e4567-e89b-12d3-a456-426614174011", "ROLLBACK_FIRED"))
        self.assertEqual("PAUSED", self.store.job_status("org-a", job))
        with self.assertRaises(ValueError):
            self.store.record_callback("org-a", event("123e4567-e89b-12d3-a456-426614174012", "PILOT_STARTED"))
        self.store.record_callback("org-a", event("123e4567-e89b-12d3-a456-426614174013", "COMPENSATING_REVERTED"))
        self.assertEqual("REVERTED", self.store.job_status("org-a", job))
