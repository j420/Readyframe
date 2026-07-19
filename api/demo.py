"""Vercel endpoint for the deterministic, safe Build Week hero flow."""
from http.server import BaseHTTPRequestHandler
import json
from urllib.parse import parse_qs, urlparse

from deploygrade.engine.demo_flow import run
from api.responses import error_artifact


class handler(BaseHTTPRequestHandler):
    def _send(self, status, value):
        body = json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
        self.send_response(status); self.send_header("Content-Type", "application/json; charset=utf-8"); self.send_header("Cache-Control", "no-store"); self.send_header("Content-Length", str(len(body))); self.end_headers(); self.wfile.write(body)

    def do_GET(self):  # noqa: N802
        try:
            query = parse_qs(urlparse(self.path).query, keep_blank_values=True)
            unknown = set(query) - {"profile"}
            if unknown:
                raise ValueError("unsupported query parameter")
            profiles = query.get("profile", ["deceptive"])
            if len(profiles) != 1:
                raise ValueError("profile must be provided at most once")
            profile = profiles[0]
            self._send(200, run(profile))
        except ValueError as error:
            self._send(400, error_artifact(str(error)))

    def _method_not_allowed(self):
        self._send(405, error_artifact("use GET /api/demo?profile=mature|deceptive"))

    def do_POST(self):  # noqa: N802
        self._method_not_allowed()

    do_PUT = do_PATCH = do_DELETE = do_HEAD = do_OPTIONS = _method_not_allowed
