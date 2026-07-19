import hashlib
import hmac
import json
import os
from datetime import datetime, timezone
from http.client import HTTPConnection
from http.server import HTTPServer
from threading import Thread
import unittest

from api.pilot_callback import _clear_replay_cache_for_test, handler


class PilotCallbackTests(unittest.TestCase):
    secret = "test-callback-secret"

    @classmethod
    def setUpClass(cls):
        cls.previous_secret = os.environ.get("PILOT_CALLBACK_SECRET")
        os.environ["PILOT_CALLBACK_SECRET"] = cls.secret
        cls.server = HTTPServer(("127.0.0.1", 0), handler)
        cls.thread = Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.thread.join()
        cls.server.server_close()
        if cls.previous_secret is None:
            os.environ.pop("PILOT_CALLBACK_SECRET", None)
        else:
            os.environ["PILOT_CALLBACK_SECRET"] = cls.previous_secret

    def setUp(self):
        _clear_replay_cache_for_test()
        self.event = {
            "event_id": "123e4567-e89b-12d3-a456-426614174000",
            "occurred_at": "2026-07-18T12:00:00Z",
            "event_type": "PILOT_STARTED",
            "pilot_job_id": "pilot-1",
            "blueprint_hash": "a" * 64,
        }

    def post(self, event=None, content_type="application/json", signature=True):
        raw = json.dumps(self.event if event is None else event, sort_keys=True, separators=(",", ":")).encode()
        headers = {"Content-Type": content_type, "Content-Length": str(len(raw))}
        if signature:
            headers["X-DeployGrade-Signature"] = hmac.new(self.secret.encode(), raw, hashlib.sha256).hexdigest()
        connection = HTTPConnection("127.0.0.1", self.server.server_port)
        connection.request("POST", "/api/pilot-callback", body=raw, headers=headers)
        response = connection.getresponse()
        return response.status, json.loads(response.read())

    def test_signed_schema_valid_callback_is_accepted(self):
        from deploygrade.engine.contracts import validate_artifact

        status, body = self.post()
        self.assertEqual(status, 202)
        validate_artifact(body)
        self.assertEqual(body, {"$schema": "../schemas/pilot_callback_receipt.schema.json", "schema_version": "1.0", "accepted": True, "event_id": self.event["event_id"], "event_type": "PILOT_STARTED"})

    def test_duplicate_signed_event_is_rejected_fail_closed(self):
        self.assertEqual(self.post()[0], 202)
        status, body = self.post()
        self.assertEqual(status, 409)
        self.assertIn("duplicate", body["error"])

    def test_unsigned_and_wrong_content_type_callbacks_are_rejected(self):
        status, body = self.post(signature=False)
        self.assertEqual(status, 400)
        self.assertIn("signature", body["error"])
        status, body = self.post(content_type="text/plain")
        self.assertEqual(status, 400)
        self.assertIn("Content-Type", body["error"])

    def test_missing_or_invalid_event_identity_is_rejected(self):
        event = dict(self.event)
        del event["event_id"]
        status, body = self.post(event)
        self.assertEqual(status, 400)
        self.assertIn("event_id", body["error"])
        event = {**self.event, "event_id": "not-a-uuid"}
        status, body = self.post(event)
        self.assertEqual(status, 400)
        self.assertIn("event_id", body["error"])
        event = {**self.event, "occurred_at": "2026-07-18"}
        status, body = self.post(event)
        self.assertEqual(status, 400)
        self.assertIn("occurred_at", body["error"])

    def test_schema_rejects_ambiguous_extra_fields(self):
        status, body = self.post({**self.event, "untrusted": True})
        self.assertEqual(status, 400)
        self.assertIn("unexpected", body["error"])

    def test_unsupported_methods_return_schema_valid_errors(self):
        from deploygrade.engine.contracts import validate_artifact

        for method in ("GET", "PUT", "PATCH", "DELETE", "OPTIONS"):
            connection = HTTPConnection("127.0.0.1", self.server.server_port)
            connection.request(method, "/api/pilot-callback")
            response = connection.getresponse()
            self.assertEqual(response.status, 405, method)
            artifact = json.loads(response.read())
            validate_artifact(artifact)

