"""Immutable, checked-in rubric artifacts used for all production score math."""
import hashlib
import json
from pathlib import Path

from deploygrade.engine.contracts import validate_artifact


ROOT = Path(__file__).parents[1] / "rubrics"
MANIFEST = ROOT / "manifest.json"


def _canonical_hash(payload: dict) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _manifest() -> dict:
    manifest = json.loads(MANIFEST.read_text())
    validate_artifact(manifest)
    return manifest


def publication(version: str) -> dict:
    """Return immutable publication provenance for a rubric release.

    A version in the content-hash catalogue is not sufficient for a flywheel
    release: the release must also name the approved corpus and its parent
    rubric.  Missing provenance is deliberately treated as unpublished.
    """
    record = _manifest().get("publications", {}).get(version)
    if not isinstance(record, dict):
        raise ValueError("rubric has no approved publication provenance")
    required = {"vertical", "corpus_hash", "parent_rubric_version", "parent_rubric_hash", "approval_id"}
    if set(record) != required or not all(isinstance(record[name], str) and record[name] for name in required):
        raise ValueError("rubric publication provenance is incomplete")
    if record["parent_rubric_hash"] != content_hash(record["parent_rubric_version"]):
        raise ValueError("rubric publication parent hash does not match immutable manifest")
    return record


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
    expected_hash = _manifest()["rubric_hashes"].get(version)
    actual_hash = _canonical_hash(rubric)
    if expected_hash != actual_hash:
        raise ValueError("rubric content hash does not match immutable manifest")
    return rubric


def content_hash(version: str) -> str:
    """Return the canonical content hash retained in score and refit audit records."""
    rubric = load(version)
    return _canonical_hash(rubric)
