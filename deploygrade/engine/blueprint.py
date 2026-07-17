"""Deterministic rollout blueprint compiler; prose agents never select gates or autonomy."""
import json
from pathlib import Path
from deploygrade.engine.contracts import validate_artifact

AUTONOMY_BY_BAND = {"BLOCKED": "OBSERVE", "CONDITIONAL": "SUPERVISED", "READY": "BOUNDED", "SCALE": "AUTONOMOUS"}
LOW_SCORE = 40


def _because(item: dict) -> dict:
    return {"sub_score": item["name"], "control_clause": item["control_clauses"][0], "evidence_uris": item["evidence_uris"]}


def _policy(pack: dict) -> tuple[int, list[dict]]:
    validate_artifact(pack)
    budget = pack["defaults"]["max_goal_token_budget"]
    for override in pack["overrides"]:
        if override["field"] != "max_goal_token_budget" or override["value"] > budget:
            raise ValueError("policy overrides may only tighten the token budget")
        budget = override["value"]
    return int(budget), pack["overrides"]


def compile_blueprint(readiness_score: dict, policy_pack: dict, deployment_id: str, requested_autonomy: str | None = None) -> dict:
    """Clamp requested autonomy to the deterministic band policy and emit enforceable gates."""
    validate_artifact(readiness_score)
    budget, overrides = _policy(policy_pack)
    permitted = AUTONOMY_BY_BAND[readiness_score["band"]]
    levels = ["OBSERVE", "SUPERVISED", "BOUNDED", "AUTONOMOUS"]
    if requested_autonomy and levels.index(requested_autonomy) > levels.index(permitted):
        requested_autonomy = permitted  # fail closed: a customer cannot loosen a weak score.
    autonomy = requested_autonomy or permitted
    low = [item for item in readiness_score["sub_scores"] if item["raw"] < LOW_SCORE]
    rules, approvals = [], []
    for item in low:
        because = _because(item)
        rules.append({"when": f"{item['name']}.raw < {LOW_SCORE}", "effect": "DENY" if item["name"] == "rollback_recovery" else "REQUIRE_HUMAN", "because": because})
        approvals.append({"id": f"approve-{item['name']}", "required": True, "because": because})
    if not rules:
        anchor = readiness_score["sub_scores"][0]
        rules.append({"when": "policy.pre_execution_gate", "effect": "PAUSE", "because": _because(anchor)})
        approvals.append({"id": "approve-rollout", "required": readiness_score["band"] != "SCALE", "because": _because(anchor)})
    pilot_repos = sorted(policy_pack["defaults"]["pilot_repos"], key=lambda repo: ["LOW", "MEDIUM", "HIGH"].index(repo["blast_radius"]))
    anchor = low[0] if low else readiness_score["sub_scores"][0]
    result = {"$schema": "../schemas/rollout_blueprint.schema.json", "schema_version": "2.0", "deployment_id": deployment_id,
              "source_readiness_audit": {key: readiness_score["audit"][key] for key in ("inputs_hash", "rubric_version", "engine_version", "signature")},
              "source_band": readiness_score["band"], "autonomy_level": autonomy, "policy_pack": {"id": policy_pack["id"], "vertical": policy_pack["vertical"], "defaults": policy_pack["defaults"], "overrides": overrides},
              "rollback_rules": rules,
              "budget": {"goal_token_budget": {"value": budget, "confidence": readiness_score["score"]["confidence"], "evidence_uris": readiness_score["score"]["evidence_uris"], "rubric_version": readiness_score["score"]["rubric_version"]}},
              "approval_gates": approvals,
              "pilot_repos": [{**repo, "because": _because(anchor)} for repo in pilot_repos]}
    validate_artifact(result)
    return result


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(); parser.add_argument("readiness_score"); parser.add_argument("policy_pack"); parser.add_argument("deployment_id")
    args = parser.parse_args()
    print(json.dumps(compile_blueprint(json.loads(Path(args.readiness_score).read_text()), json.loads(Path(args.policy_pack).read_text()), args.deployment_id), sort_keys=True))
