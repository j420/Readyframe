"""Approved, read-only local connector fixtures for deterministic Discovery tests.

The public input is an approval artifact only. Fixture filesystem paths remain private
implementation details in this module and cannot be supplied by callers.
"""
import hashlib
from pathlib import Path

from deploygrade.engine.contracts import validate_artifact

SCHEMA = "../schemas/approved_repository_connector.schema.json"
ROOT = Path(__file__).parents[2]
FIXTURE_ROOT = ROOT / "deploygrade/fixtures/discovery_repos"

# This allowlist models the control-plane approved connector registry for local tests.
# It intentionally contains identities/revisions, never caller-provided paths.
_LOCAL_FIXTURES = {
    "mature-v1": {"repository_id": "fixture-mature", "connector_id": "local-readonly-fixture", "revision": "fixture-mature-20260718", "directory": "mature"},
    "deceptive-v1": {"repository_id": "fixture-deceptive", "connector_id": "local-readonly-fixture", "revision": "fixture-deceptive-20260718", "directory": "deceptive"},
    "bare-v1": {"repository_id": "fixture-bare", "connector_id": "local-readonly-fixture", "revision": "fixture-bare-20260718", "directory": "bare"},
}


def _fixture_files(root: Path) -> list[Path]:
    return sorted(path for path in root.rglob("*") if path.is_file() and "__pycache__" not in path.parts and path.suffix != ".pyc")


def _manifest(fixture_id: str) -> dict:
    item = _LOCAL_FIXTURES[fixture_id]
    root = FIXTURE_ROOT / item["directory"]
    files = [{"path": path.relative_to(root).as_posix(), "sha256": hashlib.sha256(path.read_bytes()).hexdigest()} for path in _fixture_files(root)]
    # Empty repositories still require a signed manifest boundary; .gitkeep is tracked.
    return {"fixture_id": fixture_id, "files": files}


def approved_fixture(fixture_id: str, *, organization_id: str = "local-test-org", engagement_id: str = "local-test-engagement") -> dict:
    """Return a schema-valid local approval artifact for a known read-only fixture."""
    if fixture_id not in _LOCAL_FIXTURES:
        raise ValueError("unknown approved local connector fixture")
    item = _LOCAL_FIXTURES[fixture_id]
    artifact = {"$schema": SCHEMA, "schema_version": "1.0", "organization_id": organization_id,
                "engagement_id": engagement_id,
                "repository": {key: item[key] for key in ("repository_id", "connector_id", "revision")},
                "approval": {"approval_id": f"approval-{fixture_id}", "approved_by": "local-fixture-admin", "status": "APPROVED"},
                "access": {"mode": "READ_ONLY", "network_egress": "DENY_ALL"},
                "evidence_manifest": _manifest(fixture_id)}
    validate_artifact(artifact)
    return artifact


def resolve_approved_fixture(connector: dict) -> Path:
    """Validate approval + manifest, then resolve only a fixed local fixture directory."""
    validate_artifact(connector)
    if connector.get("$schema") != SCHEMA:
        raise ValueError("discovery requires an approved repository connector artifact")
    matches = [(fixture_id, item) for fixture_id, item in _LOCAL_FIXTURES.items()
               if {key: connector["repository"][key] for key in ("repository_id", "connector_id", "revision")} ==
               {key: item[key] for key in ("repository_id", "connector_id", "revision")}]
    if len(matches) != 1:
        raise ValueError("repository identity and revision are not approved for local discovery")
    fixture_id, item = matches[0]
    if connector["evidence_manifest"] != _manifest(fixture_id):
        raise ValueError("read-only evidence manifest does not match the approved repository revision")
    return FIXTURE_ROOT / item["directory"]
