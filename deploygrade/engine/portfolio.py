"""Deterministic, schema-valid portfolio prioritization."""
from deploygrade.engine.contracts import validate_artifact


def aggregate(rows, portfolio_id="default"):
    """Order fully explained deployment rows by descending risk then velocity.

    Callers must provide schema-shaped numeric envelopes; metadata-free numbers
    fail closed rather than becoming decision inputs.
    """
    try:
        ordered = sorted(rows, key=lambda row: (-row["risk"]["value"], -row["velocity"]["value"], row["deployment_id"]))
    except (KeyError, TypeError) as error:
        raise ValueError("portfolio rows must include numeric metadata envelopes") from error
    artifact = {
        "$schema": "../schemas/portfolio_dashboard.schema.json",
        "schema_version": "1.0",
        "portfolio_id": portfolio_id,
        "rows": ordered,
    }
    validate_artifact(artifact)
    return artifact
