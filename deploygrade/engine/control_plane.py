"""Durable, fail-closed SQLite control-plane lineage store.

This is deliberately a repository-contained implementation for local/control-plane
deployments.  It does not substitute for Supabase authentication, but makes the
tenant, artifact, approval, job, and callback invariants executable and testable.
"""
import hashlib
import json
import sqlite3
import uuid
import secrets
from contextlib import contextmanager
from threading import RLock
from typing import Callable, Protocol, TypeVar, runtime_checkable
from datetime import datetime, timezone
from pathlib import Path

from deploygrade.engine.contracts import validate_artifact


@runtime_checkable
class ControlPlaneStorage(Protocol):
    """Durable tenant-scoped persistence boundary used by HTTP and workers."""
    def create_organization(self, organization_id: str) -> None: ...
    def create_engagement(self, organization_id: str, engagement_id: str, vertical: str) -> None: ...
    def store_artifact(self, organization_id: str, engagement_id: str, payload: dict) -> str: ...
    def approve(self, organization_id: str, engagement_id: str, artifact_hash: str, approved_by: str, decision: str = "APPROVED") -> str: ...
    def create_pilot_job(self, organization_id: str, engagement_id: str, blueprint_hash: str, approval_id: str, sandbox_repository: str) -> str: ...
    def record_callback(self, organization_id: str, event: dict) -> None: ...
    def issue_callback_authorization(self, organization_id: str, pilot_job_id: str, *, ttl_seconds: int = 300) -> dict: ...
    def revoke_callback_authorization(self, organization_id: str, route_id: str) -> None: ...
    def callback_authorization(self, route_id: str) -> dict: ...
    def record_authorized_callback(self, route_id: str, event: dict) -> None: ...
    def job_status(self, organization_id: str, job_id: str) -> str: ...
    def readiness(self) -> dict: ...

def validate_sqlite_database_path(database: str | Path, *, allow_memory: bool = False) -> Path:
    """Validate a configured durable SQLite location before opening it.

    HTTP deployments must pass an absolute path on an existing, non-symlinked
    directory.  ``:memory:`` remains available only for isolated unit tests.
    """
    if str(database) == ":memory:":
        if allow_memory:
            return Path(":memory:")
        raise ValueError("durable control-plane storage cannot use :memory:")
    path = Path(database)
    if not path.is_absolute():
        raise ValueError("control-plane database path must be absolute")
    parent = path.parent
    if not parent.is_dir() or parent.is_symlink():
        raise ValueError("control-plane database directory must exist and not be a symlink")
    if path.exists() and (not path.is_file() or path.is_symlink()):
        raise ValueError("control-plane database must be a regular non-symlink file")
    return path


_T = TypeVar("_T")


