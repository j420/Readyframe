"""Durable, tenant-authorized ingestion for signed Pilot worker callbacks.

An HTTP handler (or queue consumer) chooses ``route_id`` from trusted deployment
configuration.  The callback body never selects its tenant, Pilot job, or
blueprint: all three are pinned in :class:`CallbackAuthorization` and must match
before the event reaches the durable control plane.
"""
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import hashlib
import hmac
import json
from collections.abc import Callable, Mapping

from deploygrade.engine.contracts import validate_artifact
from deploygrade.engine.control_plane import ControlPlaneStore


MAX_CALLBACK_BYTES = 32_768
_CALLBACK_SCHEMA = "../schemas/pilot_callback.schema.json"
_RECEIPT_SCHEMA = "../schemas/pilot_callback_receipt.schema.json"


@dataclass(frozen=True)
class CallbackAuthorization:
    """Immutable deployment configuration for one worker callback route."""

    organization_id: str
    pilot_job_id: str
    blueprint_hash: str
    signing_secret: str

    def __post_init__(self) -> None:
        if not all(isinstance(value, str) and value for value in (
            self.organization_id, self.pilot_job_id, self.blueprint_hash, self.signing_secret
        )):
            raise ValueError("callback authorization fields must be non-empty strings")


class CallbackIngestionAdapter:
    """Verify a signed callback, pin its authorization, then ingest it durably.

    ``route_id`` is deliberately an argument supplied by trusted routing
    configuration rather than a body field.  Duplicate event IDs, unknown routes,
    stale timestamps, mismatched lineage, and unsafe state transitions all raise
    ``ValueError`` and are never acknowledged.
    """

    def __init__(
        self,
        store: ControlPlaneStore,
        routes: Mapping[str, CallbackAuthorization],
        *,
        clock: Callable[[], datetime] | None = None,
        max_event_age: timedelta = timedelta(minutes=5),
        max_future_skew: timedelta = timedelta(seconds=30),
    ) -> None:
        if not routes:
            raise ValueError("at least one callback authorization route is required")
        if max_event_age < timedelta(0) or max_future_skew < timedelta(0):
            raise ValueError("callback timestamp windows must not be negative")
        if any(not isinstance(route_id, str) or not route_id for route_id in routes):
            raise ValueError("callback route ids must be non-empty strings")
        if not all(isinstance(route, CallbackAuthorization) for route in routes.values()):
            raise ValueError("callback routes must contain CallbackAuthorization values")
        self._store = store
        self._routes = dict(routes)
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self._max_event_age = max_event_age
        self._max_future_skew = max_future_skew

    def ingest(self, route_id: str, raw_body: bytes, supplied_signature: str) -> dict:
        """Durably record exactly one configured, fresh, signed Pilot event."""
        authorization = self._routes.get(route_id)
        if authorization is None:
            raise ValueError("unknown callback authorization route")
        if not isinstance(raw_body, bytes) or not raw_body or len(raw_body) > MAX_CALLBACK_BYTES:
            raise ValueError("invalid callback body length")
        if not isinstance(supplied_signature, str) or len(supplied_signature) != 64:
            raise ValueError("invalid callback signature")
        expected = hmac.new(authorization.signing_secret.encode("utf-8"), raw_body, hashlib.sha256).hexdigest()
        if not hmac.compare_digest(supplied_signature, expected):
            raise ValueError("invalid callback signature")
        try:
            body = json.loads(raw_body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise ValueError("callback body must be UTF-8 JSON") from error
        if not isinstance(body, dict):
            raise ValueError("callback body must be a JSON object")
        if {"$schema", "schema_version"} & set(body):
            raise ValueError("callback body must not supply artifact contract fields")
        event = {"$schema": _CALLBACK_SCHEMA, "schema_version": "1.0", **body}
        validate_artifact(event)
        self._require_authorized_lineage(event, authorization)
        self._require_fresh_timestamp(event["occurred_at"])
        self._store.record_callback(authorization.organization_id, event)
        receipt = {
            "$schema": _RECEIPT_SCHEMA,
            "schema_version": "1.0",
            "accepted": True,
            "event_id": event["event_id"],
            "event_type": event["event_type"],
        }
        validate_artifact(receipt)
        return receipt

    @staticmethod
    def _require_authorized_lineage(event: dict, authorization: CallbackAuthorization) -> None:
        if event["pilot_job_id"] != authorization.pilot_job_id or event["blueprint_hash"] != authorization.blueprint_hash:
            raise ValueError("callback body does not match configured Pilot authorization")

    def _require_fresh_timestamp(self, occurred_at: str) -> None:
        event_time = datetime.fromisoformat(occurred_at[:-1] + "+00:00")
        now = self._clock()
        if now.tzinfo is None:
            raise ValueError("callback clock must return a timezone-aware timestamp")
        now = now.astimezone(timezone.utc)
        if event_time < now - self._max_event_age or event_time > now + self._max_future_skew:
            raise ValueError("callback timestamp is outside the accepted delivery window")

class StoreCallbackIngestionAdapter:
    """Durable route resolver for job-scoped callback credentials.

    This adapter is intended for production ingress: a route is minted when an
    approved Pilot job is created and is read/rechecked inside the same storage
    transaction that records the callback.  It deliberately has no environment
    route map and never exposes a raw secret in a receipt or artifact.
    """

    def __init__(self, store: ControlPlaneStore, *, clock: Callable[[], datetime] | None = None,
                 max_event_age: timedelta = timedelta(minutes=5),
                 max_future_skew: timedelta = timedelta(seconds=30)) -> None:
        self._store = store
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self._max_event_age = max_event_age
        self._max_future_skew = max_future_skew
        if max_event_age < timedelta(0) or max_future_skew < timedelta(0):
            raise ValueError("callback timestamp windows must not be negative")

    def ingest(self, route_id: str, raw_body: bytes, supplied_signature: str) -> dict:
        if not isinstance(route_id, str) or not route_id:
            raise ValueError("unknown callback authorization route")
        if not isinstance(raw_body, bytes) or not raw_body or len(raw_body) > MAX_CALLBACK_BYTES:
            raise ValueError("invalid callback body length")
        authorization = self._store.callback_authorization(route_id)
        if not isinstance(supplied_signature, str) or len(supplied_signature) != 64:
            raise ValueError("invalid callback signature")
        expected = hmac.new(authorization["signing_secret"].encode("utf-8"), raw_body, hashlib.sha256).hexdigest()
        if not hmac.compare_digest(supplied_signature, expected):
            raise ValueError("invalid callback signature")
        try:
            body = json.loads(raw_body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise ValueError("callback body must be UTF-8 JSON") from error
        if not isinstance(body, dict):
            raise ValueError("callback body must be a JSON object")
        if {"$schema", "schema_version"} & set(body):
            raise ValueError("callback body must not supply artifact contract fields")
        event = {"$schema": _CALLBACK_SCHEMA, "schema_version": "1.0", **body}
        validate_artifact(event)
        if event["pilot_job_id"] != authorization["pilot_job_id"] or event["blueprint_hash"] != authorization["blueprint_hash"]:
            raise ValueError("callback body does not match configured Pilot authorization")
        event_time = datetime.fromisoformat(event["occurred_at"][:-1] + "+00:00")
        now = self._clock()
        if now.tzinfo is None:
            raise ValueError("callback clock must return a timezone-aware timestamp")
        now = now.astimezone(timezone.utc)
        if event_time < now - self._max_event_age or event_time > now + self._max_future_skew:
            raise ValueError("callback timestamp is outside the accepted delivery window")
        self._store.record_authorized_callback(route_id, event)
        receipt = {"$schema": _RECEIPT_SCHEMA, "schema_version": "1.0", "accepted": True,
                   "event_id": event["event_id"], "event_type": event["event_type"]}
        validate_artifact(receipt)
        return receipt
