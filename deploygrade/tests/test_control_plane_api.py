"""Adversarial tests for the signed, tenant-scoped control-plane boundary."""
import os
import tempfile
import unittest
import json
from http.client import HTTPConnection
from http.server import HTTPServer
from threading import Thread
from unittest.mock import patch

from api.control_plane import authenticate_bearer, control_plane_store, execute, handler, make_bearer_token, _store
from deploygrade.engine.control_plane import ControlPlaneStore


def request(action: str, **fields) -> dict:
    return {"$schema": "../schemas/control_plane_request.schema.json", "schema_version": "1.0", "action": action, **fields}


class ControlPlaneApiTests(unittest.TestCase):
    def setUp(self):
        self.secret = "test-secret"
        self.organization = "acme"
        self.subject = "operator"
        self.store = ControlPlaneStore(":memory:")

    def tearDown(self):
        self.store.close()

    def test_signed_identity_controls_tenant_and_approver(self):
        token = make_bearer_token(self.organization, self.subject, self.secret)
        self.assertEqual(authenticate_bearer([f"Bearer {token}"], self.secret), (self.organization, self.subject))
        response = execute(self.store, self.organization, self.subject, request("create_engagement", engagement_id="engagement_a", vertical="healthcare"))
        self.assertEqual(response["organization_id"], self.organization)
        self.assertEqual(response["result"], {"engagement_id": "engagement_a"})

    def test_token_and_tenant_ambiguity_fail_closed(self):
        token = make_bearer_token(self.organization, self.subject, self.secret)
        with self.assertRaisesRegex(ValueError, "authentication required"):
            authenticate_bearer([f"Bearer {token}", f"Bearer {token}"], self.secret)
        with self.assertRaisesRegex(ValueError, "authentication required"):
            authenticate_bearer([f"Bearer {token[:-1]}0"], self.secret)
        forged = request("create_engagement", engagement_id="engagement_a", vertical="healthcare")
        forged["organization_id"] = "other_tenant"
        with self.assertRaisesRegex(ValueError, "unexpected fields"):
            execute(self.store, self.organization, self.subject, forged)

    def test_cross_tenant_engagement_is_rejected(self):
        execute(self.store, "acme", "operator", request("create_engagement", engagement_id="engagement_a", vertical="healthcare"))
        with self.assertRaisesRegex(ValueError, "unknown tenant-scoped engagement"):
            execute(self.store, "other", "operator", request("store_artifact", engagement_id="engagement_a", artifact={"$schema": "../schemas/api_error.schema.json", "schema_version": "1.0", "error": "safe"}))

    def test_oidc_roles_are_enforced_at_each_mutating_action(self):
        payload = request("create_engagement", engagement_id="engagement_a", vertical="healthcare")
        with self.assertRaisesRegex(ValueError, "authorization denied"):
            execute(self.store, self.organization, self.subject, payload, roles=frozenset({"viewer"}))
        response = execute(self.store, self.organization, self.subject, payload, roles=frozenset({"fde"}))
        self.assertEqual(response["result"], {"engagement_id": "engagement_a"})

    def test_production_selects_managed_postgres_and_never_sqlite(self):
        environment = {
            "DEPLOYGRADE_ENVIRONMENT": "production", "DEPLOYGRADE_CONTROL_PLANE_BACKEND": "postgres",
            "DEPLOYGRADE_AUTH_MODE": "oidc", "DEPLOYGRADE_OIDC_ISSUER": "https://issuer.deploygrade.test",
            "DEPLOYGRADE_OIDC_AUDIENCE": "deploygrade-control-plane",
            "DEPLOYGRADE_OIDC_JWKS_URI": "https://issuer.deploygrade.test/jwks",
            "DATABASE_URL": "postgresql://service:secret@db.deploygrade.test/deploygrade?sslmode=verify-full",
        }
        expected = object()
        with patch.dict(os.environ, environment, clear=True), patch("api.control_plane._postgres_store", return_value=expected) as postgres:
            self.assertIs(control_plane_store(), expected)
        postgres.assert_called_once_with(environment["DATABASE_URL"])

    def test_malformed_action_missing_required_fields_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "requires fields"):
            execute(self.store, self.organization, self.subject, request("create_engagement", vertical="healthcare"))

    def test_http_derives_tenant_only_from_signed_header(self):
        with tempfile.NamedTemporaryFile() as database:
            old_secret = os.environ.get("DEPLOYGRADE_AUTH_SECRET")
            old_database = os.environ.get("DEPLOYGRADE_CONTROL_PLANE_DB")
            os.environ["DEPLOYGRADE_AUTH_SECRET"] = self.secret
            os.environ["DEPLOYGRADE_CONTROL_PLANE_DB"] = database.name
            _store.cache_clear()
            server = HTTPServer(("127.0.0.1", 0), handler)
            thread = Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                connection = HTTPConnection("127.0.0.1", server.server_port)
                body = json.dumps(request("create_engagement", engagement_id="engagement_a", vertical="healthcare"))
                connection.request("POST", "/api/control_plane", body=body, headers={"Authorization": f"Bearer {make_bearer_token(self.organization, self.subject, self.secret)}", "Content-Type": "application/json"})
                response = connection.getresponse()
                self.assertEqual(response.status, 200)
                result = json.loads(response.read())
                self.assertEqual(result["organization_id"], self.organization)
                bad = HTTPConnection("127.0.0.1", server.server_port)
                bad.request("POST", "/api/control_plane", body=body, headers={"Content-Type": "application/json"})
                self.assertEqual(bad.getresponse().status, 401)
            finally:
                server.shutdown(); thread.join(); server.server_close()
                _store.cache_clear()
                if old_secret is None: os.environ.pop("DEPLOYGRADE_AUTH_SECRET", None)
                else: os.environ["DEPLOYGRADE_AUTH_SECRET"] = old_secret
                if old_database is None: os.environ.pop("DEPLOYGRADE_CONTROL_PLANE_DB", None)
                else: os.environ["DEPLOYGRADE_CONTROL_PLANE_DB"] = old_database
