"""Read-only GitHub App evidence connector for pinned repository revisions.

The connector deliberately accepts an approval artifact, not a clone URL or a local
path.  A caller supplies a token provider (normally backed by a GitHub App
installation-token service); tokens are used only for the HTTPS Authorization header
and never become part of an artifact, exception, or log message.
"""
from __future__ import annotations

import hashlib
import json
import re
import base64
from collections.abc import Callable
from typing import Any
from urllib.parse import quote
from urllib.request import Request, urlopen

from deploygrade.engine.contracts import validate_artifact

SCHEMA = "../schemas/github_repository_snapshot.schema.json"
CONTENT_EVIDENCE_SCHEMA = "../schemas/github_content_evidence.schema.json"
_SHA = re.compile(r"^[0-9a-f]{40}$")
_NAME = re.compile(r"^[A-Za-z0-9_.-]+$")
_TEXT_SUFFIXES = {".bicep", ".json", ".py", ".sh", ".tf", ".yaml", ".yml"}
_MAX_CONTENT_FILES = 24
_MAX_CONTENT_FILE_BYTES = 262_144
_MAX_CONTENT_TOTAL_BYTES = 1_000_000


class GitHubConnectorError(ValueError):
    """An ambiguous or untrusted GitHub response; callers must pause/escalate."""


def _canonical_hash(value: object) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()


def _validate_identifier(name: str, value: str) -> None:
    if not isinstance(value, str) or not _NAME.fullmatch(value):
        raise GitHubConnectorError(f"invalid GitHub {name}")


def _validate_sha(name: str, value: object) -> str:
    if not isinstance(value, str) or not _SHA.fullmatch(value):
        raise GitHubConnectorError(f"GitHub response has invalid {name}")
    return value


def _https_get(request: Request) -> bytes:
    # Explicitly constrain the network primitive to HTTPS and a short response bound.
    if request.full_url.split(":", 1)[0].lower() != "https":
        raise GitHubConnectorError("GitHub connector requires HTTPS")
    with urlopen(request, timeout=15) as response:  # nosec B310: URL is constructed below from validated fields
        if getattr(response, "status", 200) != 200:
            raise GitHubConnectorError("GitHub returned a non-success response")
        content_type = response.headers.get("Content-Type", "")
        if not content_type.lower().startswith("application/json"):
            raise GitHubConnectorError("GitHub response must be JSON")
        body = response.read(2_000_001)
    if len(body) > 2_000_000:
        raise GitHubConnectorError("GitHub response exceeds maximum size")
    return body


