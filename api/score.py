"""Schema-validating, deterministic readiness-score HTTP endpoint for Vercel."""
from http.server import BaseHTTPRequestHandler
import json

from deploygrade.engine.score import score_readiness


MAX_BODY_BYTES = 32_768
SUPPORTED_PUBLIC_RUBRICS = frozenset({"2026.07.0"})


def calculate(payload: object) -> dict:
    """Return a score artifact or raise ValueError without changing score semantics."""
    if not isinstance(payload, dict):
        raise ValueError("request body must be a JSON object")
    if payload.get("rubric_version") not in SUPPORTED_PUBLIC_RUBRICS:
        raise ValueError("rubric_version is not published for the public calculator")
    return score_readiness(payload)


class handler(BaseHTTPRequestHandler):
    """Vercel Python function handler for POST /api/score."""

    def _send_json(self, status: int, payload: dict) -> None:
        body = json.dumps(payload, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-DeployGrade-Input-Trust", "unverified-declared-evidence")
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self) -> None:  # noqa: N802 - required by BaseHTTPRequestHandler
        try:
            content_length = int(self.headers.get("Content-Length", "0"))
            if content_length <= 0 or content_length > MAX_BODY_BYTES:
                raise ValueError("request body must be between 1 and 32768 bytes")
            if self.headers.get("Content-Type", "").split(";", 1)[0].lower() != "application/json":
                raise ValueError("Content-Type must be application/json")
            payload = json.loads(self.rfile.read(content_length))
            self._send_json(200, calculate(payload))
        except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as error:
            self._send_json(400, {"error": str(error)})

    def do_GET(self) -> None:  # noqa: N802 - required by BaseHTTPRequestHandler
        self._send_json(405, {"error": "use POST with a readiness-input JSON artifact"})
