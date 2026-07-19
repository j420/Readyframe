"""Authenticated, tenant-scoped control-plane API for Vercel.

Development uses a deterministic HMAC bearer fixture. Production constructs a
PyJWT-backed OIDC/JWKS verifier from server-only configuration, validates the
JWT signature before claims, and derives tenant and operator only from that
verified identity; request JSON and query parameters cannot select a tenant.
"""
from http.server import BaseHTTPRequestHandler
import hashlib
import hmac
import json
import os
import re
from functools import lru_cache

from api.responses import error_artifact
from deploygrade.engine.contracts import validate_artifact
from deploygrade.engine.control_plane import ControlPlaneStorage, ControlPlaneStore, validate_sqlite_database_path
from deploygrade.engine.identity import AuthorizationError, IdentityError, OIDCIdentityVerifier, production_identity_verifier_from_environment
from deploygrade.engine.postgres_control_plane import PostgresControlPlaneStore
from deploygrade.engine.production_config import ManagedPostgresConfiguration, ProductionConfigurationError, validate_production_control_plane


MAX_BODY_BYTES = 262_144
_IDENTITY = re.compile(r"^[a-z0-9][a-z0-9_-]{2,63}$")


class AuthenticationError(ValueError):
    """A deliberately non-specific authentication denial for HTTP callers."""


def make_bearer_token(organization_id: str, subject: str, secret: str) -> str:
    """Create a deterministic token for controlled deployment provisioning/tests."""
    if not isinstance(secret, str) or not secret or not _IDENTITY.fullmatch(organization_id) or not _IDENTITY.fullmatch(subject):
        raise ValueError("token identities and secret must be valid")
    signed = f"dg1:{organization_id}:{subject}".encode("utf-8")
    signature = hmac.new(secret.encode("utf-8"), signed, hashlib.sha256).hexdigest()
    return f"dg1.{organization_id}.{subject}.{signature}"


def authenticate_bearer(values: list[str], secret: str) -> tuple[str, str]:
    """Return signed organization and subject; any ambiguity is denied."""
    if not isinstance(secret, str) or not secret:
        raise AuthenticationError("control-plane authentication is not configured")
    if len(values) != 1 or not values[0].startswith("Bearer "):
        raise AuthenticationError("authentication required")
    parts = values[0][7:].split(".")
    if len(parts) != 4 or parts[0] != "dg1":
        raise AuthenticationError("authentication required")
    _, organization_id, subject, signature = parts
    if not _IDENTITY.fullmatch(organization_id) or not _IDENTITY.fullmatch(subject) or not re.fullmatch(r"[a-f0-9]{64}", signature):
        raise AuthenticationError("authentication required")
    expected = make_bearer_token(organization_id, subject, secret).rsplit(".", 1)[1]
    if not hmac.compare_digest(signature, expected):
        raise AuthenticationError("authentication required")
    return organization_id, subject


@lru_cache(maxsize=4)
def _store(database_path: str) -> ControlPlaneStore:
    validate_sqlite_database_path(database_path, allow_memory=False)
    return ControlPlaneStore(database_path)


@lru_cache(maxsize=4)
def _postgres_store(database_url: str) -> PostgresControlPlaneStore:
    """Create the managed, RLS-backed production store only after validation."""
    return PostgresControlPlaneStore(database_url)


_production_identity_verifier: OIDCIdentityVerifier | None = None

def configure_production_identity_verifier(verifier: OIDCIdentityVerifier | None) -> None:
    """Install a cryptographic OIDC verifier from trusted server bootstrap only.

    The repository never builds this from unverified HTTP headers or decoded JWT
    claims.  Production remains unavailable until platform bootstrap injects an
    adapter that verifies signatures against the configured issuer/JWKS.
    """
    global _production_identity_verifier
    _production_identity_verifier = verifier

def validate_control_plane_environment() -> str:
    """Fail closed unless the selected storage and identity mode are safe."""
    if os.environ.get("DEPLOYGRADE_ENVIRONMENT", "development") == "production":
        validate_production_control_plane(os.environ)
        return ManagedPostgresConfiguration.from_environment(os.environ).database_url
    if not os.environ.get("DEPLOYGRADE_AUTH_SECRET"):
        raise ValueError("control-plane authentication is not configured")
    path = os.environ.get("DEPLOYGRADE_CONTROL_PLANE_DB")
    if not path:
        raise ValueError("control-plane storage is not configured")
    return str(validate_sqlite_database_path(path, allow_memory=False))

def authenticated_identity(values: list[str]) -> tuple[str, str, frozenset[str] | None]:
    """Authenticate development HMAC or production cryptographically verified OIDC."""
    if os.environ.get("DEPLOYGRADE_ENVIRONMENT", "development") != "production":
        organization_id, subject = authenticate_bearer(values, os.environ.get("DEPLOYGRADE_AUTH_SECRET", ""))
        return organization_id, subject, None
    try:
        validate_production_control_plane(os.environ)
        verifier = _production_identity_verifier or production_identity_verifier_from_environment(os.environ)
        identity = verifier.authenticate(values)
    except (IdentityError, ProductionConfigurationError) as error:
        raise AuthenticationError("authentication required") from error
    return identity.organization_id, identity.subject, identity.roles


