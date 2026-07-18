"""Deterministic Build Week hero path: Discovery → Score → Blueprint → Flywheel."""
import json
from pathlib import Path

from deploygrade.engine.blueprint import compile_blueprint
from deploygrade.engine.contracts import validate_artifact
from deploygrade.engine.discovery import discover_approved
from deploygrade.engine.repository_connector import approved_fixture
from deploygrade.engine.flywheel import hero
from deploygrade.engine.score import score_inventory


ROOT = Path(__file__).parents[2]


def run(repo_profile: str, deployment_id: str = "meridian-bank") -> dict:
    """Run only checked-in, read-only demo repositories; never accept arbitrary server paths."""
    profiles = {"mature": "mature-v1", "deceptive": "deceptive-v1"}
    if repo_profile not in profiles:
        raise ValueError("repo_profile must be mature or deceptive")
    inventory = discover_approved(approved_fixture(profiles[repo_profile]), environment="sandbox")
    score = score_inventory(inventory, "2026.07.0")
    policy = json.loads((ROOT / "deploygrade/fixtures/policy_pack.json").read_text())
    blueprint = compile_blueprint(score, policy, deployment_id)
    result = {
        "$schema": "../schemas/demo_run.schema.json",
        "schema_version": "1.0",
        "inventory": inventory,
        "readiness_score": score,
        "blueprint": blueprint,
        "flywheel": hero(inventory),
    }
    validate_artifact(result)
    return result
