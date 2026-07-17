"""Deterministic Build Week hero path: Discovery → Score → Blueprint → Flywheel."""
import json
from pathlib import Path

from deploygrade.engine.blueprint import compile_blueprint
from deploygrade.engine.discovery import discover
from deploygrade.engine.flywheel import hero
from deploygrade.engine.score import score_inventory
from deploygrade.engine.contracts import validate_artifact


ROOT = Path(__file__).parents[2]


def run(repo_profile: str, deployment_id: str = "meridian-bank") -> dict:
    """Run only checked-in, read-only demo repositories; never accept arbitrary server paths."""
    profiles = {"mature": ROOT / "deploygrade/fixtures/discovery_repos/mature", "deceptive": ROOT / "deploygrade/fixtures/discovery_repos/deceptive"}
    if repo_profile not in profiles:
        raise ValueError("repo_profile must be mature or deceptive")
    inventory = discover(profiles[repo_profile], environment="sandbox")
    score = score_inventory(inventory, "2026.07.0")
    policy = json.loads((ROOT / "deploygrade/fixtures/policy_pack.json").read_text())
    blueprint = compile_blueprint(score, policy, deployment_id)
    # A separate, anonymized seeded engagement demonstrates an actual rubric-version re-score.
    refit_target = discover(profiles["mature"], environment="sandbox")
    rollback = next(fact for fact in refit_target["collected_facts"] if fact["category"] == "rollback")
    rollback["status"] = "present_low_quality"
    rollback["evidence_quality"] = {**rollback["evidence_quality"], "confidence": .15}
    result = {"$schema": "../schemas/demo_run.schema.json", "schema_version": "1.0", "inventory": inventory, "readiness_score": score, "blueprint": blueprint, "flywheel": hero(refit_target)}
    validate_artifact(result)
    return result
