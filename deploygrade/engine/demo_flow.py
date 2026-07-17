"""Deterministic Build Week hero path: Discovery → Score → Blueprint → Flywheel."""
import json
from pathlib import Path

from deploygrade.engine.blueprint import compile_blueprint
from deploygrade.engine.discovery import discover
from deploygrade.engine.flywheel import hero
from deploygrade.engine.score import score_inventory


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
    return {"inventory": inventory, "readiness_score": score, "blueprint": blueprint, "flywheel": hero()}
