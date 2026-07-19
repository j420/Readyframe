"""Reference worker runtime with explicit fail-closed execution semantics.

This module is deliberately *not* a sandbox implementation.  It consumes only a
validated worker dispatch and approved, read-only connector artifact.  Discovery
is allowed solely against the connector's pinned evidence manifest.  Pilot work is
always denied before an action can be attempted: a real isolated worker must
implement a non-bypassable tool policy before Pilot execution is enabled.
"""
from __future__ import annotations

import uuid

from deploygrade.engine.contracts import validate_artifact
from deploygrade.engine.discovery import CHECKS, discover_approved
from deploygrade.engine.worker_dispatch import status_event

SCHEMA = "../schemas/worker_runtime_result.schema.json"
_NAMESPACE = uuid.UUID("a8fd5c81-1ae8-4d84-b583-4266b0fb0bdb")


def _event_id(dispatch_hash: str, state: str, reason: str) -> str:
    """Return a reproducible event id; repeated safe reference runs are identical."""
    return str(uuid.uuid5(_NAMESPACE, f"{dispatch_hash}:{state}:{reason}"))


def _event(dispatch: dict, state: str, reason: str) -> dict:
    return status_event(
        event_id=_event_id(dispatch["dispatch_hash"], state, reason),
        dispatch=dispatch,
        state=state,
        reason=reason,
    )


def _validate_binding(dispatch: dict, connector: dict) -> None:
    validate_artifact(dispatch)
    validate_artifact(connector)
    if dispatch.get("$schema") != "../schemas/worker_dispatch.schema.json":
        raise ValueError("worker runtime requires a worker dispatch artifact")
    connector_schema = connector.get("$schema")
    if connector_schema == "../schemas/approved_repository_connector.schema.json":
        if dispatch["repository"] != connector["repository"]:
            raise ValueError("dispatch repository does not match approved connector evidence")
    elif connector_schema == "../schemas/github_repository_snapshot.schema.json":
        snapshot_repository = connector["repository"]
        dispatch_repository = dispatch["repository"]
        if (dispatch_repository["repository_id"] != snapshot_repository["repository_id"]
                or dispatch_repository["revision"] != snapshot_repository["revision"]
                or dispatch_repository["connector_id"] != "github"):
            raise ValueError("dispatch repository does not match approved GitHub snapshot evidence")
    else:
        raise ValueError("worker runtime requires an approved repository connector artifact")
    if connector["access"] != {"mode": "READ_ONLY", "network_egress": "DENY_ALL"}:
        raise ValueError("worker runtime requires read-only, no-egress connector evidence")
    if dispatch["sandbox"]["filesystem_mode"] != "READ_ONLY" or dispatch["sandbox"]["network_egress"] != "DENY_ALL":
        raise ValueError("worker runtime requires a read-only, no-egress dispatch")


def _github_snapshot_inventory(snapshot: dict, environment: str) -> dict:
    """Report an honest inventory from metadata-only GitHub evidence.

    The snapshot intentionally excludes repository contents to avoid persisting
    customer source in control-plane artifacts.  Therefore it cannot support a
    content-based positive finding.  Emit only explicit missing-evidence records
    and require an approved isolated content worker for further inspection.
    """
    repository = snapshot["repository"]
    source = f"github://{repository['owner']}/{repository['name']}@{repository['revision']}"
    inventory = {
        "$schema": "../schemas/deployment_inventory.schema.json",
        "schema_version": "2.0",
        "environment": environment,
        "agents": [{"id": "github-snapshot", "version": "metadata-only-v1"}],
        "collected_facts": [],
        "missing_evidence": [
            {"category": category, "sub_score": sub_score,
             "reason": "immutable GitHub snapshot contains metadata only; approved isolated content inspection is required",
             "evidence_quality": {"source": source, "freshness": "snapshot-metadata-only", "confidence": 0.8}}
            for category, sub_score in CHECKS
        ],
    }
    validate_artifact(inventory)
    return inventory


