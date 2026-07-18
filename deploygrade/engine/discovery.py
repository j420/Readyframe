"""Read-only, parallel evidence discovery for deployment inventories."""
import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from deploygrade.engine.contracts import validate_artifact

CHECKS = (
    ("rollback", "rollback_plan"), ("tests", "operational_assurance"),
    ("ci", "operational_assurance"), ("iac", "change_control"),
    ("cloud", "environment_isolation"), ("iam", "access_control"),
)


def _files(root: Path) -> list[Path]:
    return sorted(path for path in root.rglob("*") if path.is_file())


def _quality(path: Path, confidence: float) -> dict:
    return {"source": f"repo://{path.as_posix()}", "freshness": "unknown-static-scan", "confidence": confidence}


def _find(paths: list[Path], predicate) -> list[Path]:
    return [path for path in paths if predicate(path, path.read_text(errors="ignore"))]


def _scan(category: str, sub_score: str, root: Path, paths: list[Path]) -> tuple[dict | None, dict | None]:
    relative = lambda path: path.relative_to(root)
    if category == "rollback":
        candidates = _find(paths, lambda p, _: "rollback" in p.name.lower())
        valid = [p for p in candidates if "set -e" in p.read_text(errors="ignore") and ("undo" in p.read_text(errors="ignore") or "revert" in p.read_text(errors="ignore"))]
    elif category == "tests":
        candidates = _find(paths, lambda p, _: "test" in p.name.lower())
        valid = [p for p in candidates if "assert " in p.read_text(errors="ignore") and "assert True" not in p.read_text(errors="ignore")]
    elif category == "ci":
        candidates = _find(paths, lambda p, _: ".github/workflows" in p.as_posix() or p.name in {".gitlab-ci.yml", "Jenkinsfile"})
        valid = [p for p in candidates if "pytest" in p.read_text(errors="ignore") or "npm test" in p.read_text(errors="ignore")]
    elif category == "iac":
        candidates = _find(paths, lambda p, _: p.suffix in {".tf", ".bicep"} or "cloudformation" in p.name.lower())
        valid = [p for p in candidates if "resource " in p.read_text(errors="ignore")]
    elif category == "cloud":
        candidates = _find(paths, lambda p, _: "cloud" in p.as_posix().lower() or "k8s" in p.as_posix().lower())
        valid = [p for p in candidates if len(p.read_text(errors="ignore").strip()) > 20]
    else:  # iam
        candidates = _find(paths, lambda p, text: "iam" in p.as_posix().lower() or "policy" in p.name.lower())
        valid = [p for p in candidates if len(p.read_text(errors="ignore").strip()) > 10 and p.read_text(errors="ignore").strip() != "{}"]
    if not candidates:
        return None, {"category": category, "sub_score": sub_score, "reason": "no evidence found by read-only scan", "evidence_quality": {"source": "repo-scan", "freshness": "not_observed", "confidence": 0.8}}
    chosen = valid[0] if valid else candidates[0]
    quality = _quality(relative(chosen), 0.85 if valid else 0.15)
    return {"category": category, "sub_score": sub_score,
            "finding": "validated static evidence" if valid else "evidence exists but static validation is insufficient",
            "status": "present" if valid else "present_low_quality",
            "evidence_uris": [quality["source"]], "evidence_quality": quality}, None


def discover(root: str | Path, environment: str = "unknown") -> dict:
    """Run independent read-only scans concurrently and return a schema-valid inventory."""
    repo = Path(root).resolve()
    paths = _files(repo)
    with ThreadPoolExecutor(max_workers=len(CHECKS)) as pool:
        futures = [pool.submit(_scan, category, sub_score, repo, paths) for category, sub_score in CHECKS]
        results = [future.result() for future in futures]
    facts = [fact for fact, _ in results if fact]
    missing = [gap for _, gap in results if gap]
    inventory = {"$schema": "../schemas/deployment_inventory.schema.json", "schema_version": "2.0",
                 "environment": environment, "agents": [{"id": repo.name, "version": "discovery-inferred"}],
                 "collected_facts": facts, "missing_evidence": missing}
    validate_artifact(inventory)
    return inventory


def discover_approved(connector: dict, environment: str = "unknown") -> dict:
    """Discover only from a pre-approved read-only connector; no path input is accepted."""
    from deploygrade.engine.repository_connector import resolve_approved_fixture
    return discover(resolve_approved_fixture(connector), environment)


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("repo")
    parser.add_argument("--environment", default="unknown")
    args = parser.parse_args()
    print(json.dumps(discover(args.repo, args.environment), sort_keys=True))
