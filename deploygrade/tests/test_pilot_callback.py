import hashlib
import hmac
import json
import os
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
