import json
import unittest

from deploygrade.harness.verify_runtime_config import validate


class RuntimeConfigTests(unittest.TestCase):
    def test_development_requires_no_production_secrets(self):
        self.assertEqual(validate({"DEPLOYGRADE_ENVIRONMENT": "development"}), [])

    def test_production_rejects_missing_and_placeholder_values(self):
        errors = validate({"DEPLOYGRADE_ENVIRONMENT": "production"})
        self.assertTrue(any("DEPLOYGRADE_OIDC_ISSUER" in error or "authentication must use oidc" in error for error in errors))
        self.assertTrue(any("DEPLOYGRADE_WORKER_ENDPOINT" in error for error in errors))

    def test_production_accepts_complete_safe_shape(self):
        environment = {
            "DEPLOYGRADE_ENVIRONMENT": "production",
            "DEPLOYGRADE_CONTROL_PLANE_BACKEND": "postgres",
            "DEPLOYGRADE_AUTH_MODE": "oidc",
            "DEPLOYGRADE_OIDC_ISSUER": "https://issuer.deploygrade.test",
            "DEPLOYGRADE_OIDC_AUDIENCE": "deploygrade-control-plane",
            "DEPLOYGRADE_OIDC_JWKS_URI": "https://issuer.deploygrade.test/.well-known/jwks.json",
            "DATABASE_URL": "postgresql://service:secret@db.deploygrade.test/deploygrade?sslmode=verify-full",
            "DEPLOYGRADE_WORKER_ENDPOINT": "https://worker.deploygrade.test",
            "DEPLOYGRADE_WORKER_ID": "worker-prod",
            "DEPLOYGRADE_WORKER_CREDENTIAL_REF": "secret-manager://worker/credential",
            "DEPLOYGRADE_CONNECTOR_CREDENTIAL_REF": "secret-manager://scm/installation",
            "DEPLOYGRADE_DEPLOYED_URL": "https://app.deploygrade.test",
        }
        self.assertEqual(validate(environment), [])

    def test_production_rejects_invalid_durable_callback_routes(self):
        errors = validate({
            "DEPLOYGRADE_ENVIRONMENT": "production",
            "DEPLOYGRADE_PILOT_CALLBACK_ROUTES": "not-json",
        })
        self.assertTrue(any("DEPLOYGRADE_PILOT_CALLBACK_ROUTES" in error for error in errors))

    def test_rejects_bad_deployed_url_without_exposing_it(self):
        errors = validate({"DEPLOYGRADE_ENVIRONMENT": "production", "DEPLOYGRADE_DEPLOYED_URL": "http://bad.example"})
        self.assertIn("DEPLOYGRADE_DEPLOYED_URL must be an HTTPS origin without query or fragment", errors)


if __name__ == "__main__":
    unittest.main()
