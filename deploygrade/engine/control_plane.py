"""Durable, fail-closed SQLite control-plane lineage store.

This is deliberately a repository-contained implementation for local/control-plane
deployments.  It does not substitute for Supabase authentication, but makes the
tenant, artifact, approval, job, and callback invariants executable and testable.
"""
import hashlib
import json
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path

from deploygrade.engine.contracts import validate_artifact


def canonical_hash(payload: dict) -> str:
    """Return the stable content address used for immutable artifact storage."""
    return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def _validate_callback_identity(event: dict) -> None:
    """Require canonical callback identity in every durable ingestion path."""
    event_id = event.get("event_id")
    try:
        parsed_id = uuid.UUID(event_id)
    except (ValueError, AttributeError, TypeError) as error:
        raise ValueError("callback event_id must be a canonical UUID string") from error
    if str(parsed_id) != event_id.lower():
        raise ValueError("callback event_id must be a canonical UUID string")
    occurred_at = event.get("occurred_at")
    if not isinstance(occurred_at, str) or not occurred_at.endswith("Z"):
        raise ValueError("callback occurred_at must be an RFC3339 UTC timestamp")
    try:
        parsed_time = datetime.fromisoformat(occurred_at[:-1] + "+00:00")
    except ValueError as error:
        raise ValueError("callback occurred_at must be an RFC3339 UTC timestamp") from error
    if parsed_time.tzinfo != timezone.utc:
        raise ValueError("callback occurred_at must be an RFC3339 UTC timestamp")


