"""Immutable, checked-in rubric artifacts used for all production score math."""
import json
import hashlib
from pathlib import Path

from deploygrade.engine.contracts import validate_artifact


ROOT = Path(__file__).parents[1] / "rubrics"


def load(version: str) -> dict:
    path = ROOT / f"{version}.json"
    if not path.is_file():
        raise ValueError(f"unpublished rubric version: {version}")
    rubric = json.loads(path.read_text())
    validate_artifact(rubric)
    if rubric["rubric_version"] != version:
        raise ValueError("rubric filename and rubric_version disagree")
    if round(sum(dimension["weight"] for dimension in rubric["dimensions"]), 6) != 1:
        raise ValueError("rubric weights must sum to one")
    required_dimension = {"id", "weight", "categories", "control_clauses", "cost", "counterfactual"}
    if not rubric["dimensions"] or any(set(dimension) != required_dimension for dimension in rubric["dimensions"]):
        raise ValueError("rubric dimensions must carry the complete deterministic specification")
    bands = rubric.get("bands", [])
    if not bands or any(set(band) != {"threshold", "name"} for band in bands):
        raise ValueError("rubric bands must carry threshold and name")
    if [band["threshold"] for band in bands] != sorted(band["threshold"] for band in bands):
        raise ValueError("rubric bands must be strictly ordered")
    return rubric


def content_hash(version: str) -> str:
    """Return the canonical content hash carried by every score audit."""
    rubric = load(version)
    return hashlib.sha256(json.dumps(rubric, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
