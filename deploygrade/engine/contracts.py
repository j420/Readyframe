"""Versioned JSON-contract and semantic validation for DeployGrade artifacts."""
import hashlib
import json
import math
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path

SCHEMA_ROOT = Path(__file__).parents[1] / "schemas"


def _schema_path(schema_uri: str) -> Path:
    schema_name = Path(schema_uri).name
    if not schema_uri.endswith(f"/schemas/{schema_name}"):
        raise ValueError(f"schema URI must reference a checked-in schemas directory: {schema_uri}")
    path = (SCHEMA_ROOT / schema_name).resolve()
    if not path.is_file() or path.parent != SCHEMA_ROOT.resolve():
        raise ValueError(f"unknown or unavailable schema: {schema_uri}")
    return path


def _resolve_ref(rule: dict, root_schema: dict) -> dict:
    """Resolve local JSON Schema references; external references fail closed."""
    reference = rule.get("$ref")
    if not reference:
        return rule
    if not reference.startswith("#/"):
        raise ValueError(f"unsupported external schema reference: {reference}")
    resolved = root_schema
    for part in reference[2:].split("/"):
        if not isinstance(resolved, dict) or part not in resolved:
            raise ValueError(f"unresolvable schema reference: {reference}")
        resolved = resolved[part]
    if not isinstance(resolved, dict):
        raise ValueError(f"schema reference must resolve to an object: {reference}")
    return resolved


def _validate(value, rule: dict, path: str, root_schema: dict | None = None) -> None:
    root_schema = root_schema or rule
    rule = _resolve_ref(rule, root_schema)
    expected = rule.get("type")
    type_ok = {
        "object": lambda: isinstance(value, dict),
        "array": lambda: isinstance(value, list),
        "string": lambda: isinstance(value, str),
        "number": lambda: isinstance(value, (int, float)) and not isinstance(value, bool),
        "integer": lambda: isinstance(value, int) and not isinstance(value, bool),
        "boolean": lambda: isinstance(value, bool),
    }
    if expected and not type_ok[expected]():
        raise ValueError(f"{path} must be a {expected}")
    if "enum" in rule and value not in rule["enum"]:
        raise ValueError(f"{path} must be one of {rule['enum']}")
    if "const" in rule and value != rule["const"]:
        raise ValueError(f"{path} must equal {rule['const']}")
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        if not math.isfinite(value):
            raise ValueError(f"{path} must be a finite number")
        if value < rule.get("minimum", value) or value > rule.get("maximum", value):
            raise ValueError(f"{path} is outside its allowed range")
    if isinstance(value, str):
        if len(value) < rule.get("minLength", 0):
            raise ValueError(f"{path} must not be empty")
        if "maxLength" in rule and len(value) > rule["maxLength"]:
            raise ValueError(f"{path} exceeds its allowed length")
        if "pattern" in rule and re.search(rule["pattern"], value) is None:
            raise ValueError(f"{path} does not match its required pattern")
    if isinstance(value, list):
        if len(value) < rule.get("minItems", 0):
            raise ValueError(f"{path} needs at least {rule['minItems']} items")
        for index, item in enumerate(value):
            _validate(item, rule.get("items", {}), f"{path}[{index}]", root_schema)
    if isinstance(value, dict):
        if len(value) < rule.get("minProperties", 0):
            raise ValueError(f"{path} needs at least {rule['minProperties']} properties")
        if "maxProperties" in rule and len(value) > rule["maxProperties"]:
            raise ValueError(f"{path} has too many properties")
        missing = set(rule.get("required", [])) - set(value)
        if missing:
            raise ValueError(f"{path} missing required fields: {sorted(missing)}")
        properties = rule.get("properties", {})
        if rule.get("additionalProperties") is False:
            extras = set(value) - set(properties)
            if extras:
                raise ValueError(f"{path} has unexpected fields: {sorted(extras)}")
        elif isinstance(rule.get("additionalProperties"), dict):
            for key in set(value) - set(properties):
                _validate(value[key], rule["additionalProperties"], f"{path}.{key}", root_schema)
        for key, child_rule in properties.items():
            if key in value:
                _validate(value[key], child_rule, f"{path}.{key}", root_schema)


