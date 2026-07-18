"""Deterministic, six-dimension DeployGrade readiness scoring."""
import hashlib
import itertools
import json
import sys
from pathlib import Path
from deploygrade.engine.contracts import validate_artifact
from deploygrade.engine.rubrics import content_hash as rubric_hash
from deploygrade.engine.rubrics import load as load_rubric

ENGINE_VERSION = "3.0.0"
def _specifications(rubric_version: str):
    """Load production score parameters from an immutable rubric artifact."""
    try:
        rubric = load_rubric(rubric_version)
    except ValueError:
        # Historical fixtures remain replayable; all public API paths restrict to published versions.
        if rubric_version not in {"r1"}:
            raise
        rubric = load_rubric("2026.07.0")
    return tuple((item["id"], item["weight"], tuple(item["categories"]), tuple(item["control_clauses"]), item["cost"], item["counterfactual"]) for item in rubric["dimensions"])


# Compatibility export for existing deterministic tests; its source is the checked-in rubric.
DIMENSIONS = _specifications("2026.07.0")
BANDS = tuple((band["threshold"], band["name"]) for band in load_rubric("2026.07.0")["bands"])


def _canonical_hash(value: dict) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def band_for(score: int, bands=BANDS) -> str:
    for threshold, band in bands:
        if score < threshold:
            return band
    return "SCALE"


def _next_threshold(score: int, bands) -> int | None:
    return next((threshold for threshold, _ in bands if score < threshold), None)


def _counterfactual(sub_scores: list[dict], score: int, dimensions, bands) -> list[dict]:
    target = _next_threshold(score, bands)
    if target is None:
        return []
    actions = [(item, spec[4], spec[5]) for item, spec in zip(sub_scores, dimensions) if item["raw"] < 100]
    candidates = []
    for count in range(1, len(actions) + 1):
        for group in itertools.combinations(actions, count):
            projected = round(score + sum((100 - item["raw"]) * item["weight"] * 10 for item, _, _ in group))
            if projected >= target:
                candidates.append((sum(cost for _, cost, _ in group), len(group), tuple(item["name"] for item, _, _ in group), group, projected))
    if not candidates:
        return []
    _, _, _, chosen, projected = min(candidates, key=lambda candidate: candidate[:3])
    return [{"action": action, "sub_score_affected": item["name"], "projected_score_delta": round((100 - item["raw"]) * item["weight"] * 10), "cost": cost} for item, cost, action in chosen]


def score_inventory(inventory: dict, rubric_version: str = "2026.07.0") -> dict:
    """Pure scoring function of the schema-validated discovery inventory and rubric version."""
    validate_artifact(inventory)
    rubric = load_rubric(rubric_version) if rubric_version != "r1" else load_rubric("2026.07.0")
    dimensions = _specifications(rubric_version)
    bands = tuple((band["threshold"], band["name"]) for band in rubric["bands"])
    facts = {fact["category"]: fact for fact in inventory["collected_facts"]}
    missing = {gap["category"]: gap for gap in inventory["missing_evidence"]}
    sub_scores, drivers, evidence_confidences = [], [], []
    for name, weight, categories, clauses, _, _ in dimensions:
        relevant = [facts[category] for category in categories if category in facts]
        gaps = [missing[category] for category in categories if category in missing]
        if relevant:
            raw = sum(85 if fact["status"] == "present" else 15 for fact in relevant) / len(relevant)
            quality_fact = min(relevant, key=lambda fact: fact["evidence_quality"]["confidence"])
            quality = quality_fact["evidence_quality"]["confidence"]
            evidence_quality = quality_fact["evidence_quality"]
            evidence_uris = [uri for fact in relevant for uri in fact["evidence_uris"]]
            if any(fact["status"] == "present_low_quality" for fact in relevant):
                drivers.append({"kind": "coverage", "detail": f"{name} relies on present but low-quality evidence"})
        else:
            raw, quality, evidence_uris = 0, .2, ["evidence://missing/" + (categories[0] if categories else name)]
            evidence_quality = {"source": "score-engine", "freshness": "not_observed", "confidence": quality}
            drivers.append({"kind": "missing_evidence", "detail": f"{name} has no collected evidence"})
        for gap in gaps:
            drivers.append({"kind": "missing_evidence", "detail": f"{gap['category']} evidence is missing"})
        evidence_confidences.append(quality)
        sub_scores.append({"name": name, "raw": raw, "weight": weight, "controls": list(categories) or [name], "control_clauses": list(clauses), "evidence_uris": evidence_uris, "evidence_quality": evidence_quality})
    return _assemble(sub_scores, rubric_version, inventory, drivers, min(evidence_confidences), dimensions, bands)


def _assemble(sub_scores: list[dict], rubric_version: str, inputs: dict, drivers: list[dict], confidence: float, dimensions=None, bands=BANDS) -> dict:
    dimensions = dimensions or DIMENSIONS
    value = round(sum(item["raw"] * item["weight"] for item in sub_scores) * 10)
    audit = {"rubric_version": rubric_version, "inputs_hash": _canonical_hash(inputs), "rubric_hash": rubric_hash(rubric_version if rubric_version != "r1" else "2026.07.0"), "engine_version": ENGINE_VERSION, "generated_at": "1970-01-01T00:00:00Z"}
    audit["signature"] = _canonical_hash(audit)
    result = {"$schema": "../schemas/readiness_score.schema.json", "schema_version": "2.0",
              "score": {"value": value, "confidence": round(confidence, 2), "evidence_uris": sorted({uri for item in sub_scores for uri in item["evidence_uris"]}), "rubric_version": rubric_version},
              "band": band_for(value, bands), "sub_scores": sub_scores,
              "confidence": {"interval_low": round(value * confidence), "interval_high": min(1000, round(value + (1 - confidence) * 1000)), "method": "evidence-quality-propagation", "drivers": drivers or [{"kind": "coverage", "detail": "all dimensions have collected evidence"}]},
              "counterfactual": _counterfactual(sub_scores, value, dimensions, bands), "audit": audit}
    validate_artifact(result)
    return result


def score_readiness(payload: dict) -> dict:
    """Compatibility entry point: map direct controls into a deterministic inventory."""
    validate_artifact(payload)
    if payload.get("discovery_inventory") is not None:
        return score_inventory(payload["discovery_inventory"], payload["rubric_version"])
    facts = [{"category": {"access_control": "iam", "rollback_plan": "rollback", "observability": "cloud"}.get(name, name), "sub_score": name, "finding": "direct control input", "status": "present", "evidence_uris": [f"control://{name}"], "evidence_quality": {"source": "direct-input", "freshness": "declared", "confidence": value}} for name, value in payload["controls"].items()]
    inventory = {"$schema": "../schemas/deployment_inventory.schema.json", "schema_version": "2.0", "environment": "direct-input", "agents": [{"id": "direct-input", "version": "1"}], "collected_facts": facts, "missing_evidence": []}
    return score_inventory(inventory, payload["rubric_version"])


if __name__ == "__main__":
    print(json.dumps(score_readiness(json.loads(Path(sys.argv[1]).read_text())), sort_keys=True))
