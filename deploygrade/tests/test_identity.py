import base64
import json
import unittest
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
from threading import Thread

import jwt
from cryptography.hazmat.primitives.asymmetric import rsa


from deploygrade.engine.identity import IdentityError, OIDCConfiguration, OIDCIdentityVerifier, PyJWTJWKSVerifier, production_identity_verifier_from_environment
from deploygrade.engine.production_config import ProductionConfigurationError, validate_production_control_plane


def token(header: dict, claims: dict) -> str:
    encode = lambda value: base64.urlsafe_b64encode(json.dumps(value, separators=(",", ":")).encode()).rstrip(b"=").decode()
    return f"{encode(header)}.{encode(claims)}.signature"


class OIDCIdentityTests(unittest.TestCase):
    def setUp(self):
        self.config = OIDCConfiguration("https://issuer.deploygrade.test", "deploygrade-control-plane")
        self.claims = {
            "iss": "https://issuer.deploygrade.test", "aud": "deploygrade-control-plane",
            "sub": "user-123", "organization_id": "acme", "roles": ["reviewer"],
            "iat": 900, "nbf": 900, "exp": 1100,
        }
        self.header = {"typ": "JWT", "alg": "RS256", "kid": "current"}

    def test_claims_are_never_accepted_without_signature_verifier(self):
        verifier = OIDCIdentityVerifier(self.config, clock=lambda: 1000)
        with self.assertRaisesRegex(IdentityError, "authentication required"):
            verifier.authenticate([f"Bearer {token(self.header, self.claims)}"])

    def test_verified_identity_has_tenant_and_roles(self):
        seen = []
        verifier = OIDCIdentityVerifier(self.config, lambda raw, header: seen.append((raw, header)) or True, clock=lambda: 1000)
        identity = verifier.authenticate([f"Bearer {token(self.header, self.claims)}"])
        self.assertEqual((identity.organization_id, identity.subject, identity.roles), ("acme", "user-123", frozenset({"reviewer"})))
        self.assertEqual(len(seen), 1)

    def test_rejects_wrong_issuer_expiry_role_and_algorithm(self):
        for field, value in (("iss", "https://other.test"), ("exp", 800), ("roles", ["admin"])):
            claims = dict(self.claims); claims[field] = value
            verifier = OIDCIdentityVerifier(self.config, lambda *_: True, clock=lambda: 1000)
            with self.assertRaises(IdentityError):
                verifier.authenticate([f"Bearer {token(self.header, claims)}"])
        verifier = OIDCIdentityVerifier(self.config, lambda *_: True, clock=lambda: 1000)
        with self.assertRaises(IdentityError):
            verifier.authenticate([f"Bearer {token({**self.header, 'alg': 'none'}, self.claims)}"])


    def test_pyjwt_jwks_verifier_cryptographically_verifies_local_rotating_key(self):
        private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        public = private_key.public_key().public_numbers()
        def b64(value):
            raw = value.to_bytes((value.bit_length() + 7) // 8, "big")
            return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")
        jwks = {"keys": [{"kty": "RSA", "kid": "local-key", "use": "sig", "alg": "RS256", "n": b64(public.n), "e": b64(public.e)}]}
        class JWKSHandler(BaseHTTPRequestHandler):
            def do_GET(self):
                body = json.dumps(jwks).encode("utf-8")
                self.send_response(200); self.send_header("Content-Type", "application/json"); self.send_header("Content-Length", str(len(body))); self.end_headers(); self.wfile.write(body)
            def log_message(self, *args):
                return
        server = HTTPServer(("127.0.0.1", 0), JWKSHandler)
        thread = Thread(target=server.serve_forever, daemon=True); thread.start()
        try:
            configuration = OIDCConfiguration(self.config.issuer, self.config.audience, f"http://127.0.0.1:{server.server_port}/jwks")
            now = int(time.time())
            signed = jwt.encode({**self.claims, "iat": now - 1, "nbf": now - 1, "exp": now + 60}, private_key, algorithm="RS256", headers={"kid": "local-key", "typ": "JWT"})
            verifier = OIDCIdentityVerifier(configuration, PyJWTJWKSVerifier(configuration, allow_insecure_loopback=True))
            self.assertEqual(verifier.authenticate([f"Bearer {signed}"]).subject, "user-123")
            self.assertTrue(signed.endswith(signed.split(".")[-1]))
            forged = signed.rsplit(".", 1)[0] + ".invalid"
            with self.assertRaises(IdentityError):
                verifier.authenticate([f"Bearer {forged}"])
        finally:
            server.shutdown(); thread.join(); server.server_close()

    def test_production_factory_requires_https_jwks_endpoint(self):
        environment = {"DEPLOYGRADE_OIDC_ISSUER": "https://issuer.deploygrade.test", "DEPLOYGRADE_OIDC_AUDIENCE": "deploygrade-control-plane", "DEPLOYGRADE_OIDC_JWKS_URI": "http://127.0.0.1/jwks"}
        with self.assertRaises(IdentityError):
            production_identity_verifier_from_environment(environment)

    def test_production_configuration_requires_managed_postgres_and_oidc(self):
        environment = {
            "DEPLOYGRADE_ENVIRONMENT": "production", "DEPLOYGRADE_CONTROL_PLANE_BACKEND": "postgres",
            "DEPLOYGRADE_AUTH_MODE": "oidc", "DEPLOYGRADE_OIDC_ISSUER": "https://issuer.deploygrade.test",
            "DEPLOYGRADE_OIDC_AUDIENCE": "deploygrade-control-plane",
            "DEPLOYGRADE_OIDC_JWKS_URI": "https://issuer.deploygrade.test/.well-known/jwks.json",
            "DATABASE_URL": "postgresql://service:secret@db.deploygrade.test/deploygrade?sslmode=verify-full",
        }
        validate_production_control_plane(environment)
        environment["DATABASE_URL"] = "postgresql://service:secret@localhost/deploygrade?sslmode=disable"
        with self.assertRaises(ProductionConfigurationError):
            validate_production_control_plane(environment)


if __name__ == "__main__":
    unittest.main()
