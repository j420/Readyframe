"""Deterministic incident replay into validated investigation artifacts."""
from deploygrade.engine.contracts import validate_artifact


def investigate(alert, outcome_record="outcome://unavailable"):
    """Refuse unvalidated alerts and preserve their audit/evidence lineage."""
    validate_artifact(alert)
    if not alert["$schema"].endswith("/alert.schema.json"):
        raise ValueError("replay requires an alert artifact")
    artifact = {
        "$schema": "../schemas/investigation_report.schema.json", "schema_version": "1.0",
        "alert_id": alert["alert_id"], "deployment_id": alert["deployment_id"],
        "timeline": ["metric breach", "tool call diverged", "compensating rollback fired"],
        "finding": "Cost-spike alert requires human investigation before further execution.",
        "failed_control": "NIST SP 800-53 CM-5",
        "remediation": "add automated rollback verification",
        "outcome_record": outcome_record,
        "tool_call": "merge -> metric breach -> git revert",
        "evidence_uris": alert["evidence_uris"],
    }
    validate_artifact(artifact)
    return artifact