class GitHubRepositoryConnector:
    """Fetch a pinned commit/tree through the GitHub REST API without cloning code."""

    def __init__(self, token_provider: Callable[[], str], *, api_base: str = "https://api.github.com", transport: Callable[[Request], bytes] | None = None):
        if not api_base.startswith("https://") or api_base.rstrip("/") != api_base or "/" in api_base[8:]:
            raise GitHubConnectorError("GitHub API base must be an HTTPS origin without a path")
        self._api_base = api_base
        self._token_provider = token_provider
        self._transport = transport or _https_get

    def _get_json(self, path: str) -> dict[str, Any]:
        token = self._token_provider()
        if not isinstance(token, str) or len(token) < 20 or any(c.isspace() for c in token):
            raise GitHubConnectorError("GitHub installation token is unavailable")
        request = Request(
            f"{self._api_base}{path}",
            headers={"Accept": "application/vnd.github+json", "Authorization": f"Bearer {token}", "X-GitHub-Api-Version": "2022-11-28"},
            method="GET",
        )
        try:
            raw = self._transport(request)
            response = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError, OSError, TimeoutError) as error:
            raise GitHubConnectorError("GitHub response could not be safely decoded") from error
        if not isinstance(response, dict):
            raise GitHubConnectorError("GitHub response must be a JSON object")
        return response

    def snapshot(self, approval: dict) -> dict:
        """Produce a validated evidence artifact from an already-approved pinned SHA."""
        if not isinstance(approval, dict):
            raise GitHubConnectorError("GitHub approval must be an object")
        required = {"organization_id", "engagement_id", "repository", "approval"}
        if set(approval) != required:
            raise GitHubConnectorError("GitHub approval has an ambiguous shape")
        repository = approval["repository"]
        approved = approval["approval"]
        if not isinstance(repository, dict) or set(repository) != {"repository_id", "owner", "name", "revision"}:
            raise GitHubConnectorError("GitHub repository approval has an ambiguous shape")
        if not isinstance(approved, dict) or set(approved) != {"approval_id", "approved_by", "status"} or approved["status"] != "APPROVED":
            raise GitHubConnectorError("GitHub repository is not approved")
        for key in ("owner", "name", "repository_id"):
            _validate_identifier(key, repository[key])
        revision = _validate_sha("approved revision", repository["revision"])
        owner, name = quote(repository["owner"], safe=""), quote(repository["name"], safe="")
        commit = self._get_json(f"/repos/{owner}/{name}/commits/{revision}")
        if set(commit) < {"sha", "commit", "html_url"} or not isinstance(commit.get("commit"), dict):
            raise GitHubConnectorError("GitHub commit response has an ambiguous shape")
        if _validate_sha("commit SHA", commit["sha"]) != revision:
            raise GitHubConnectorError("GitHub commit SHA does not match the approved revision")
        tree = commit["commit"].get("tree")
        if not isinstance(tree, dict) or set(tree) < {"sha", "url"}:
            raise GitHubConnectorError("GitHub commit does not provide a tree")
        tree_sha = _validate_sha("tree SHA", tree["sha"])
        tree_response = self._get_json(f"/repos/{owner}/{name}/git/trees/{tree_sha}?recursive=1")
        if set(tree_response) < {"sha", "truncated", "tree"} or tree_response["truncated"] is not False or not isinstance(tree_response["tree"], list):
            raise GitHubConnectorError("GitHub tree response is incomplete or ambiguous")
        if _validate_sha("tree response SHA", tree_response["sha"]) != tree_sha:
            raise GitHubConnectorError("GitHub tree SHA does not match the commit")
        files = []
        for entry in tree_response["tree"]:
            if not isinstance(entry, dict) or set(entry) < {"path", "type", "sha", "size"} or entry["type"] != "blob":
                continue
            path, blob_sha, size = entry["path"], _validate_sha("blob SHA", entry["sha"]), entry["size"]
            if not isinstance(path, str) or not path or path.startswith("/") or ".." in path.split("/") or not isinstance(size, int) or size < 0:
                raise GitHubConnectorError("GitHub tree contains unsafe evidence metadata")
            files.append({"path": path, "git_blob_sha": blob_sha, "size": size})
        files.sort(key=lambda item: item["path"])
        if len({item["path"] for item in files}) != len(files):
            raise GitHubConnectorError("GitHub tree has duplicate evidence paths")
        manifest = {"tree_sha": tree_sha, "files": files}
        artifact = {
            "$schema": SCHEMA, "schema_version": "1.0",
            "organization_id": approval["organization_id"], "engagement_id": approval["engagement_id"],
            "repository": {**repository, "provider": "github"}, "approval": approved,
            "access": {"mode": "READ_ONLY", "network_egress": "DENY_ALL"},
            "commit": {"sha": revision, "html_url": commit["html_url"]},
            "evidence_manifest": {**manifest, "content_hash": _canonical_hash(manifest)},
        }
        try:
            validate_artifact(artifact)
        except ValueError as error:
            raise GitHubConnectorError("GitHub snapshot violates the evidence contract") from error
        return artifact

    @staticmethod
    def _eligible_content_files(snapshot: dict) -> list[dict]:
        """Select a fixed, bounded, policy-defined set of text candidates.

        The selection comes exclusively from the immutable snapshot manifest; no
        caller-provided globs, paths, or URLs are accepted.  This prevents a
        discovery request from widening an approved repository scan.
        """
        files = []
        for item in snapshot["evidence_manifest"]["files"]:
            path = item["path"]
            suffix = "." + path.rsplit(".", 1)[1].lower() if "." in path.rsplit("/", 1)[-1] else ""
            if suffix in _TEXT_SUFFIXES and item["size"] <= _MAX_CONTENT_FILE_BYTES:
                files.append(item)
        return files[:_MAX_CONTENT_FILES]

    @staticmethod
    def _rules(path: str, text: str) -> list[tuple[str, str, str, bool]]:
        """Return deterministic static checks without retaining source content."""
        name = path.rsplit("/", 1)[-1].lower()
        lower_path = path.lower()
        stripped = text.strip()
        return [
            ("rollback", "rollback_plan", "github.rollback.revert", "rollback" in name and "set -e" in text and "revert" in text),
            ("tests", "operational_assurance", "github.tests.assertions", "test" in name and "assert " in text and "assert True" not in text),
            ("ci", "operational_assurance", "github.ci.test-command", (".github/workflows" in lower_path or name in {".gitlab-ci.yml", "jenkinsfile"}) and ("pytest" in text or "npm test" in text)),
            ("iac", "change_control", "github.iac.resource", path.endswith((".tf", ".bicep")) and "resource " in text),
            ("cloud", "environment_isolation", "github.cloud.configuration", ("cloud" in lower_path or "k8s" in lower_path) and len(stripped) > 20),
            ("iam", "access_control", "github.iam.policy", ("iam" in lower_path or "policy" in name) and len(stripped) > 10 and stripped != "{}"),
        ]

    def content_evidence(self, snapshot: dict) -> dict:
        """Inspect allowlisted blobs ephemerally and return redacted evidence only.

        Blob bytes are decoded in memory, checked by deterministic rules, and
        discarded before the result is created.  The resulting artifact contains
        immutable blob identities and content digests, never source text,
        credentials, excerpts, clone URLs, or installation tokens.
        """
        try:
            validate_artifact(snapshot)
        except ValueError as error:
            raise GitHubConnectorError("GitHub content inspection requires a valid snapshot") from error
        if snapshot.get("$schema") != SCHEMA:
            raise GitHubConnectorError("GitHub content inspection requires a GitHub snapshot")
        selected = self._eligible_content_files(snapshot)
        total_size = sum(item["size"] for item in selected)
        if total_size > _MAX_CONTENT_TOTAL_BYTES:
            raise GitHubConnectorError("GitHub content inspection exceeds total size limit")
        owner, name = quote(snapshot["repository"]["owner"], safe=""), quote(snapshot["repository"]["name"], safe="")
        examined, findings = [], []
        for item in selected:
            response = self._get_json(f"/repos/{owner}/{name}/git/blobs/{item['git_blob_sha']}")
            if set(response) - {"content", "encoding", "sha", "size", "url", "node_id"} or not {"content", "encoding", "sha", "size"} <= set(response):
                raise GitHubConnectorError("GitHub blob response has an ambiguous shape")
            if response["encoding"] != "base64" or _validate_sha("blob response SHA", response["sha"]) != item["git_blob_sha"]:
                raise GitHubConnectorError("GitHub blob response is not bound to the approved manifest")
            if response["size"] != item["size"] or not isinstance(response["content"], str):
                raise GitHubConnectorError("GitHub blob response size is invalid")
            try:
                # GitHub may wrap base64 at newlines.  Permit only that wire
                # formatting; other whitespace remains an ambiguous response.
                if any(char.isspace() and char not in "\r\n" for char in response["content"]):
                    raise ValueError("invalid base64 whitespace")
                raw = base64.b64decode(response["content"].replace("\n", "").replace("\r", ""), validate=True)
                text = raw.decode("utf-8")
            except (ValueError, UnicodeDecodeError) as error:
                raise GitHubConnectorError("GitHub content inspection accepts UTF-8 text blobs only") from error
            if len(raw) != item["size"] or len(raw) > _MAX_CONTENT_FILE_BYTES:
                raise GitHubConnectorError("GitHub blob violates content inspection size limit")
            content_sha256 = hashlib.sha256(raw).hexdigest()
            examined.append({"path": item["path"], "git_blob_sha": item["git_blob_sha"], "size": item["size"], "content_sha256": content_sha256})
            for category, sub_score, rule_id, matched in self._rules(item["path"], text):
                if matched:
                    findings.append({"category": category, "sub_score": sub_score, "rule_id": rule_id,
                                     "path": item["path"], "git_blob_sha": item["git_blob_sha"],
                                     "content_sha256": content_sha256})
            # Keep source text scoped to this iteration; never attach it to an artifact.
            del raw, text
        examined.sort(key=lambda value: value["path"])
        findings.sort(key=lambda value: (value["category"], value["path"], value["rule_id"]))
        unsigned = {"snapshot_manifest_hash": snapshot["evidence_manifest"]["content_hash"], "examined_blobs": examined, "findings": findings}
        artifact = {
            "$schema": CONTENT_EVIDENCE_SCHEMA, "schema_version": "1.0",
            "organization_id": snapshot["organization_id"], "engagement_id": snapshot["engagement_id"],
            "repository": snapshot["repository"], "snapshot_manifest_hash": snapshot["evidence_manifest"]["content_hash"],
            "policy": {"version": "github-content-v1", "max_files": _MAX_CONTENT_FILES,
                       "max_file_bytes": _MAX_CONTENT_FILE_BYTES, "max_total_bytes": _MAX_CONTENT_TOTAL_BYTES,
                       "source_retention": "NONE"},
            "examined_blobs": examined, "findings": findings,
            "content_evidence_hash": _canonical_hash(unsigned),
        }
        try:
            validate_artifact(artifact)
        except ValueError as error:
            raise GitHubConnectorError("GitHub content evidence violates the contract") from error
        return artifact
