"""Schema-valid shared response artifacts for Vercel API handlers."""

from deploygrade.engine.contracts import validate_artifact


def error_artifact(message: str) -> dict:
    """Build an API-boundary error artifact and validate it before sending."""
    if not isinstance(message, str) or not message:
        raise ValueError("API error message must be a non-empty string")
    payload = {"$schema": "../schemas/api_error.schema.json", "schema_version": "1.0", "error": message}
    validate_artifact(payload)
    return payload
