"""Fail-closed OIDC identity boundary for production control-plane callers.

Production verifies compact JWTs with the maintained PyJWT cryptographic verifier
and a configured HTTPS JWKS endpoint.  Claims are never trusted until signature
verification has succeeded.  The remaining issuer, audience, tenant, role, and
clock constraints are then checked by this module.
"""
from __future__ import annotations

import base64
import json
import time
from dataclasses import dataclass
from typing import Any, Callable, Mapping, Protocol
from urllib.parse import urlparse


class IdentityError(ValueError):
    """Non-specific authentication/authorization denial."""


class AuthorizationError(IdentityError):
    """Authenticated caller lacks authority for the requested action."""


class JwtSignatureVerifier(Protocol):
    """Verifier that validates the original compact JWT cryptographically."""

    def __call__(self, token: str, header: Mapping[str, Any]) -> bool: ...


_ALLOWED_ALGORITHMS = frozenset({"RS256", "ES256"})
_ALLOWED_ROLES = frozenset({"owner", "fde", "reviewer", "viewer", "worker"})


def _https_origin(value: str, *, field: str) -> str:
    parsed = urlparse(value)
    if parsed.scheme != "https" or not parsed.netloc or parsed.query or parsed.fragment:
        raise IdentityError(f"{field} must be an HTTPS URL without query or fragment")
    return value.rstrip("/")


