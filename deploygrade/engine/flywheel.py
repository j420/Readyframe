"""Transparent deterministic vertical rubric refit; never model fine-tuning."""
import hashlib
import json

from deploygrade.engine.contracts import validate_artifact
from deploygrade.engine.knowledge import load
from deploygrade.engine.rubrics import content_hash, load as load_rubric, publication
from deploygrade.engine.score import score_inventory


BASE_VERSION = "2026.07.0"
PUBLISHED_VERSION = "2026.07.2"
SPLIT_VERSION = "sha256-anonymized-id-v1"
MIN_ACCEPTED_RECORDS = 20


def _canonical_hash(value: object) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _split(rows: list[dict]) -> tuple[list[dict], list[dict]]:
    """Produce a reproducible 80/20 split independent of source-file ordering."""
    ordered = sorted(rows, key=lambda row: (hashlib.sha256(row["anonymized_id"].encode("utf-8")).hexdigest(), row["deployment_id"]))
    holdout_size = max(1, len(ordered) // 5)
    return ordered[:-holdout_size], ordered[-holdout_size:]


def _observed_class(row: dict) -> str:
    return "rollback" if row["observed"]["outcome"] == "rollback" else "safe"


def _candidate_class(row: dict) -> str:
    return "rollback" if row["predicted"]["outcome"] == "low_rollback" else "safe"


def _accuracy(rows: list[dict], classifier) -> float:
    return round(sum(classifier(row) == _observed_class(row) for row in rows) / len(rows), 4)


def refit(path, vertical):
    accepted, quarantined = load(path)
    rows = [row for row, _ in accepted if row["vertical"] == vertical]
    corpus_hash = _canonical_hash(rows)
    training, holdout = _split(rows) if rows else ([], [])
    common = {"$schema": "../schemas/rubric_refit.schema.json", "schema_version": "1.0", "vertical": vertical,
              "corpus_hash": corpus_hash, "split_version": SPLIT_VERSION, "accepted_records": len(rows), "holdout_records": len(holdout)}
    if any(reason == "untrusted_source" for _, reason in quarantined):
        result = {**common, "status": "REFUSED", "reason": "holdout validation refused untrusted poison corpus"}
        validate_artifact(result)
        return result
    if len(rows) < MIN_ACCEPTED_RECORDS:
        result = {**common, "status": "REFUSED", "reason": "insufficient accepted evidence for deterministic refit"}
        validate_artifact(result)
        return result
    majority = max(("safe", "rollback"), key=lambda outcome: (sum(_observed_class(row) == outcome for row in training), outcome))
    baseline = _accuracy(holdout, lambda _: majority)
    candidate = _accuracy(holdout, _candidate_class)
    if candidate <= baseline:
        result = {**common, "status": "REFUSED", "reason": "holdout accuracy did not improve"}
        validate_artifact(result)
        return result
    try:
        release = publication(PUBLISHED_VERSION)
    except ValueError:
        result = {**common, "status": "REFUSED", "reason": "rubric publication provenance is unavailable"}
        validate_artifact(result)
        return result
    if release["vertical"] != vertical or release["corpus_hash"] != corpus_hash:
        result = {**common, "status": "REFUSED", "reason": "corpus is not the approved immutable publication corpus"}
        validate_artifact(result)
        return result
    before, after = load_rubric(BASE_VERSION), load_rubric(PUBLISHED_VERSION)
    weights = {item["id"]: item["weight"] for item in after["dimensions"]}
    old_weights = {item["id"]: item["weight"] for item in before["dimensions"]}
    result = {**common, "status": "PUBLISHED", "rubric_version": PUBLISHED_VERSION, "rubric_hash": content_hash(PUBLISHED_VERSION), "parent_rubric_version": release["parent_rubric_version"], "parent_rubric_hash": release["parent_rubric_hash"], "approval_id": release["approval_id"], "holdout_accuracy": candidate, "baseline_accuracy": baseline, "weights": weights, "diff": {name: round(weights[name] - old_weights[name], 2) for name in weights if weights[name] != old_weights[name]}, "reason": "holdout accuracy improved using a deterministic train/holdout split", "rollback_to": BASE_VERSION}
    validate_artifact(result)
    return result


def hero(inventory=None):
    result = refit("deploygrade/knowledge/outcome_records_clean.jsonl", "healthcare")
    if result["status"] != "PUBLISHED":
        return {"refit": result}
    if inventory is None:
        return {"refit": result}
    before = score_inventory(inventory, BASE_VERSION)
    after = score_inventory(inventory, PUBLISHED_VERSION)
    return {"refit": result, "before": before, "after": after}