class ControlPlaneStore:
    """Tenant-scoped append-only artifact and Pilot lineage store.

    Every public mutator takes an organization id and rechecks ownership in SQL;
    callers cannot create cross-tenant references by supplying another tenant's
    hash or job id.
    """
    def __init__(self, database: str | Path = ":memory:"):
        self.connection = sqlite3.connect(str(database))
        self.connection.row_factory = sqlite3.Row
        self.connection.execute("PRAGMA foreign_keys = ON")
        self.connection.executescript("""
            CREATE TABLE IF NOT EXISTS organizations (id TEXT PRIMARY KEY);
            CREATE TABLE IF NOT EXISTS engagements (
              id TEXT PRIMARY KEY, organization_id TEXT NOT NULL REFERENCES organizations(id), vertical TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS artifacts (
              hash TEXT PRIMARY KEY, organization_id TEXT NOT NULL REFERENCES organizations(id),
              engagement_id TEXT NOT NULL REFERENCES engagements(id), schema_uri TEXT NOT NULL, payload TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS approvals (
              id TEXT PRIMARY KEY, organization_id TEXT NOT NULL REFERENCES organizations(id),
              engagement_id TEXT NOT NULL REFERENCES engagements(id), artifact_hash TEXT NOT NULL REFERENCES artifacts(hash),
              decision TEXT NOT NULL CHECK (decision IN ('APPROVED','REJECTED')), approved_by TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS pilot_jobs (
              id TEXT PRIMARY KEY, organization_id TEXT NOT NULL REFERENCES organizations(id),
              engagement_id TEXT NOT NULL REFERENCES engagements(id), blueprint_hash TEXT NOT NULL REFERENCES artifacts(hash),
              approval_id TEXT NOT NULL REFERENCES approvals(id), sandbox_repository TEXT NOT NULL,
              status TEXT NOT NULL CHECK (status IN ('QUEUED','RUNNING','PAUSED','REVERTED','COMPLETE','FAILED')));
            CREATE TABLE IF NOT EXISTS pilot_events (
              event_id TEXT PRIMARY KEY, organization_id TEXT NOT NULL REFERENCES organizations(id),
              pilot_job_id TEXT NOT NULL REFERENCES pilot_jobs(id), blueprint_hash TEXT NOT NULL,
              event_type TEXT NOT NULL, payload TEXT NOT NULL);
        """)
        self.connection.commit()

    def close(self) -> None:
        self.connection.close()

    def create_organization(self, organization_id: str) -> None:
        self.connection.execute("INSERT INTO organizations(id) VALUES (?)", (organization_id,))
        self.connection.commit()

    def create_engagement(self, organization_id: str, engagement_id: str, vertical: str) -> None:
        self._organization(organization_id)
        self.connection.execute("INSERT INTO engagements(id, organization_id, vertical) VALUES (?,?,?)", (engagement_id, organization_id, vertical))
        self.connection.commit()

    def store_artifact(self, organization_id: str, engagement_id: str, payload: dict) -> str:
        """Validate then content-address an immutable artifact; conflicts fail closed."""
        validate_artifact(payload)
        self._engagement(organization_id, engagement_id)
        digest = canonical_hash(payload)
        existing = self.connection.execute("SELECT organization_id, engagement_id, payload FROM artifacts WHERE hash=?", (digest,)).fetchone()
        serialized = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        if existing:
            if (existing["organization_id"], existing["engagement_id"], existing["payload"]) != (organization_id, engagement_id, serialized):
                raise ValueError("artifact hash is already bound to a different tenant or engagement")
            return digest
        self.connection.execute("INSERT INTO artifacts(hash,organization_id,engagement_id,schema_uri,payload) VALUES (?,?,?,?,?)", (digest, organization_id, engagement_id, payload["$schema"], serialized))
        self.connection.commit()
        return digest

    def approve(self, organization_id: str, engagement_id: str, artifact_hash: str, approved_by: str, decision: str = "APPROVED") -> str:
        if decision not in {"APPROVED", "REJECTED"}:
            raise ValueError("unknown approval decision")
        self._artifact(organization_id, engagement_id, artifact_hash)
        approval_id = str(uuid.uuid4())
        self.connection.execute("INSERT INTO approvals VALUES (?,?,?,?,?,?)", (approval_id, organization_id, engagement_id, artifact_hash, decision, approved_by))
        self.connection.commit()
        return approval_id

    def create_pilot_job(self, organization_id: str, engagement_id: str, blueprint_hash: str, approval_id: str, sandbox_repository: str) -> str:
        blueprint = self._artifact(organization_id, engagement_id, blueprint_hash)
        if blueprint["schema_uri"] != "../schemas/rollout_blueprint.schema.json":
            raise ValueError("Pilot job requires a rollout blueprint artifact")
        approval = self.connection.execute("SELECT * FROM approvals WHERE id=? AND organization_id=? AND engagement_id=?", (approval_id, organization_id, engagement_id)).fetchone()
        if not approval or approval["artifact_hash"] != blueprint_hash or approval["decision"] != "APPROVED":
            raise ValueError("Pilot job requires an approved approval for the exact blueprint")
        if not sandbox_repository:
            raise ValueError("Pilot job requires an approved sandbox repository")
        job_id = str(uuid.uuid4())
        self.connection.execute("INSERT INTO pilot_jobs VALUES (?,?,?,?,?,?,?)", (job_id, organization_id, engagement_id, blueprint_hash, approval_id, sandbox_repository, "QUEUED"))
        self.connection.commit()
        return job_id

    def record_callback(self, organization_id: str, event: dict) -> None:
        """Persist one validated callback only when it matches an approved job."""
        validate_artifact(event)
        _validate_callback_identity(event)
        job = self.connection.execute("SELECT * FROM pilot_jobs WHERE id=? AND organization_id=?", (event["pilot_job_id"], organization_id)).fetchone()
        if not job or job["blueprint_hash"] != event["blueprint_hash"]:
            raise ValueError("callback job and blueprint lineage is unknown or mismatched")
        if job["status"] in {"REVERTED", "COMPLETE", "FAILED"}:
            raise ValueError("callback targets a terminal Pilot job")
        # A breach must be fail-closed.  In particular, an untrusted callback
        # must not be able to silently turn a paused job back into RUNNING.
        # The only permitted follow-up is evidence that the compensating revert
        # completed; a human-approved, separately audited workflow is required
        # before any new Pilot job can be dispatched.
        allowed_events = {
            # A pre-start breach/rollback signal is safe to record: it can only
            # move the job into PAUSED, never authorize execution.
            "QUEUED": {"PILOT_STARTED", "THRESHOLD_BREACHED", "ROLLBACK_FIRED", "PILOT_PAUSED"},
            "RUNNING": {"ACTION_DENIED", "METRIC_RECORDED", "THRESHOLD_BREACHED", "ROLLBACK_FIRED", "COMPENSATING_REVERTED", "PILOT_PAUSED"},
            "PAUSED": {"COMPENSATING_REVERTED"},
        }
        if event["event_type"] not in allowed_events[job["status"]]:
            raise ValueError(f"callback event is not allowed while Pilot job is {job['status']}")
        try:
            self.connection.execute("INSERT INTO pilot_events VALUES (?,?,?,?,?,?)", (event["event_id"], organization_id, job["id"], event["blueprint_hash"], event["event_type"], json.dumps(event, sort_keys=True, separators=(",", ":"))))
        except sqlite3.IntegrityError as error:
            raise ValueError("duplicate callback event") from error
        status = {"PILOT_STARTED": "RUNNING", "THRESHOLD_BREACHED": "PAUSED", "ROLLBACK_FIRED": "PAUSED", "PILOT_PAUSED": "PAUSED", "COMPENSATING_REVERTED": "REVERTED"}.get(event["event_type"])
        if status:
            self.connection.execute("UPDATE pilot_jobs SET status=? WHERE id=?", (status, job["id"]))
        self.connection.commit()

    def job_status(self, organization_id: str, job_id: str) -> str:
        row = self.connection.execute("SELECT status FROM pilot_jobs WHERE id=? AND organization_id=?", (job_id, organization_id)).fetchone()
        if not row:
            raise ValueError("unknown tenant-scoped Pilot job")
        return row["status"]

    def _organization(self, organization_id: str) -> None:
        if not self.connection.execute("SELECT 1 FROM organizations WHERE id=?", (organization_id,)).fetchone():
            raise ValueError("unknown organization")

    def _engagement(self, organization_id: str, engagement_id: str) -> None:
        if not self.connection.execute("SELECT 1 FROM engagements WHERE id=? AND organization_id=?", (engagement_id, organization_id)).fetchone():
            raise ValueError("unknown tenant-scoped engagement")

    def _artifact(self, organization_id: str, engagement_id: str, artifact_hash: str) -> sqlite3.Row:
        row = self.connection.execute("SELECT * FROM artifacts WHERE hash=? AND organization_id=? AND engagement_id=?", (artifact_hash, organization_id, engagement_id)).fetchone()
        if not row:
            raise ValueError("unknown tenant-scoped artifact")
        return row