class DurablePilotCallbackHttpTests(unittest.TestCase):
    """The local durable-route compatibility path delegates events durably.

    Production rejects this SQLite/static-route setup and requires the managed
    storage plus OIDC adapter; those requirements are covered by configuration
    tests.  This test keeps the protocol behavior independently executable.
    """

    secret = "durable-route-secret"

    def setUp(self):
        import tempfile
        from pathlib import Path
        from api import control_plane
        from api.pilot_callback import _clear_durable_adapter_for_test
        from deploygrade.engine.control_plane import ControlPlaneStore
        from deploygrade.engine.demo_flow import run

        self.environ = {name: os.environ.get(name) for name in (
            "DEPLOYGRADE_ENVIRONMENT", "DEPLOYGRADE_CONTROL_PLANE_DB",
            "DEPLOYGRADE_AUTH_SECRET", "DEPLOYGRADE_PILOT_CALLBACK_ROUTES",
            "PILOT_CALLBACK_SECRET",
        )}
        self.tempdir = tempfile.TemporaryDirectory()
        database = str(Path(self.tempdir.name) / "control-plane.sqlite3")
        store = ControlPlaneStore(database)
        store.create_organization("org-a")
        store.create_engagement("org-a", "eng-a", "healthcare")
        blueprint_hash = store.store_artifact("org-a", "eng-a", run("mature")["blueprint"])
        approval = store.approve("org-a", "eng-a", blueprint_hash, "reviewer")
        self.job_id = store.create_pilot_job("org-a", "eng-a", blueprint_hash, approval, "approved-repository")
        store.close()
        os.environ.update({
            "DEPLOYGRADE_ENVIRONMENT": "staging",
            "DEPLOYGRADE_CONTROL_PLANE_DB": database,
            "DEPLOYGRADE_AUTH_SECRET": "a" * 32,
            "DEPLOYGRADE_PILOT_CALLBACK_ROUTES": json.dumps({"worker-a": {
                "organization_id": "org-a", "pilot_job_id": self.job_id,
                "blueprint_hash": blueprint_hash, "signing_secret": self.secret,
            }}, sort_keys=True),
            # A valid legacy secret must not affect the durable route behavior.
            "PILOT_CALLBACK_SECRET": "legacy-secret",
        })
        control_plane._store.cache_clear()
        _clear_durable_adapter_for_test()
        self.server = HTTPServer(("127.0.0.1", 0), handler)
        self.thread = Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.event = {
            "event_id": "123e4567-e89b-12d3-a456-426614174200",
            "occurred_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
            "event_type": "PILOT_STARTED", "pilot_job_id": self.job_id,
            "blueprint_hash": blueprint_hash,
        }

    def tearDown(self):
        from api import control_plane
        from api.pilot_callback import _clear_durable_adapter_for_test
        self.server.shutdown()
        self.thread.join()
        self.server.server_close()
        # Close the cached durable store before discarding its factory cache.
        try:
            control_plane.control_plane_store().close()
        except ValueError:
            pass
        for name, value in self.environ.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value
        control_plane._store.cache_clear()
        _clear_durable_adapter_for_test()
        self.tempdir.cleanup()

    def post(self, path="/api/pilot_callback/worker-a", event=None, secret=None):
        raw = json.dumps(event or self.event, sort_keys=True, separators=(",", ":")).encode()
        headers = {
            "Content-Type": "application/json", "Content-Length": str(len(raw)),
            "X-DeployGrade-Signature": hmac.new((secret or self.secret).encode(), raw, hashlib.sha256).hexdigest(),
        }
        connection = HTTPConnection("127.0.0.1", self.server.server_port)
        connection.request("POST", path, body=raw, headers=headers)
        response = connection.getresponse()
        return response.status, json.loads(response.read())

    def test_durable_route_is_durable_and_does_not_use_local_replay_cache(self):
        from api import control_plane
        from api.pilot_callback import _seen_event_ids

        self.assertEqual(202, self.post()[0])
        self.assertEqual({}, dict(_seen_event_ids))
        self.assertEqual("RUNNING", control_plane.control_plane_store().job_status("org-a", self.job_id))
        status, body = self.post()
        self.assertEqual(409, status, body)
        self.assertIn("duplicate", body["error"])

    def test_durable_route_rejects_route_or_lineage_not_explicitly_authorised(self):
        self.assertEqual(400, self.post(path="/api/pilot_callback/not-configured")[0])
        forged = {**self.event, "pilot_job_id": "attacker-job"}
        self.assertEqual(400, self.post(event=forged)[0])
