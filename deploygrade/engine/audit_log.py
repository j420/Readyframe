"""Append-only, hash-chained audit log for artifact handoffs."""
import hashlib
import json
from pathlib import Path
from deploygrade.engine.contracts import validate_artifact

SCHEMA = "../schemas/audit_log.schema.json"


def canonical_hash(value: dict) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def _entries(path: Path) -> list[dict]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text().splitlines() if line]


def append_handoff(path: str | Path, *, phase: str, inputs: dict, outputs: dict,
                   rubric_version: str, human_approvals: list[str], timestamp: str) -> dict:
    """Append exactly one chained, schema-validated record; never rewrite prior records."""
    destination = Path(path)
    prior = _entries(destination)
    previous_entry_hash = prior[-1]["entry_hash"] if prior else ""
    entry = {"$schema": SCHEMA, "schema_version": "1.0", "phase": phase,
             "inputs_hash": canonical_hash(inputs), "outputs_hash": canonical_hash(outputs),
             "rubric_version": rubric_version, "human_approvals": human_approvals,
             "timestamp": timestamp, "previous_entry_hash": previous_entry_hash}
    entry["entry_hash"] = canonical_hash(entry)
    validate_artifact(entry)
    destination.parent.mkdir(parents=True, exist_ok=True)
    with destination.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(entry, sort_keys=True, separators=(",", ":")) + "\n")
    return entry


def verify(path: str | Path) -> list[dict]:
    """Fail closed on modified, reordered, or broken audit records."""
    entries = _entries(Path(path))
    previous = ""
    for entry in entries:
        validate_artifact(entry)
        unsigned = {key: value for key, value in entry.items() if key != "entry_hash"}
        if entry["previous_entry_hash"] != previous or entry["entry_hash"] != canonical_hash(unsigned):
            raise ValueError("audit log integrity failure")
        previous = entry["entry_hash"]
    return entries
