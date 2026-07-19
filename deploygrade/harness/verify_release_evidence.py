"""Fail closed on missing evidence for a claimed production release.

This verifier intentionally validates an operator-provided attestation; it does not
pretend a repository checkout can provision, inspect, or attest to external cloud
infrastructure.  A release gate can require this checked contract alongside the
live endpoint and platform-specific verification steps.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

from deploygrade.engine.contracts import validate_artifact

_PLACEHOLDERS = ("example.invalid", "replace-with", "changeme", "your-")


def _https_origin(value: str) -> bool:
    parsed = urlparse(value)
    return parsed.scheme == "https" and bool(parsed.netloc) and not parsed.path and not parsed.query and not parsed.fragment


def verify(path: str | Path, *, expected_commit: str | None = None) -> dict:
    """Validate a complete, non-placeholder release evidence artifact."""
    try:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError("release evidence must be a readable JSON artifact") from error
    validate_artifact(payload)
    for field in ("deployed_origin", "worker_endpoint", "verified_by"):
        if any(marker in payload[field].lower() for marker in _PLACEHOLDERS):
            raise ValueError("release evidence contains a placeholder value")
    if not _https_origin(payload["deployed_origin"]) or not _https_origin(payload["worker_endpoint"]):
        raise ValueError("release evidence endpoints must be clean HTTPS origins")
    try:
        verified_at = datetime.fromisoformat(payload["verified_at"].replace("Z", "+00:00"))
    except ValueError as error:
        raise ValueError("release evidence verified_at must be RFC3339") from error
    if verified_at.tzinfo is None or verified_at.astimezone(timezone.utc) > datetime.now(timezone.utc):
        raise ValueError("release evidence verified_at must be a non-future timezone-aware timestamp")
    if expected_commit and payload["release_commit"] != expected_commit:
        raise ValueError("release evidence commit does not match the release checkout")
    return payload


def main() -> None:
    path = os.environ.get("DEPLOYGRADE_RELEASE_EVIDENCE_FILE")
    if not path:
        raise ValueError("DEPLOYGRADE_RELEASE_EVIDENCE_FILE is required")
    commit = subprocess.run(["git", "rev-parse", "HEAD"], check=True, capture_output=True, text=True).stdout.strip()
    verify(path, expected_commit=commit)
    print("Production release evidence validated")


if __name__ == "__main__":
    try:
        main()
    except (ValueError, subprocess.CalledProcessError) as error:
        print(f"Release evidence verification failed: {error}", file=sys.stderr)
        raise SystemExit(1)