def _github_content_inventory(snapshot: dict, evidence: dict, environment: str) -> dict:
    """Convert validated redacted GitHub evidence into an honest inventory.

    The input contains blob identities and hashes, never source bytes.  A
    category is reported only when a deterministic inspection rule matched; all
    other score inputs remain explicit missing evidence.
    """
    validate_artifact(evidence)
    if evidence.get("$schema") != "../schemas/github_content_evidence.schema.json":
        raise ValueError("worker runtime requires GitHub content evidence")
    repository = snapshot["repository"]
    if (evidence["organization_id"] != snapshot["organization_id"]
            or evidence["engagement_id"] != snapshot["engagement_id"]
            or evidence["repository"] != repository
            or evidence["snapshot_manifest_hash"] != snapshot["evidence_manifest"]["content_hash"]):
        raise ValueError("GitHub content evidence does not match the approved snapshot")
    source = f"github://{repository['owner']}/{repository['name']}@{repository['revision']}"
    by_category = {}
    for finding in evidence["findings"]:
        by_category.setdefault(finding["category"], finding)
    facts, missing = [], []
    for category, sub_score in CHECKS:
        finding = by_category.get(category)
        if finding is None:
            missing.append({"category": category, "sub_score": sub_score,
                            "reason": "no validated match in approved ephemeral GitHub content inspection",
                            "evidence_quality": {"source": source, "freshness": "pinned-content-inspection", "confidence": 0.8}})
            continue
        uri = f"{source}/{finding['path']}#git-blob-{finding['git_blob_sha']}"
        facts.append({"category": category, "sub_score": sub_score,
                      "finding": f"validated redacted GitHub static evidence ({finding['rule_id']})",
                      "status": "present", "evidence_uris": [uri],
                      "evidence_quality": {"source": uri, "freshness": "pinned-content-inspection", "confidence": 0.85}})
    inventory = {"$schema": "../schemas/deployment_inventory.schema.json", "schema_version": "2.0",
                 "environment": environment, "agents": [{"id": "github-content-inspection", "version": evidence["policy"]["version"]}],
                 "collected_facts": facts, "missing_evidence": missing}
    validate_artifact(inventory)
    return inventory


def run(dispatch: dict, connector: dict, *, environment: str = "unknown", github_content_evidence: dict | None = None) -> dict:
    """Run approved Discovery or fail closed before every Pilot action.

    No subprocesses, network clients, mutable mounts, credentials, or Pilot tools
    are invoked here.  ``PILOT`` is a deliberate denied state, not a simulated
    sandbox execution or a claimed rollback.
    """
    _validate_binding(dispatch, connector)
    received = _event(dispatch, "RECEIVED", "validated approved read-only dispatch")
    if dispatch["execution_kind"] == "PILOT":
        denied = _event(
            dispatch,
            "FAILED",
            "pilot action denied before execution: reference runtime has no isolated tool enforcement",
        )
        result = {
            "$schema": SCHEMA,
            "schema_version": "1.0",
            "dispatch_hash": dispatch["dispatch_hash"],
            "outcome": "PILOT_DENIED",
            "events": [received, denied],
            "human_escalation_required": True,
        }
    elif dispatch["execution_kind"] == "DISCOVERY":
        running = _event(dispatch, "RUNNING", "starting approved read-only evidence scan")
        if connector["$schema"] == "../schemas/approved_repository_connector.schema.json":
            if github_content_evidence is not None:
                raise ValueError("content evidence is valid only for a GitHub snapshot")
            inventory = discover_approved(connector, environment)
        else:
            inventory = (_github_snapshot_inventory(connector, environment)
                         if github_content_evidence is None
                         else _github_content_inventory(connector, github_content_evidence, environment))
        completed = _event(dispatch, "COMPLETED", "approved read-only evidence scan completed")
        result = {
            "$schema": SCHEMA,
            "schema_version": "1.0",
            "dispatch_hash": dispatch["dispatch_hash"],
            "outcome": "DISCOVERY_COMPLETED",
            "events": [received, running, completed],
            "inventory": inventory,
            "human_escalation_required": False,
        }
    else:  # The dispatch schema makes this unreachable; keep the runtime fail closed.
        raise ValueError("worker runtime refuses unknown execution kind")
    validate_artifact(result)
    return result