def _atomic_mutation(method: Callable[..., _T]) -> Callable[..., _T]:
    """Run each externally visible write operation as one locked transaction."""
    def wrapped(self: "ControlPlaneStore", *args, **kwargs) -> _T:
        with self._transaction():
            return method(self, *args, **kwargs)
    return wrapped



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
        path = validate_sqlite_database_path(database, allow_memory=True)
        self.database_path = path
        self._lock = RLock()
        self.connection = sqlite3.connect(str(path), check_same_thread=False, isolation_level=None)
        self.connection.row_factory = sqlite3.Row
        self.connection.execute("PRAGMA foreign_keys = ON")
        self.connection.execute("PRAGMA journal_mode = WAL")
        self.connection.execute("PRAGMA synchronous = FULL")
        self.connection.execute("PRAGMA busy_timeout = 5000")
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
            CREATE TABLE IF NOT EXISTS callback_authorizations (
              route_id TEXT PRIMARY KEY, organization_id TEXT NOT NULL REFERENCES organizations(id),
              pilot_job_id TEXT NOT NULL REFERENCES pilot_jobs(id), blueprint_hash TEXT NOT NULL,
              signing_secret TEXT NOT NULL, expires_at TEXT NOT NULL, revoked_at TEXT);
        """)

    @contextmanager
    def _transaction(self):
        """Serialize write operations and guarantee rollback on every failure."""
        with self._lock:
            self.connection.execute("BEGIN IMMEDIATE")
            try:
                yield
            except BaseException:
                self.connection.rollback()
                raise
            else:
                self.connection.commit()

    def readiness(self) -> dict:
        """Return operational readiness without exposing storage internals."""
        try:
            with self._lock:
                self.connection.execute("SELECT 1").fetchone()
        except sqlite3.Error as error:
            raise ValueError("control-plane storage is unavailable") from error
        return {"backend": "sqlite", "durable": str(self.database_path) != ":memory:", "ready": True}

    def close(self) -> None:
        self.connection.close()

    @_atomic_mutation
    def create_organization(self, organization_id: str) -> None:
        self.connection.execute("INSERT INTO organizations(id) VALUES (?)", (organization_id,))

    @_atomic_mutation
    def create_engagement(self, organization_id: str, engagement_id: str, vertical: str) -> None:
        self._organization(organization_id)
        self.connection.execute("INSERT INTO engagements(id, organization_id, vertical) VALUES (?,?,?)", (engagement_id, organization_id, vertical))

    @_atomic_mutation
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
        return digest

    @_atomic_mutation
    def approve(self, organization_id: str, engagement_id: str, artifact_hash: str, approved_by: str, decision: str = "APPROVED") -> str:
        if decision not in {"APPROVED", "REJECTED"}:
            raise ValueError("unknown approval decision")
        self._artifact(organization_id, engagement_id, artifact_hash)
        approval_id = str(uuid.uuid4())
        self.connection.execute("INSERT INTO approvals VALUES (?,?,?,?,?,?)", (approval_id, organization_id, engagement_id, artifact_hash, decision, approved_by))
        return approval_id

    @_atomic_mutation
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
        return job_id

    def _record_callback_unlocked(self, organization_id: str, event: dict) -> None:
        """Persist one validated callback while an enclosing transaction is held."""
        validate_artifact(event)
        _validate_callback_identity(event)
        if self.connection.execute("SELECT 1 FROM pilot_events WHERE event_id=?", (event["event_id"],)).fetchone():
            raise ValueError("duplicate callback event")
        job = self.connection.execute("SELECT * FROM pilot_jobs WHERE id=? AND organization_id=?", (event["pilot_job_id"], organization_id)).fetchone()
        if not job or job["blueprint_hash"] != event["blueprint_hash"]:
            raise ValueError("callback job and blueprint lineage is unknown or mismatched")
        if job["status"] in {"REVERTED", "COMPLETE", "FAILED"}:
            raise ValueError("callback targets a terminal Pilot job")
        allowed_events = {
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

    @_atomic_mutation
    def record_callback(self, organization_id: str, event: dict) -> None:
        """Legacy internal ingestion path; HTTP ingress must use route authorization."""
        self._record_callback_unlocked(organization_id, event)

    @_atomic_mutation
    def issue_callback_authorization(self, organization_id: str, pilot_job_id: str, *, ttl_seconds: int = 300) -> dict:
        """Issue one short-lived callback credential for an exact non-terminal job.

        The raw signing secret is returned exactly once to the trusted dispatcher;
        callers must place it in a worker secret channel, never an artifact.
        """
        if not isinstance(ttl_seconds, int) or isinstance(ttl_seconds, bool) or not 30 <= ttl_seconds <= 3600:
            raise ValueError("callback authorization ttl must be between 30 and 3600 seconds")
        job = self.connection.execute("SELECT * FROM pilot_jobs WHERE id=? AND organization_id=?", (pilot_job_id, organization_id)).fetchone()
        if not job or job["status"] not in {"QUEUED", "RUNNING", "PAUSED"}:
            raise ValueError("callback authorization requires a non-terminal tenant-scoped Pilot job")
        now = datetime.now(timezone.utc)
        expires_at = now.timestamp() + ttl_seconds
        route_id = uuid.uuid4().hex
        secret = secrets.token_urlsafe(32)
        self.connection.execute("INSERT INTO callback_authorizations VALUES (?,?,?,?,?,?,NULL)", (route_id, organization_id, pilot_job_id, job["blueprint_hash"], secret, datetime.fromtimestamp(expires_at, timezone.utc).isoformat().replace("+00:00", "Z")))
        return {"route_id": route_id, "organization_id": organization_id, "pilot_job_id": pilot_job_id, "blueprint_hash": job["blueprint_hash"], "signing_secret": secret, "expires_at": datetime.fromtimestamp(expires_at, timezone.utc).isoformat().replace("+00:00", "Z")}

    @_atomic_mutation
    def revoke_callback_authorization(self, organization_id: str, route_id: str) -> None:
        row = self.connection.execute("SELECT organization_id FROM callback_authorizations WHERE route_id=?", (route_id,)).fetchone()
        if not row or row["organization_id"] != organization_id:
            raise ValueError("unknown tenant-scoped callback authorization")
        self.connection.execute("UPDATE callback_authorizations SET revoked_at=? WHERE route_id=? AND revoked_at IS NULL", (datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"), route_id))

    def callback_authorization(self, route_id: str) -> dict:
        """Read only an active, unexpired authorization; secrets stay server-side."""
        row = self.connection.execute("SELECT * FROM callback_authorizations WHERE route_id=?", (route_id,)).fetchone()
        if not row or row["revoked_at"] is not None:
            raise ValueError("unknown callback authorization route")
        expires = datetime.fromisoformat(row["expires_at"].replace("Z", "+00:00"))
        if expires <= datetime.now(timezone.utc):
            raise ValueError("callback authorization has expired")
        return dict(row)

    @_atomic_mutation
    def record_authorized_callback(self, route_id: str, event: dict) -> None:
        """Atomically recheck active route lineage and persist its callback."""
        auth = self.callback_authorization(route_id)
        if event.get("pilot_job_id") != auth["pilot_job_id"] or event.get("blueprint_hash") != auth["blueprint_hash"]:
            raise ValueError("callback body does not match configured Pilot authorization")
        self._record_callback_unlocked(auth["organization_id"], event)

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
