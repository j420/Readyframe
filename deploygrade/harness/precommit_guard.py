#!/usr/bin/env python3
"""Fail-closed staged-change policy for DeployGrade."""
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def staged_paths() -> list[str]:
    result = subprocess.run(
        ["git", "diff", "--cached", "--name-only", "--diff-filter=ACMR"],
        cwd=ROOT, check=True, capture_output=True, text=True,
    )
    return [path for path in result.stdout.splitlines() if path]


def staged_text(path: str) -> str:
    return subprocess.run(
        ["git", "show", f":{path}"], cwd=ROOT, check=True,
        capture_output=True, text=True,
    ).stdout


def reject(message: str) -> None:
    print(f"DeployGrade pre-commit: REJECTED: {message}", file=sys.stderr)
    raise SystemExit(1)


def validate_artifact(path: str) -> None:
    if not path.endswith(".json") or path.startswith("deploygrade/schemas/"):
        return
    if not path.startswith("deploygrade/") or path.startswith("deploygrade/fixtures/discovery_repos/"):
        return
    try:
        payload = json.loads(staged_text(path))
    except json.JSONDecodeError as error:
        reject(f"artifact {path} is not valid JSON: {error.msg}")
    schema_uri = payload.get("$schema") if isinstance(payload, dict) else None
    if not isinstance(schema_uri, str) or not schema_uri:
        reject(f"artifact {path} has no $schema contract")
    schema_path = (ROOT / path).parent / schema_uri
    if not schema_path.resolve().is_file() or "deploygrade/schemas" not in str(schema_path.resolve()):
        reject(f"artifact {path} references missing or external schema: {schema_uri}")


def is_scoring_path(path: str) -> bool:
    if not path.startswith("deploygrade/engine/") or not path.endswith(".py"):
        return False
    return "score" in staged_text(path).lower()


def main() -> None:
    paths = staged_paths()
    for path in paths:
        validate_artifact(path)
    if any(is_scoring_path(path) for path in paths):
        has_determinism_test = any(
            path.startswith("deploygrade/tests/")
            and "determinism" in Path(path).stem.lower()
            for path in paths
        )
        if not has_determinism_test:
            reject("scoring path staged without a matching determinism test")
    print("DeployGrade pre-commit: policy checks passed")


if __name__ == "__main__":
    main()
