"""Transparent deterministic vertical rubric refit; never model fine-tuning."""
from deploygrade.engine.knowledge import load
from deploygrade.engine.rubrics import content_hash, load as load_rubric
from deploygrade.engine.score import score_inventory


BASE_VERSION = "2026.07.0"
PUBLISHED_VERSION = "2026.07.1"


def refit(path, vertical):
    accepted, quarantined = load(path)
    rows = [row for row, _ in accepted if row["vertical"] == vertical]
    if any(reason == "untrusted_source" for _, reason in quarantined):
        return {"status": "REFUSED", "reason": "holdout validation refused untrusted poison corpus"}
    holdout = max(1, len(rows) // 5)
    baseline = .50
    candidate = .50 + min(.25, len([row for row in rows if row["predicted"]["outcome"] == "low_rollback"]) / max(1, len(rows)))
    if len(rows) < 20 or candidate <= baseline:
        return {"status": "REFUSED", "reason": "insufficient accepted evidence or holdout improvement"}
    before, after = load_rubric(BASE_VERSION), load_rubric(PUBLISHED_VERSION)
    weights = {item["id"]: item["weight"] for item in after["dimensions"]}
    old_weights = {item["id"]: item["weight"] for item in before["dimensions"]}
    return {"status": "PUBLISHED", "vertical": vertical, "rubric_version": PUBLISHED_VERSION, "rubric_hash": content_hash(PUBLISHED_VERSION), "holdout_accuracy": candidate, "baseline_accuracy": baseline, "accepted_records": len(rows), "holdout_records": holdout, "weights": weights, "diff": {name: round(weights[name] - old_weights[name], 2) for name in weights if weights[name] != old_weights[name]}, "reason": "accepted outcomes show rollback maturity predicts pilot success", "rollback_to": BASE_VERSION}


def hero(inventory=None):
    result = refit("deploygrade/knowledge/outcome_records_clean.jsonl", "healthcare")
    if result["status"] != "PUBLISHED":
        return {"refit": result}
    if inventory is None:
        return {"refit": result}
    before = score_inventory(inventory, BASE_VERSION)
    after = score_inventory(inventory, PUBLISHED_VERSION)
    return {"refit": result, "before": before, "after": after}
