"""Fail-closed, signed Pilot event callback for the Vercel control plane.

This endpoint only accepts events that are schema-valid and have not already been
accepted by this process. Durable replay protection and job/blueprint lineage
validation must be supplied by the control-plane persistence layer before a
production Pilot worker is connected.
"""
from http.server import BaseHTTPRequestHandler
from collections import OrderedDict
from datetime import datetime, timezone
import hashlib
import hmac
import json
import os
import threading
import uuid

from api.responses import error_artifact
from deploygrade.engine.contracts import validate_artifact

MAX_BODY_BYTES = 32_768
MAX_REPLAY_IDS = 4_096
_SCHEMA_URI = "../schemas/pilot_callback.schema.json"
_seen_event_ids: OrderedDict[str, None] = OrderedDict()
_seen_event_ids_lock = threading.Lock()


class ReplayDetected(ValueError):
    """Raised when the same signed callback event is delivered twice."""


def _validate_event_identity(event: dict) -> None:
    """Reject ambiguous event identifiers and invalid timestamps."""
    if not isinstance(event, dict):
        raise ValueError("callback body must be a JSON object")
    event_id = event.get("event_id")
    if not isinstance(event_id, str):
        raise ValueError("event_id must be a UUID string")
    try:
        parsed_id = uuid.UUID(event_id)
    except (ValueError, AttributeError) as error:
        raise ValueError("event_id must be a UUID string") from error
    if str(parsed_id) != event_id.lower():
        raise ValueError("event_id must be a canonical UUID string")

    occurred_at = event.get("occurred_at")
    if not isinstance(occurred_at, str) or not occurred_at.endswith("Z"):
        raise ValueError("occurred_at must be an RFC3339 UTC timestamp")
    try:
        parsed_time = datetime.fromisoformat(occurred_at[:-1] + "+00:00")
    except ValueError as error:
        raise ValueError("occurred_at must be an RFC3339 UTC timestamp") from error
    if parsed_time.tzinfo != timezone.utc:
        raise ValueError("occurred_at must be an RFC3339 UTC timestamp")


def _record_event_id(event_id: str) -> None:
    """Record an accepted event ID atomically; a duplicate fails closed."""
    with _seen_event_ids_lock:
        if event_id in _seen_event_ids:
            raise ReplayDetected("duplicate callback event_id")
        _seen_event_ids[event_id] = None
        if len(_seen_event_ids) > MAX_REPLAY_IDS:
            _seen_event_ids.popitem(last=False)


def _clear_replay_cache_for_test() -> None:
    """Test-only helper; production code never clears accepted callback IDs."""
    with _seen_event_ids_lock:
        _seen_event_ids.clear()


def _receipt(event: dict) -> dict:
    payload = {
        "$schema": "../schemas/pilot_callback_receipt.schema.json",
        "schema_version": "1.0",
        "accepted": True,
        "event_id": event["event_id"],
        "event_type": event["event_type"],
    }
    validate_artifact(payload)
    return payload


class handler(BaseHTTPRequestHandler):
    """Accept one signed, schema-valid Pilot callback event or reject it."""

    def _send(self, status: int, payload: dict) -> None:
        body = json.dumps(payload, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self) -> None:  # noqa: N802 - required by BaseHTTPRequestHandler
        try:
            secret = os.environ.get("PILOT_CALLBACK_SECRET")
            if not secret:
                raise ValueError("Pilot callback is not configured")
            if self.headers.get("Content-Type", "").split(";", 1)[0].lower() != "application/json":
                raise ValueError("Content-Type must be application/json")
            length_values = self.headers.get_all("Content-Length", [])
            if len(length_values) != 1:
                raise ValueError("callback must include exactly one Content-Length")
            try:
                length = int(length_values[0])
            except ValueError as error:
                raise ValueError("invalid callback body length") from error
            if length <= 0 or length > MAX_BODY_BYTES:
                raise ValueError("invalid callback body length")
            raw = self.rfile.read(length)
            if len(raw) != length:
                raise ValueError("incomplete callback body")
            signature_values = self.headers.get_all("X-DeployGrade-Signature", [])
            if len(signature_values) != 1:
                raise ValueError("callback must include exactly one signature")
            supplied = signature_values[0]
            expected = hmac.new(secret.encode("utf-8"), raw, hashlib.sha256).hexdigest()
            if not hmac.compare_digest(supplied, expected):
                raise ValueError("invalid callback signature")
            event = json.loads(raw.decode("utf-8"))
            _validate_event_identity(event)
            event = {"$schema": _SCHEMA_URI, "schema_version": "1.0", **event}
            validate_artifact(event)
            _record_event_id(event["event_id"])
            self._send(202, _receipt(event))
        except ReplayDetected as error:
            self._send(409, error_artifact(str(error)))
        except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as error:
            self._send(400, error_artifact(str(error)))

    def _method_not_allowed(self) -> None:
        self._send(405, error_artifact("use POST with a signed Pilot callback artifact"))

    do_GET = do_PUT = do_PATCH = do_DELETE = do_HEAD = do_OPTIONS = _method_not_allowed