def _base64url_json(part: str, *, label: str) -> dict[str, Any]:
    try:
        raw = base64.urlsafe_b64decode(part + "=" * (-len(part) % 4))
        value = json.loads(raw.decode("utf-8"))
    except (ValueError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise IdentityError("authentication required") from error
    if not isinstance(value, dict):
        raise IdentityError("authentication required")
    return value


@dataclass(frozen=True)
class OIDCConfiguration:
    """Explicit production identity requirements, sourced from server-only config."""

    issuer: str
    audience: str
    jwks_uri: str | None = None
    organization_claim: str = "organization_id"
    roles_claim: str = "roles"
    clock_skew_seconds: int = 60

    def __post_init__(self) -> None:
        _https_origin(self.issuer, field="OIDC issuer")
        if self.jwks_uri is not None:
            # The production factory below requires HTTPS.  Permit explicit loopback
            # HTTP only when constructing a hermetic local-JWKS test verifier.
            parsed_jwks = urlparse(self.jwks_uri)
            if parsed_jwks.query or parsed_jwks.fragment or not parsed_jwks.netloc or parsed_jwks.scheme not in {"https", "http"}:
                raise IdentityError("OIDC JWKS URI must be an HTTPS URL without query or fragment")
        if not isinstance(self.audience, str) or not self.audience:
            raise IdentityError("OIDC audience must be configured")
        if not self.organization_claim or not self.roles_claim:
            raise IdentityError("OIDC claim names must be configured")
        if not 0 <= self.clock_skew_seconds <= 300:
            raise IdentityError("OIDC clock skew must be between 0 and 300 seconds")

    @classmethod
    def from_environment(cls, environment: Mapping[str, str]) -> "OIDCConfiguration":
        issuer = environment.get("DEPLOYGRADE_OIDC_ISSUER", "")
        audience = environment.get("DEPLOYGRADE_OIDC_AUDIENCE", "")
        jwks_uri = environment.get("DEPLOYGRADE_OIDC_JWKS_URI", "")
        if not jwks_uri:
            raise IdentityError("OIDC JWKS URI must be configured")
        _https_origin(jwks_uri, field="OIDC JWKS URI")
        return cls(
            issuer=issuer,
            audience=audience,
            jwks_uri=jwks_uri,
            organization_claim=environment.get("DEPLOYGRADE_OIDC_ORGANIZATION_CLAIM", "organization_id"),
            roles_claim=environment.get("DEPLOYGRADE_OIDC_ROLES_CLAIM", "roles"),
        )


class PyJWTJWKSVerifier:
    """Cryptographically verify a token using PyJWT and a rotating JWKS.

    ``allow_insecure_loopback`` exists solely for hermetic local JWKS transport
    tests. Production bootstrap never enables it, so configuration cannot use
    HTTP or a caller-controlled local endpoint.
    """

    def __init__(self, configuration: OIDCConfiguration, *, allow_insecure_loopback: bool = False, clock_skew_seconds: int | None = None):
        if not configuration.jwks_uri:
            raise IdentityError("OIDC JWKS URI must be configured")
        parsed = urlparse(configuration.jwks_uri)
        loopback = parsed.scheme == "http" and parsed.hostname in {"127.0.0.1", "::1", "localhost"}
        if parsed.scheme != "https" and not (allow_insecure_loopback and loopback):
            raise IdentityError("OIDC JWKS URI must use HTTPS")
        try:
            import jwt
        except ImportError as error:  # pragma: no cover - exercised by deployment packaging.
            raise IdentityError("PyJWT cryptographic verifier is not installed") from error
        self._jwt = jwt
        self._configuration = configuration
        self._client = jwt.PyJWKClient(configuration.jwks_uri, cache_keys=True, lifespan=300)
        self._leeway = configuration.clock_skew_seconds if clock_skew_seconds is None else clock_skew_seconds

    def __call__(self, token: str, header: Mapping[str, Any]) -> bool:
        algorithm = header.get("alg")
        if algorithm not in _ALLOWED_ALGORITHMS:
            return False
        try:
            signing_key = self._client.get_signing_key_from_jwt(token)
            self._jwt.decode(
                token,
                signing_key.key,
                algorithms=[algorithm],
                audience=self._configuration.audience,
                issuer=self._configuration.issuer,
                leeway=self._leeway,
                options={"require": ["exp", "iat", "nbf", "iss", "aud", "sub"]},
            )
        except self._jwt.PyJWTError:
            return False
        except (OSError, ValueError):
            return False
        return True


@dataclass(frozen=True)
class Identity:
    organization_id: str
    subject: str
    roles: frozenset[str]
    issuer: str

    def require_role(self, *allowed: str) -> None:
        if not set(allowed).intersection(self.roles):
            raise AuthorizationError("authorization denied")


class OIDCIdentityVerifier:
    """Verify signed OIDC JWT claims and expose a tenant-bound identity."""

    def __init__(self, configuration: OIDCConfiguration, signature_verifier: JwtSignatureVerifier | None = None, *, clock: Callable[[], float] = time.time):
        self.configuration = configuration
        self.signature_verifier = signature_verifier
        self.clock = clock

    def authenticate(self, authorization_values: list[str]) -> Identity:
        if len(authorization_values) != 1 or not authorization_values[0].startswith("Bearer "):
            raise IdentityError("authentication required")
        token = authorization_values[0][7:]
        parts = token.split(".")
        if len(parts) != 3 or not all(parts):
            raise IdentityError("authentication required")
        header = _base64url_json(parts[0], label="header")
        if header.get("typ") != "JWT" or header.get("alg") not in _ALLOWED_ALGORITHMS or not isinstance(header.get("kid"), str) or not header["kid"]:
            raise IdentityError("authentication required")
        if self.signature_verifier is None or self.signature_verifier(token, header) is not True:
            raise IdentityError("authentication required")
        claims = _base64url_json(parts[1], label="claims")
        return self._claims_identity(claims)

    def _claims_identity(self, claims: Mapping[str, Any]) -> Identity:
        now = self.clock()
        issuer = claims.get("iss")
        subject = claims.get("sub")
        organization_id = claims.get(self.configuration.organization_claim)
        audience = claims.get("aud")
        if issuer != self.configuration.issuer or not isinstance(subject, str) or not subject or not isinstance(organization_id, str) or not organization_id:
            raise IdentityError("authentication required")
        audiences = {audience} if isinstance(audience, str) else set(audience) if isinstance(audience, list) and all(isinstance(item, str) for item in audience) else set()
        if self.configuration.audience not in audiences:
            raise IdentityError("authentication required")
        for name in ("exp", "iat", "nbf"):
            if not isinstance(claims.get(name), (int, float)) or isinstance(claims.get(name), bool):
                raise IdentityError("authentication required")
        skew = self.configuration.clock_skew_seconds
        if claims["exp"] <= now - skew or claims["iat"] > now + skew or claims["nbf"] > now + skew:
            raise IdentityError("authentication required")
        roles = claims.get(self.configuration.roles_claim)
        if not isinstance(roles, list) or not roles or not all(isinstance(role, str) and role in _ALLOWED_ROLES for role in roles):
            raise AuthorizationError("authorization denied")
        return Identity(organization_id=organization_id, subject=subject, roles=frozenset(roles), issuer=issuer)


def production_identity_verifier_from_environment(environment: Mapping[str, str]) -> OIDCIdentityVerifier:
    """Build the only supported production verifier from pinned server config."""
    configuration = OIDCConfiguration.from_environment(environment)
    return OIDCIdentityVerifier(configuration, PyJWTJWKSVerifier(configuration))
