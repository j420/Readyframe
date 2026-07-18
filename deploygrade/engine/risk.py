"""Deterministic score-aware alerts with validated numeric evidence."""
from deploygrade.engine.contracts import validate_artifact


def cost_spike(deployment_id, readiness_score, cost):
    """Produce an alert only from fully evidenced score and cost envelopes."""
    for value in (readiness_score, cost):
        if not isinstance(value, dict):
            raise ValueError("risk inputs must be numeric metadata envelopes")
    severity = "CRITICAL" if cost["value"] > 1000 and readiness_score["value"] < 600 else "HIGH"
    evidence_uris = sorted(set(cost["evidence_uris"] + readiness_score["evidence_uris"]))
    artifact = {
        "$schema": "../schemas/alert.schema.json", "schema_version": "1.0",
        "alert_id": f"alert://cost-spike/{deployment_id}", "deployment_id": deployment_id,
        "severity": severity,
        "message": f"Cost spike detected for {deployment_id}; human approval is required.",
        "cost": cost, "readiness_score": readiness_score,
        "remediation": "cap spend and require human approval",
        "investigate_handoff": f"replay://investigate/{deployment_id}",
        "evidence_uris": evidence_uris,
    }
    validate_artifact(artifact)
    return artifact
