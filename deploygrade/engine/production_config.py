"""Production-only configuration contracts that fail closed before API startup."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping
from urllib.parse import parse_qs, urlparse

from deploygrade.engine.identity import IdentityError, OIDCConfiguration


class ProductionConfigurationError(ValueError):
    """A safe configuration error that never includes a secret value."""


@dataclass(frozen=True)
class ManagedPostgresConfiguration:
    """Validated server-only managed Postgres connection contract.

    A database driver is deliberately not vendored into this stdlib repository.
    Callers may use this contract only after deploying an adapter that implements
    ``ControlPlaneStorage`` and performs tenant-scoped transactions/RLS checks.
    """

    database_url: str

    @classmethod
    def from_environment(cls, environment: Mapping[str, str]) -> "ManagedPostgresConfiguration":
        value = environment.get("DATABASE_URL", "")
        parsed = urlparse(value)
        if parsed.scheme not in {"postgres", "postgresql"} or not parsed.hostname or not parsed.path or parsed.path == "/":
            raise ProductionConfigurationError("DATABASE_URL must be a managed Postgres URL")
        if parsed.hostname in {"localhost", "127.0.0.1", "::1"}:
            raise ProductionConfigurationError("DATABASE_URL must not target a local host in production")
        options = parse_qs(parsed.query, keep_blank_values=True)
        if options.get("sslmode", [""])[0] not in {"require", "verify-ca", "verify-full"}:
            raise ProductionConfigurationError("DATABASE_URL must require TLS with sslmode=require, verify-ca, or verify-full")
        return cls(database_url=value)


def validate_production_control_plane(environment: Mapping[str, str]) -> None:
    """Require managed storage and cryptographically verified OIDC before a production API starts."""
    if environment.get("DEPLOYGRADE_ENVIRONMENT", "development") != "production":
        return
    if environment.get("DEPLOYGRADE_CONTROL_PLANE_BACKEND") != "postgres":
        raise ProductionConfigurationError("production control-plane backend must be postgres")
    ManagedPostgresConfiguration.from_environment(environment)
    if environment.get("DEPLOYGRADE_AUTH_MODE") != "oidc":
        raise ProductionConfigurationError("production control-plane authentication must use oidc")
    try:
        OIDCConfiguration.from_environment(environment)
    except IdentityError as error:
        raise ProductionConfigurationError(str(error)) from error