def control_plane_store() -> ControlPlaneStorage:
    """Get the only permitted durable store for the active deployment mode.

    Production selects the psycopg/RLS adapter. Development and controlled test
    environments retain the local SQLite implementation. There is no production
    fallback between the two paths.
    """
    configured_database = validate_control_plane_environment()
    if os.environ.get("DEPLOYGRADE_ENVIRONMENT", "development") == "production":
        return _postgres_store(configured_database)
    return _store(configured_database)


def _required(payload: dict, *names: str) -> None:
    missing = [name for name in names if name not in payload]
    if missing:
        raise ValueError(f"action requires fields: {', '.join(missing)}")


def execute(store: ControlPlaneStorage, organization_id: str, subject: str, payload: dict, *, roles: frozenset[str] | None = None) -> dict:
    """Execute one tenant-scoped operation after validating its request artifact."""
    validate_artifact(payload)
    # Token-authenticated organizations are provisioned explicitly here, rather
    # than ever accepting an organization id from an untrusted request.
    try:
        store.create_organization(organization_id)
    except Exception as error:
        if "UNIQUE constraint failed" not in str(error):
            raise
    action = payload["action"]
    # Local HMAC fixtures have no role claim.  Real production OIDC identities
    # must pass action-level authorization before any state mutation.
    allowed_roles = {
        "create_engagement": {"owner", "fde"},
        "store_artifact": {"owner", "fde", "worker"},
        "approve": {"owner", "fde", "reviewer"},
        "create_pilot_job": {"owner", "fde"},
        "job_status": {"owner", "fde", "reviewer", "viewer", "worker"},
    }
    if roles is not None and not allowed_roles[action].intersection(roles):
        raise AuthorizationError("authorization denied")
    if action == "create_engagement":
        _required(payload, "engagement_id", "vertical")
        store.create_engagement(organization_id, payload["engagement_id"], payload["vertical"])
        result = {"engagement_id": payload["engagement_id"]}
    elif action == "store_artifact":
        _required(payload, "engagement_id", "artifact")
        result = {"artifact_hash": store.store_artifact(organization_id, payload["engagement_id"], payload["artifact"])}
    elif action == "approve":
        _required(payload, "engagement_id", "artifact_hash")
        result = {"approval_id": store.approve(organization_id, payload["engagement_id"], payload["artifact_hash"], subject, payload.get("decision", "APPROVED"))}
    elif action == "create_pilot_job":
        _required(payload, "engagement_id", "blueprint_hash", "approval_id", "sandbox_repository")
        result = {"pilot_job_id": store.create_pilot_job(organization_id, payload["engagement_id"], payload["blueprint_hash"], payload["approval_id"], payload["sandbox_repository"])}
    elif action == "job_status":
        _required(payload, "pilot_job_id")
        result = {"status": store.job_status(organization_id, payload["pilot_job_id"])}
    else:  # schema validation makes this unreachable; retain the fail-closed boundary.
        raise ValueError("unsupported control-plane action")
    response = {"$schema": "../schemas/control_plane_response.schema.json", "schema_version": "1.0", "action": action, "organization_id": organization_id, "result": result}
    validate_artifact(response)
    return response


class handler(BaseHTTPRequestHandler):
    """Vercel handler for authenticated POST /api/control_plane."""
    def _send(self, status: int, payload: dict) -> None:
        body = json.dumps(payload, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self) -> None:  # noqa: N802
        try:
            organization_id, subject, roles = authenticated_identity(self.headers.get_all("Authorization", []))
            lengths = self.headers.get_all("Content-Length", [])
            if len(lengths) != 1:
                raise ValueError("request must include exactly one Content-Length")
            length = int(lengths[0])
            if length <= 0 or length > MAX_BODY_BYTES:
                raise ValueError("request body must be between 1 and 262144 bytes")
            if self.headers.get("Content-Type", "").split(";", 1)[0].lower() != "application/json":
                raise ValueError("Content-Type must be application/json")
            raw = self.rfile.read(length)
            if len(raw) != length:
                raise ValueError("incomplete request body")
            payload = json.loads(raw.decode("utf-8"))
            self._send(200, execute(control_plane_store(), organization_id, subject, payload, roles=roles))
        except AuthenticationError:
            self._send(401, error_artifact("authentication required"))
        except AuthorizationError:
            self._send(403, error_artifact("authorization denied"))
        except IdentityError:
            self._send(401, error_artifact("authentication required"))
        except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as error:
            self._send(400, error_artifact(str(error)))
        except Exception:
            self._send(500, error_artifact("internal server error"))

    def _method_not_allowed(self) -> None:
        self._send(405, error_artifact("use authenticated POST with a control-plane request artifact"))

    do_GET = do_PUT = do_PATCH = do_DELETE = do_HEAD = do_OPTIONS = _method_not_allowed
