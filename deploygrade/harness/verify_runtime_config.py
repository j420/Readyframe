"""Fail-closed validation of DeployGrade deployment configuration.

This checks configuration shape only; it never opens network connections or prints
secret values.  Production deployments must set all required values through the
platform secret store before a release can be promoted.
"""
from __future__ import annotations

import os
import sys
from collections.abc import Mapping
from urllib.parse import urlparse

from deploygrade.engine.production_config import ProductionConfigurationError, validate_production_control_plane

PLACEHOLDER_MARKERS = ("replace-with", ".example.invalid", "your-", "changeme")
REQUIRED_PRODUCTION = (
    "DEPLOYGRADE_ENVIRONMENT",
    "DEPLOYGRADE_CONTROL_PLANE_BACKEND",
    "DEPLOYGRADE_AUTH_MODE",
    "DEPLOYGRADE_OIDC_ISSUER",
    "DEPLOYGRADE_OIDC_AUDIENCE",
    "DEPLOYGRADE_OIDC_JWKS_URI",
    "DATABASE_URL",
    "DEPLOYGRADE_WORKER_ENDPOINT",
    "DEPLOYGRADE_WORKER_ID",
    "DEPLOYGRADE_WORKER_CREDENTIAL_REF",
    "DEPLOYGRADE_CONNECTOR_CREDENTIAL_REF",
)
SECRET_NAMES = {
    "DEPLOYGRADE_AUTH_SECRET",
    "SUPABASE_SERVICE_ROLE_KEY",
}


def _https_url(value: str) -> bool:
    parsed = urlparse(value)
    return parsed.scheme == "https" and bool(parsed.netloc) and not parsed.query and not parsed.fragment


def validate(environment: Mapping[str, str]) -> list[str]:
    """Return safe validation errors; no error contains a configuration value."""
    mode = environment.get("DEPLOYGRADE_ENVIRONMENT", "development")
    if mode not in {"development", "staging", "production"}:
        return ["DEPLOYGRADE_ENVIRONMENT must be development, staging, or production"]
    if mode != "production":
        return []
    errors = []
    for name in REQUIRED_PRODUCTION:
        value = environment.get(name, "")
        if not value:
            errors.append(f"{name} is required in production")
        elif any(marker in value.lower() for marker in PLACEHOLDER_MARKERS):
            errors.append(f"{name} must not use an example placeholder in production")
    for name in SECRET_NAMES:
        value = environment.get(name, "")
        if value and len(value) < 32:
            errors.append(f"{name} must be at least 32 characters in production")
    for name in ("DEPLOYGRADE_WORKER_ENDPOINT", "DEPLOYGRADE_OIDC_JWKS_URI"):
        value = environment.get(name, "")
        if value and not _https_url(value):
            errors.append(f"{name} must be an HTTPS origin without query or fragment")
    # Static route maps are a migration-only compatibility mechanism.  New
    # production jobs receive short-lived route credentials transactionally from
    # the managed control plane, so their absence is intentional.
    routes = environment.get("DEPLOYGRADE_PILOT_CALLBACK_ROUTES", "")
    if routes:
        try:
            import json
            decoded = json.loads(routes)
            required_route_fields = {"organization_id", "pilot_job_id", "blueprint_hash", "signing_secret"}
            if not isinstance(decoded, dict) or not decoded:
                raise ValueError
            for route_id, route in decoded.items():
                if not isinstance(route_id, str) or not isinstance(route, dict) or set(route) != required_route_fields:
                    raise ValueError
                secret = route["signing_secret"]
                if not isinstance(secret, str) or len(secret) < 32 or any(marker in secret.lower() for marker in PLACEHOLDER_MARKERS):
                    errors.append("DEPLOYGRADE_PILOT_CALLBACK_ROUTES must contain non-placeholder route secrets of at least 32 characters")
                    break
        except (ValueError, TypeError, json.JSONDecodeError):
            errors.append("DEPLOYGRADE_PILOT_CALLBACK_ROUTES must be a valid explicit route authorization JSON object")
    try:
        validate_production_control_plane(environment)
    except ProductionConfigurationError as error:
        errors.append(str(error))
    deployed = environment.get("DEPLOYGRADE_DEPLOYED_URL", "")
    if deployed and not _https_url(deployed):
        errors.append("DEPLOYGRADE_DEPLOYED_URL must be an HTTPS origin without query or fragment")
    return errors


def main() -> None:
    errors = validate(os.environ)
    if errors:
        print("Runtime configuration validation failed:", file=sys.stderr)
        for error in errors:
            print(f"- {error}", file=sys.stderr)
        raise SystemExit(1)
    print("Runtime configuration shape validated")


if __name__ == "__main__":
    main()
