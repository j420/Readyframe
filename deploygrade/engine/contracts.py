"""Versioned JSON-contract and semantic validation for DeployGrade artifacts."""
import hashlib
import json
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


def _validate(value, rule: dict, path: str) -> None:
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
        if value < rule.get("minimum", value) or value > rule.get("maximum", value):
            raise ValueError(f"{path} is outside its allowed range")
    if isinstance(value, str) and not value and rule.get("minLength", 0) > 0:
        raise ValueError(f"{path} must not be empty")
    if isinstance(value, list):
        if len(value) < rule.get("minItems", 0):
            raise ValueError(f"{path} needs at least {rule['minItems']} items")
        for index, item in enumerate(value):
            _validate(item, rule.get("items", {}), f"{path}[{index}]")
    if isinstance(value, dict):
        missing = set(rule.get("required", [])) - set(value)
        if missing:
            raise ValueError(f"{path} missing required fields: {sorted(missing)}")
        properties = rule.get("properties", {})
        if rule.get("additionalProperties") is False:
            extras = set(value) - set(properties)
            if extras:
                raise ValueError(f"{path} has unexpected fields: {sorted(extras)}")
        for key, child_rule in properties.items():
            if key in value:
                _validate(value[key], child_rule, f"{path}.{key}")


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


def validate_schema_shape(payload: dict) -> None:
    """Validate only the versioned JSON Schema contract, without domain semantics."""
    if not isinstance(payload, dict) or not isinstance(payload.get("$schema"), str):
        raise ValueError("artifact must be an object with a $schema")
    schema_uri = payload["$schema"]
    schema = json.loads(_schema_path(schema_uri).read_text())
    _validate(payload, schema, "artifact")
    return schema_uri


def validate_artifact(payload: dict) -> None:
    """Validate schema shape and domain semantics; old readiness v1 remains supported."""
    schema_uri = validate_schema_shape(payload)
    if schema_uri.endswith("/readiness_score.schema.json"):
        _validate_readiness_semantics(payload)
    if schema_uri.endswith("/rollout_blueprint.schema.json"):
        _validate_blueprint_semantics(payload)