def _validate_readiness_semantics(payload: dict) -> None:
    score = payload["score"]["value"]
    sub_scores = payload["sub_scores"]
    weighted_score = round(sum(item["raw"] * item["weight"] for item in sub_scores) * 10)
    if abs(score - weighted_score) > 1:
        raise ValueError(f"semantic mismatch: score {score} does not match weighted sub-scores {weighted_score}")
    band = "BLOCKED" if score < 400 else "CONDITIONAL" if score < 600 else "READY" if score < 800 else "SCALE"
    if payload["band"] != band:
        raise ValueError(f"semantic mismatch: score {score} requires band {band}")
    if not (payload["confidence"]["interval_low"] <= score <= payload["confidence"]["interval_high"]):
        raise ValueError("semantic mismatch: confidence interval must contain score")
    if round(sum(item["weight"] for item in sub_scores), 6) != 1:
        raise ValueError("semantic mismatch: sub-score weights must sum to 1")
    unsigned_audit = {key: value for key, value in payload["audit"].items() if key != "signature"}
    expected_signature = hashlib.sha256(json.dumps(unsigned_audit, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    if payload["audit"]["signature"] != expected_signature:
        raise ValueError("semantic mismatch: audit signature does not match audit fields")



def _validate_blueprint_semantics(payload: dict) -> None:
    limits = {"BLOCKED": "OBSERVE", "CONDITIONAL": "SUPERVISED", "READY": "BOUNDED", "SCALE": "AUTONOMOUS"}
    levels = ["OBSERVE", "SUPERVISED", "BOUNDED", "AUTONOMOUS"]
    # The source score band is reconstructed from the signed source audit only at compile time;
    # a blueprint must nevertheless retain at least one deny/pause/human rule.
    if not payload["rollback_rules"] or not payload["approval_gates"]:
        raise ValueError("semantic mismatch: rollout blueprint must have enforceable safety gates")
    if payload["autonomy_level"] not in levels:
        raise ValueError("semantic mismatch: invalid autonomy level")
    if levels.index(payload["autonomy_level"]) > levels.index(limits[payload["source_band"]]):
        raise ValueError("semantic mismatch: autonomy exceeds source readiness band")


def _validate_demo_run_semantics(payload: dict) -> None:
    """Ensure the composite demo boundary cannot hide invalid phase artifacts."""
    validate_artifact(payload["inventory"])
    validate_artifact(payload["readiness_score"])
    validate_artifact(payload["blueprint"])
    score_audit = payload["readiness_score"]["audit"]
    expected_source_audit = {key: score_audit[key] for key in ("inputs_hash", "rubric_version", "engine_version", "signature")}
    if payload["blueprint"]["source_readiness_audit"] != expected_source_audit:
        raise ValueError("semantic mismatch: blueprint does not retain the demo readiness audit")
    flywheel = payload["flywheel"]
    if not isinstance(flywheel, dict) or not isinstance(flywheel.get("refit"), dict):
        raise ValueError("semantic mismatch: demo flywheel result is missing")
    validate_artifact(flywheel["refit"])
    for name in ("before", "after"):
        if name in flywheel:
            validate_artifact(flywheel[name])
            if flywheel[name]["audit"]["inputs_hash"] != score_audit["inputs_hash"]:
                raise ValueError("semantic mismatch: demo re-score changed the discovered input")



def _validate_pilot_callback_semantics(payload: dict) -> None:
    """Make every callback consumer enforce canonical event identity, not only HTTP."""
    try:
        event_id = uuid.UUID(payload["event_id"])
    except (ValueError, AttributeError) as error:
        raise ValueError("semantic mismatch: event_id must be a canonical UUID") from error
    if str(event_id) != payload["event_id"].lower():
        raise ValueError("semantic mismatch: event_id must be a canonical UUID")
    occurred_at = payload["occurred_at"]
    if not occurred_at.endswith("Z"):
        raise ValueError("semantic mismatch: occurred_at must be an RFC3339 UTC timestamp")
    try:
        parsed = datetime.fromisoformat(occurred_at[:-1] + "+00:00")
    except ValueError as error:
        raise ValueError("semantic mismatch: occurred_at must be an RFC3339 UTC timestamp") from error
    if parsed.tzinfo != timezone.utc:
        raise ValueError("semantic mismatch: occurred_at must be an RFC3339 UTC timestamp")


def _validate_rubric_refit_semantics(payload: dict) -> None:
    """Published refits need complete provenance; refusals must explain their stop."""
    published = {"rubric_version", "rubric_hash", "parent_rubric_version", "parent_rubric_hash",
                 "approval_id", "baseline_accuracy", "holdout_accuracy", "weights", "diff", "rollback_to"}
    if payload["status"] == "PUBLISHED":
        missing = published - set(payload)
        if missing:
            raise ValueError(f"semantic mismatch: published refit missing provenance: {sorted(missing)}")
        if payload["holdout_accuracy"] <= payload["baseline_accuracy"]:
            raise ValueError("semantic mismatch: published refit must improve holdout accuracy")
    elif "reason" not in payload:
        raise ValueError("semantic mismatch: refused refit must state its reason")


def _validate_approved_repository_connector_semantics(payload: dict) -> None:
    """Discovery connectors are read-only approvals, not caller-controlled paths."""
    repository = payload["repository"]
    forbidden = {"path", "root", "url", "clone_url", "filesystem_path"}
    if forbidden & set(repository):
        raise ValueError("semantic mismatch: repository connector must not expose a filesystem path")
    files = payload["evidence_manifest"]["files"]
    paths = [entry["path"] for entry in files]
    if len(paths) != len(set(paths)) or paths != sorted(paths):
        raise ValueError("semantic mismatch: evidence manifest paths must be unique and sorted")


def _validate_worker_dispatch_semantics(payload: dict) -> None:
    """Worker requests have immutable approval/blueprint lineage and no path escape hatch."""
    if payload["approval"]["blueprint_hash"] != payload["blueprint_hash"]:
        raise ValueError("semantic mismatch: approval does not match dispatch blueprint")
    unsigned = {key: value for key, value in payload.items() if key != "dispatch_hash"}
    if payload["dispatch_hash"] != hashlib.sha256(json.dumps(unsigned, sort_keys=True, separators=(",", ":")).encode()).hexdigest():
        raise ValueError("semantic mismatch: dispatch hash does not match dispatch fields")


def _validate_sandbox_status_event_semantics(payload: dict) -> None:
    unsafe = payload["state"] in {"PAUSED", "FAILED"}
    if payload["human_escalation_required"] != unsafe:
        raise ValueError("semantic mismatch: unsafe sandbox state must escalate to a human")


def validate_schema_shape(payload: dict) -> None:
    """Validate only the versioned JSON Schema contract, without domain semantics."""
    if not isinstance(payload, dict) or not isinstance(payload.get("$schema"), str):
        raise ValueError("artifact must be an object with a $schema")
    schema_uri = payload["$schema"]
    schema = json.loads(_schema_path(schema_uri).read_text())
    _validate(payload, schema, "artifact", schema)
    return schema_uri


def validate_artifact(payload: dict) -> None:
    """Validate schema shape and domain semantics; old readiness v1 remains supported."""
    schema_uri = validate_schema_shape(payload)
    if schema_uri.endswith("/readiness_score.schema.json"):
        _validate_readiness_semantics(payload)
    if schema_uri.endswith("/rollout_blueprint.schema.json"):
        _validate_blueprint_semantics(payload)
    if schema_uri.endswith("/demo_run.schema.json"):
        _validate_demo_run_semantics(payload)
    if schema_uri.endswith("/pilot_callback.schema.json"):
        _validate_pilot_callback_semantics(payload)
    if schema_uri.endswith("/rubric_refit.schema.json"):
        _validate_rubric_refit_semantics(payload)
    if schema_uri.endswith("/approved_repository_connector.schema.json"):
        _validate_approved_repository_connector_semantics(payload)
    if schema_uri.endswith("/worker_dispatch.schema.json"):
        _validate_worker_dispatch_semantics(payload)
    if schema_uri.endswith("/sandbox_status_event.schema.json"):
        _validate_sandbox_status_event_semantics(payload)
