"""PostgreSQL implementation of the tenant-scoped control-plane boundary.

The adapter uses ``psycopg`` (v3) and the checked-in ``0002`` migration.  It is
intentionally not an ORM: every query carries the organization predicate and
every transaction sets ``app.organization_id`` so PostgreSQL row-level security
is a second, database-enforced tenant boundary.  The database role used by this
adapter must *not* have ``BYPASSRLS``.
"""
from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
import json
import secrets
import uuid
from typing import Iterator
from threading import RLock

from deploygrade.engine.contracts import validate_artifact
from deploygrade.engine.control_plane import _validate_callback_identity, canonical_hash


class PostgresUnavailableError(RuntimeError):
    """Raised when the optional production database driver is unavailable."""


def _driver():
    try:
        import psycopg
        from psycopg.rows import dict_row
    except ImportError as error:  # pragma: no cover - depends on deployment extras
        raise PostgresUnavailableError(
            "PostgreSQL control-plane support requires psycopg; install requirements-production.txt"
        ) from error
    return psycopg, dict_row


class PostgresControlPlaneStore:
    """Durable Postgres storage with tenant-scoped transactions and RLS context."""

    backend = "postgresql"

    def __init__(self, database_url: str):
        if not isinstance(database_url, str) or not database_url:
            raise ValueError("PostgreSQL database URL is required")
        psycopg, dict_row = _driver()
        self._connection = psycopg.connect(database_url, autocommit=False, row_factory=dict_row)
        # A connection represents one transaction at a time.  Vercel may serve
        # concurrent requests in one warm process, so do not allow tenant
        # session context from one request to interleave with another.
        self._lock = RLock()
        # A session setting makes accidental unscoped SQL fail rather than using
        # a value inherited from a pooled connection.
        with self._connection.cursor() as cursor:
            cursor.execute("SET app.organization_id = ''")
        self._connection.commit()

    def close(self) -> None:
        self._connection.close()

    @contextmanager
    def _transaction(self, organization_id: str) -> Iterator[object]:
        if not isinstance(organization_id, str) or not organization_id:
            raise ValueError("organization id is required")
        with self._lock:
            with self._connection.transaction():
                with self._connection.cursor() as cursor:
                    cursor.execute("SELECT set_config('app.organization_id', %s, true)", (organization_id,))
                    yield cursor

    @staticmethod
    def _row(cursor, query: str, params: tuple):
        cursor.execute(query, params)
        return cursor.fetchone()

    def readiness(self) -> dict:
        try:
            with self._lock:
                with self._connection.cursor() as cursor:
                    cursor.execute("SELECT 1")
                    cursor.fetchone()
        except Exception as error:
            raise ValueError("control-plane storage is unavailable") from error
        return {"backend": self.backend, "durable": True, "ready": True}

    def create_organization(self, organization_id: str) -> None:
        with self._transaction(organization_id) as cursor:
            cursor.execute(
                "INSERT INTO deploygrade.organizations(id) VALUES (%s) ON CONFLICT (id) DO NOTHING",
                (organization_id,),
            )

    def create_engagement(self, organization_id: str, engagement_id: str, vertical: str) -> None:
        with self._transaction(organization_id) as cursor:
            self._organization(cursor, organization_id)
            cursor.execute(
                "INSERT INTO deploygrade.engagements(id, organization_id, vertical) VALUES (%s,%s,%s)",
                (engagement_id, organization_id, vertical),
            )

    def store_artifact(self, organization_id: str, engagement_id: str, payload: dict) -> str:
        validate_artifact(payload)
        digest = canonical_hash(payload)
        serialized = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        with self._transaction(organization_id) as cursor:
            self._engagement(cursor, organization_id, engagement_id)
            existing = self._row(cursor, "SELECT organization_id, engagement_id, payload::text AS payload FROM deploygrade.artifacts WHERE hash=%s", (digest,))
            if existing:
                # jsonb text ordering differs from source serialization, so compare
                # parsed values rather than relying on whitespace/key ordering.
                if existing["organization_id"] != organization_id or existing["engagement_id"] != engagement_id or json.loads(existing["payload"]) != payload:
                    raise ValueError("artifact hash is already bound to a different tenant or engagement")
                return digest
            try:
                cursor.execute(
                    "INSERT INTO deploygrade.artifacts(hash,organization_id,engagement_id,schema_uri,payload) VALUES (%s,%s,%s,%s,%s::jsonb)",
                    (digest, organization_id, engagement_id, payload["$schema"], serialized),
                )
            except Exception as error:
                # Under RLS an identical global hash owned by another tenant is
                # intentionally invisible to the preliminary SELECT.  Preserve
                # the public fail-closed contract without leaking its owner.
                if error.__class__.__name__ == "UniqueViolation":
                    raise ValueError("artifact hash is already bound to a different tenant or engagement") from error
                raise
        return digest

    def approve(self, organization_id: str, engagement_id: str, artifact_hash: str, approved_by: str, decision: str = "APPROVED") -> str:
        if decision not in {"APPROVED", "REJECTED"}:
            raise ValueError("unknown approval decision")
        approval_id = str(uuid.uuid4())
        with self._transaction(organization_id) as cursor:
            self._artifact(cursor, organization_id, engagement_id, artifact_hash)
            cursor.execute(
                "INSERT INTO deploygrade.approvals(id,organization_id,engagement_id,artifact_hash,decision,approved_by) VALUES (%s,%s,%s,%s,%s,%s)",
                (approval_id, organization_id, engagement_id, artifact_hash, decision, approved_by),
            )
        return approval_id

    def create_pilot_job(self, organization_id: str, engagement_id: str, blueprint_hash: str, approval_id: str, sandbox_repository: str) -> str:
        if not sandbox_repository:
            raise ValueError("Pilot job requires an approved sandbox repository")
        job_id = str(uuid.uuid4())
        with self._transaction(organization_id) as cursor:
            blueprint = self._artifact(cursor, organization_id, engagement_id, blueprint_hash)
            if blueprint["schema_uri"] != "../schemas/rollout_blueprint.schema.json":
                raise ValueError("Pilot job requires a rollout blueprint artifact")
            approval = self._row(cursor, "SELECT artifact_hash, decision FROM deploygrade.approvals WHERE id=%s AND organization_id=%s AND engagement_id=%s", (approval_id, organization_id, engagement_id))
            if not approval or approval["artifact_hash"] != blueprint_hash or approval["decision"] != "APPROVED":
                raise ValueError("Pilot job requires an approved approval for the exact blueprint")
            cursor.execute(
                "INSERT INTO deploygrade.pilot_jobs(id,organization_id,engagement_id,blueprint_hash,approval_id,sandbox_repository,status) VALUES (%s,%s,%s,%s,%s,%s,'QUEUED')",
                (job_id, organization_id, engagement_id, blueprint_hash, approval_id, sandbox_repository),
            )
        return job_id

    def _record_callback(self, cursor, organization_id: str, event: dict) -> None:
        validate_artifact(event)
        _validate_callback_identity(event)
        if self._row(cursor, "SELECT event_id FROM deploygrade.pilot_events WHERE event_id=%s", (event["event_id"],)):
            raise ValueError("duplicate callback event")
        job = self._row(cursor, "SELECT id, blueprint_hash, status FROM deploygrade.pilot_jobs WHERE id=%s AND organization_id=%s FOR UPDATE", (event["pilot_job_id"], organization_id))
        if not job or job["blueprint_hash"] != event["blueprint_hash"]:
            raise ValueError("callback job and blueprint lineage is unknown or mismatched")
        allowed = {
            "QUEUED": {"PILOT_STARTED", "THRESHOLD_BREACHED", "ROLLBACK_FIRED", "PILOT_PAUSED"},
            "RUNNING": {"ACTION_DENIED", "METRIC_RECORDED", "THRESHOLD_BREACHED", "ROLLBACK_FIRED", "COMPENSATING_REVERTED", "PILOT_PAUSED"},
            "PAUSED": {"COMPENSATING_REVERTED"},
        }
        if event["event_type"] not in allowed.get(job["status"], set()):
            raise ValueError(f"callback event is not allowed while Pilot job is {job['status']}")
        cursor.execute(
            "INSERT INTO deploygrade.pilot_events(event_id,organization_id,pilot_job_id,blueprint_hash,event_type,payload) VALUES (%s,%s,%s,%s,%s,%s::jsonb)",
            (event["event_id"], organization_id, job["id"], event["blueprint_hash"], event["event_type"], json.dumps(event, sort_keys=True, separators=(",", ":"))),
        )
        status = {"PILOT_STARTED": "RUNNING", "THRESHOLD_BREACHED": "PAUSED", "ROLLBACK_FIRED": "PAUSED", "PILOT_PAUSED": "PAUSED", "COMPENSATING_REVERTED": "REVERTED"}.get(event["event_type"])
        if status:
            cursor.execute("UPDATE deploygrade.pilot_jobs SET status=%s WHERE id=%s AND organization_id=%s", (status, job["id"], organization_id))

    def record_callback(self, organization_id: str, event: dict) -> None:
        with self._transaction(organization_id) as cursor:
            self._record_callback(cursor, organization_id, event)

    def issue_callback_authorization(self, organization_id: str, pilot_job_id: str, *, ttl_seconds: int = 300) -> dict:
        if not isinstance(ttl_seconds, int) or isinstance(ttl_seconds, bool) or not 30 <= ttl_seconds <= 3600:
            raise ValueError("callback authorization ttl must be between 30 and 3600 seconds")
        route_id, secret = uuid.uuid4().hex, secrets.token_urlsafe(32)
        with self._transaction(organization_id) as cursor:
            job = self._row(cursor, "SELECT id, blueprint_hash, status FROM deploygrade.pilot_jobs WHERE id=%s AND organization_id=%s FOR UPDATE", (pilot_job_id, organization_id))
            if not job or job["status"] not in {"QUEUED", "RUNNING", "PAUSED"}:
                raise ValueError("callback authorization requires a non-terminal tenant-scoped Pilot job")
            cursor.execute(
                "INSERT INTO deploygrade.callback_authorizations(route_id,organization_id,pilot_job_id,blueprint_hash,signing_secret,expires_at) VALUES (%s,%s,%s,%s,%s,now() + (%s * interval '1 second')) RETURNING expires_at",
                (route_id, organization_id, pilot_job_id, job["blueprint_hash"], secret, ttl_seconds),
            )
            expires_at = cursor.fetchone()["expires_at"]
        return {"route_id": route_id, "organization_id": organization_id, "pilot_job_id": pilot_job_id, "blueprint_hash": job["blueprint_hash"], "signing_secret": secret, "expires_at": expires_at.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")}

    def revoke_callback_authorization(self, organization_id: str, route_id: str) -> None:
        with self._transaction(organization_id) as cursor:
            cursor.execute("UPDATE deploygrade.callback_authorizations SET revoked_at=now() WHERE route_id=%s AND organization_id=%s AND revoked_at IS NULL", (route_id, organization_id))
            if cursor.rowcount != 1:
                raise ValueError("unknown tenant-scoped callback authorization")

    def callback_authorization(self, route_id: str) -> dict:
        # Public interface does not carry organization id.  Resolve the route
        # with a narrowly scoped SECURITY DEFINER function supplied by migration;
        # it returns only active data and does not expose arbitrary rows.
        with self._lock:
            with self._connection.transaction():
                with self._connection.cursor() as cursor:
                    cursor.execute("SELECT * FROM deploygrade.active_callback_authorization(%s)", (route_id,))
                    row = cursor.fetchone()
        if not row:
            raise ValueError("unknown callback authorization route")
        return dict(row)

    def record_authorized_callback(self, route_id: str, event: dict) -> None:
        # Authorization and event recording share one row-locked transaction.
        # The function returns the tenant context without allowing caller choice.
        with self._lock:
            with self._connection.transaction():
                with self._connection.cursor() as cursor:
                    # Resolve the opaque route first, then establish tenant RLS
                    # context before taking a row lock on the underlying table. A
                    # ``FOR UPDATE`` on a set-returning SQL function is not a row
                    # lock on the source table and would race revocation.
                    cursor.execute("SELECT * FROM deploygrade.active_callback_authorization(%s)", (route_id,))
                    resolved = cursor.fetchone()
                    if not resolved:
                        raise ValueError("unknown callback authorization route")
                    cursor.execute("SELECT set_config('app.organization_id', %s, true)", (resolved["organization_id"],))
                    cursor.execute("SELECT * FROM deploygrade.callback_authorizations WHERE route_id=%s AND revoked_at IS NULL AND expires_at > now() FOR UPDATE", (route_id,))
                    auth = cursor.fetchone()
                    if not auth:
                        raise ValueError("unknown callback authorization route")
                    if event.get("pilot_job_id") != auth["pilot_job_id"] or event.get("blueprint_hash") != auth["blueprint_hash"]:
                        raise ValueError("callback body does not match configured Pilot authorization")
                    self._record_callback(cursor, auth["organization_id"], event)

    def job_status(self, organization_id: str, job_id: str) -> str:
        with self._transaction(organization_id) as cursor:
            row = self._row(cursor, "SELECT status FROM deploygrade.pilot_jobs WHERE id=%s AND organization_id=%s", (job_id, organization_id))
        if not row:
            raise ValueError("unknown tenant-scoped Pilot job")
        return row["status"]

    @staticmethod
    def _organization(cursor, organization_id: str) -> None:
        if not PostgresControlPlaneStore._row(cursor, "SELECT id FROM deploygrade.organizations WHERE id=%s", (organization_id,)):
            raise ValueError("unknown organization")

    @staticmethod
    def _engagement(cursor, organization_id: str, engagement_id: str) -> None:
        if not PostgresControlPlaneStore._row(cursor, "SELECT id FROM deploygrade.engagements WHERE id=%s AND organization_id=%s", (engagement_id, organization_id)):
            raise ValueError("unknown tenant-scoped engagement")

    @staticmethod
    def _artifact(cursor, organization_id: str, engagement_id: str, artifact_hash: str):
        row = PostgresControlPlaneStore._row(cursor, "SELECT hash, schema_uri FROM deploygrade.artifacts WHERE hash=%s AND organization_id=%s AND engagement_id=%s", (artifact_hash, organization_id, engagement_id))
        if not row:
            raise ValueError("unknown tenant-scoped artifact")
        return row
