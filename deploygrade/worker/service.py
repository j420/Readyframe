"""Small, dependency-free worker service boundary.

The service is intended to run only behind an authenticated private ingress in the
isolated worker network.  It accepts schema-valid dispatch artifacts and delegates
all execution semantics to :mod:`deploygrade.engine.worker_runtime`.  That runtime
fails closed for PILOT requests until a separately reviewed tool sandbox is wired
in; this server never shells out, mounts a host path, or handles credentials.
"""
from __future__ import annotations

import hmac
import json
import os
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from deploygrade.engine.worker_runtime import run

_MAX_BODY_BYTES = 1_048_576


def _require_runtime_config(environ: dict[str, str] | None = None) -> dict[str, str]:
    """Return required runtime values or fail before binding a network socket."""
    env = os.environ if environ is None else environ
    token = env.get("DEPLOYGRADE_WORKER_AUTH_TOKEN", "")
    image_digest = env.get("DEPLOYGRADE_WORKER_IMAGE_DIGEST", "")
    policy_version = env.get("DEPLOYGRADE_WORKER_POLICY_VERSION", "")
    if len(token) < 32 or token.lower().startswith("replace-"):
        raise RuntimeError("DEPLOYGRADE_WORKER_AUTH_TOKEN must be a non-placeholder secret of at least 32 characters")
    if len(image_digest) != 71 or not image_digest.startswith("sha256:") or any(c not in "0123456789abcdef" for c in image_digest[7:]):
        raise RuntimeError("DEPLOYGRADE_WORKER_IMAGE_DIGEST must be a pinned sha256 digest")
    if not policy_version or policy_version.lower().startswith("replace-"):
        raise RuntimeError("DEPLOYGRADE_WORKER_POLICY_VERSION must be configured")
    return {"token": token, "image_digest": image_digest, "policy_version": policy_version}


def _json_error(handler: BaseHTTPRequestHandler, status: int, code: str) -> None:
    payload = json.dumps({"error": code}, separators=(",", ":")).encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json")
    handler.send_header("Content-Length", str(len(payload)))
    handler.end_headers()
    handler.wfile.write(payload)


def handler_factory(config: dict[str, str]):
    """Create a private-ingress handler with bounded, constant-time auth checks."""
    class WorkerHandler(BaseHTTPRequestHandler):
        server_version = "DeployGradeWorker/1.0"

        def log_message(self, _format: str, *_args: object) -> None:
            # Request bodies, repository details, and credentials must never enter logs.
            return

        def do_GET(self) -> None:
            if self.path != "/healthz":
                _json_error(self, HTTPStatus.NOT_FOUND, "not_found")
                return
            payload = json.dumps({"status": "ok", "policy_version": config["policy_version"]}, separators=(",", ":")).encode("utf-8")
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        def do_POST(self) -> None:
            if self.path != "/v1/dispatch":
                _json_error(self, HTTPStatus.NOT_FOUND, "not_found")
                return
            if not hmac.compare_digest(self.headers.get("X-DeployGrade-Worker-Token", ""), config["token"]):
                _json_error(self, HTTPStatus.UNAUTHORIZED, "unauthorized")
                return
            if self.headers.get("Content-Type", "").split(";", 1)[0].lower() != "application/json":
                _json_error(self, HTTPStatus.UNSUPPORTED_MEDIA_TYPE, "content_type_required")
                return
            try:
                length = int(self.headers.get("Content-Length", ""))
            except ValueError:
                _json_error(self, HTTPStatus.LENGTH_REQUIRED, "content_length_required")
                return
            if length < 1 or length > _MAX_BODY_BYTES:
                _json_error(self, HTTPStatus.REQUEST_ENTITY_TOO_LARGE, "invalid_content_length")
                return
            try:
                payload = json.loads(self.rfile.read(length).decode("utf-8"))
                if not isinstance(payload, dict) or set(payload) - {"dispatch", "connector", "environment", "github_content_evidence"}:
                    raise ValueError("invalid payload")
                result = run(payload["dispatch"], payload["connector"], environment=payload.get("environment", "unknown"),
                             github_content_evidence=payload.get("github_content_evidence"))
            except (KeyError, UnicodeDecodeError, json.JSONDecodeError, ValueError) as error:
                _json_error(self, HTTPStatus.BAD_REQUEST, "invalid_dispatch")
                return
            body = json.dumps(result, separators=(",", ":"), sort_keys=True).encode("utf-8")
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("X-DeployGrade-Worker-Image-Digest", config["image_digest"])
            self.end_headers()
            self.wfile.write(body)
    return WorkerHandler


def main() -> None:
    config = _require_runtime_config()
    host = os.environ.get("DEPLOYGRADE_WORKER_BIND", "0.0.0.0")
    port = int(os.environ.get("PORT", "8080"))
    if host not in {"0.0.0.0", "127.0.0.1"} or not 1 <= port <= 65535:
        raise RuntimeError("invalid private worker bind configuration")
    ThreadingHTTPServer((host, port), handler_factory(config)).serve_forever()


if __name__ == "__main__":
    main()
