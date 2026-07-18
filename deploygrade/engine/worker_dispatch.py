"""Fail-closed contracts for dispatching approved work to an isolated worker."""
from deploygrade.engine.audit_log import canonical_hash
from deploygrade.engine.contracts import validate_artifact

DISPATCH_SCHEMA = "../schemas/worker_dispatch.schema.json"
EVENT_SCHEMA = "../schemas/sandbox_status_event.schema.json"


def _approved_repository(repository: dict, approved_repositories: list[dict]) -> None:
    """Accept repository identities only; local paths are deliberately not part of this API."""
    if not isinstance(repository, dict) or set(repository) != {"repository_id", "connector_id", "revision"}:
        raise ValueError("repository must be an approved repository identity, never a local path")
    if not isinstance(approved_repositories, list) or not all(isinstance(entry, dict) for entry in approved_repositories):
        raise ValueError("approved repositories must be a list of repository identities")
    matches = [entry for entry in approved_repositories if entry.get("repository_id") == repository["repository_id"]]
    if len(matches) != 1:
        raise ValueError("repository is not uniquely approved")
    approved = matches[0]
    if approved.get("connector_id") != repository["connector_id"]:
        raise ValueError("repository connector is not approved")
    revisions = approved.get("revisions", [])
    if not isinstance(revisions, list) or repository["revision"] not in revisions:
        raise ValueError("repository revision is not approved")


def create_dispatch(*, dispatch_id: str, execution_kind: str, repository: dict,
                    approved_repositories: list[dict], blueprint: dict, approval: dict,
                    credential_ref: str) -> dict:
    """Create a read-only, no-egress worker request after exact lineage checks."""
    validate_artifact(blueprint)
    if blueprint.get("$schema") != "../schemas/rollout_blueprint.schema.json":
        raise ValueError("worker dispatch requires a rollout blueprint artifact")
    _approved_repository(repository, approved_repositories)
    blueprint_hash = canonical_hash(blueprint)
    if not isinstance(approval, dict) or approval.get("status") != "APPROVED":
        raise ValueError("worker dispatch requires an approved human approval")
    if approval.get("blueprint_hash") != blueprint_hash:
        raise ValueError("approval does not authorize this exact blueprint")
    result = {"$schema": DISPATCH_SCHEMA, "schema_version": "1.0", "dispatch_id": dispatch_id,
              "execution_kind": execution_kind, "repository": repository, "blueprint_hash": blueprint_hash,
              "approval": {key: approval.get(key) for key in ("approval_id", "blueprint_hash", "status", "approver_id")},
              "sandbox": {"filesystem_mode": "READ_ONLY", "network_egress": "DENY_ALL", "credential_ref": credential_ref}}
    result["dispatch_hash"] = canonical_hash(result)
    validate_artifact(result)
    return result


def status_event(*, event_id: str, dispatch: dict, state: str, reason: str) -> dict:
    """Record sandbox state; unsafe/unknown terminal states always require escalation."""
    validate_artifact(dispatch)
    event = {"$schema": EVENT_SCHEMA, "schema_version": "1.0", "event_id": event_id,
             "dispatch_hash": dispatch["dispatch_hash"], "state": state, "reason": reason,
             "human_escalation_required": state in {"PAUSED", "FAILED"}}
    validate_artifact(event)
    return event
