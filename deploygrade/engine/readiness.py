"""Readiness subagent boundary: deterministic numbers, model-optional prose only."""
from deploygrade.engine.score import score_inventory


def assess(inventory: dict, rubric_version: str = "2026.07.0") -> dict:
    return score_inventory(inventory, rubric_version)
