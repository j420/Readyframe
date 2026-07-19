"""Schema-valid network-effect readouts from accepted anonymized records."""
from deploygrade.engine.contracts import validate_artifact
from deploygrade.engine.knowledge import load
from deploygrade.engine.flywheel import refit


def readout(path="deploygrade/knowledge/outcome_records_clean.jsonl", vertical="healthcare"):
    accepted, _ = load(path)
    refit_result = refit(path, vertical)
    if refit_result["status"] != "PUBLISHED":
        raise ValueError("network readout is unavailable until the vertical refit publishes")
    evidence_uris = [f"knowledge://accepted/{vertical}", f"rubric-refit://{refit_result['corpus_hash']}"]
    rubric_version = refit_result["rubric_version"]
    confidence = 1.0
    meta = lambda value: {"value": value, "confidence": confidence, "evidence_uris": evidence_uris, "rubric_version": rubric_version}
    artifact = {
        "$schema": "../schemas/network_readout.schema.json", "schema_version": "1.0", "vertical": vertical,
        "customers_graded": meta(len({row["anonymized_id"] for row, _ in accepted})),
        "holdout_accuracy_before": meta(refit_result["baseline_accuracy"]),
        "holdout_accuracy_after": meta(refit_result["holdout_accuracy"]),
        "prior_deployments": meta(len(accepted)), "evidence_uris": evidence_uris,
    }
    validate_artifact(artifact)
    return artifact
