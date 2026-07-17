"""Stop: validate JSON contract and semantic rules before a handoff advances."""
from deploygrade.engine.contracts import validate_artifact


def validate_before_advance(artifact: dict) -> None:
    validate_artifact(artifact)
