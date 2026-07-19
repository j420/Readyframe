import hashlib
import json
import base64
import unittest

from deploygrade.engine.github_connector import GitHubConnectorError, GitHubRepositoryConnector


REVISION = "a" * 40
TREE = "b" * 40
BLOB_A = "c" * 40
BLOB_B = "d" * 40
APPROVAL = {
    "organization_id": "org-1", "engagement_id": "engagement-1",
    "repository": {"repository_id": "42", "owner": "deploygrade", "name": "readyframe", "revision": REVISION},
    "approval": {"approval_id": "approval-1", "approved_by": "operator-1", "status": "APPROVED"},
}


def transport_for(*, commit_sha=REVISION, tree_sha=TREE, truncated=False, entries=None, blobs=None):
    entries = entries if entries is not None else [
        {"path": "z.txt", "type": "blob", "sha": BLOB_B, "size": 9},
        {"path": "a.txt", "type": "blob", "sha": BLOB_A, "size": 3},
    ]
    seen = []
    def transport(request):
        seen.append(request)
        if "/commits/" in request.full_url:
            return json.dumps({"sha": commit_sha, "html_url": "https://github.com/deploygrade/readyframe/commit/" + REVISION,
                               "commit": {"tree": {"sha": TREE, "url": "https://api.github.com/tree"}}}).encode()
        if "/git/blobs/" in request.full_url:
            sha = request.full_url.rsplit("/", 1)[-1]
            content = (blobs or {}).get(sha)
            if content is None:
                raise AssertionError(f"unexpected blob {sha}")
            return json.dumps({"sha": sha, "size": len(content), "encoding": "base64",
                               "content": base64.b64encode(content).decode()}).encode()
        return json.dumps({"sha": tree_sha, "truncated": truncated, "tree": entries}).encode()
    transport.seen = seen
    return transport


class GitHubConnectorTests(unittest.TestCase):
    def connector(self, transport):
        return GitHubRepositoryConnector(lambda: "x" * 24, transport=transport)

    def test_pinned_revision_yields_valid_deterministic_evidence_artifact(self):
        transport = transport_for()
        first = self.connector(transport).snapshot(APPROVAL)
        second = self.connector(transport_for()).snapshot(APPROVAL)
        self.assertEqual(first, second)
        self.assertEqual([item["path"] for item in first["evidence_manifest"]["files"]], ["a.txt", "z.txt"])
        manifest = {key: first["evidence_manifest"][key] for key in ("tree_sha", "files")}
        self.assertEqual(first["evidence_manifest"]["content_hash"], hashlib.sha256(json.dumps(manifest, sort_keys=True, separators=(",", ":")).encode()).hexdigest())
        self.assertEqual(len(transport.seen), 2)
        self.assertTrue(all(request.full_url.startswith("https://api.github.com/") for request in transport.seen))
        self.assertTrue(all(request.get_header("Authorization") == "Bearer " + "x" * 24 for request in transport.seen))

    def test_empty_pinned_repository_remains_valid_evidence(self):
        snapshot = self.connector(transport_for(entries=[])).snapshot(APPROVAL)
        self.assertEqual(snapshot["evidence_manifest"]["files"], [])

    def test_refuses_commit_sha_that_does_not_match_pinned_approval(self):
        with self.assertRaisesRegex(GitHubConnectorError, "does not match"):
            self.connector(transport_for(commit_sha="e" * 40)).snapshot(APPROVAL)

    def test_refuses_incomplete_tree_or_unsafe_evidence_path(self):
        with self.assertRaisesRegex(GitHubConnectorError, "incomplete"):
            self.connector(transport_for(truncated=True)).snapshot(APPROVAL)
        unsafe = [{"path": "../secret", "type": "blob", "sha": BLOB_A, "size": 1}]
        with self.assertRaisesRegex(GitHubConnectorError, "unsafe"):
            self.connector(transport_for(entries=unsafe)).snapshot(APPROVAL)

    def test_refuses_bad_approval_token_and_base(self):
        with self.assertRaisesRegex(GitHubConnectorError, "not approved"):
            self.connector(transport_for()).snapshot({**APPROVAL, "approval": {**APPROVAL["approval"], "status": "PENDING"}})
        with self.assertRaisesRegex(GitHubConnectorError, "token"):
            GitHubRepositoryConnector(lambda: "short", transport=transport_for()).snapshot(APPROVAL)
        with self.assertRaisesRegex(GitHubConnectorError, "base"):
            GitHubRepositoryConnector(lambda: "x" * 24, api_base="http://api.github.com")

    def test_artifact_validation_refuses_manifest_hash_tampering(self):
        from deploygrade.engine.contracts import validate_artifact
        snapshot = self.connector(transport_for()).snapshot(APPROVAL)
        snapshot["evidence_manifest"]["files"][0]["size"] += 1
        with self.assertRaisesRegex(ValueError, "manifest hash"):
            validate_artifact(snapshot)

    def test_ephemeral_content_evidence_is_redacted_bounded_and_deterministic(self):
        entries = [
            {"path": "rollback.sh", "type": "blob", "sha": BLOB_A, "size": 30},
            {"path": "tests/test_ready.py", "type": "blob", "sha": BLOB_B, "size": 24},
            {"path": "README.md", "type": "blob", "sha": "d" * 40, "size": 999},
        ]
        blobs = {BLOB_A: b"#!/bin/sh\nset -e\ngit revert x\n", BLOB_B: b"def test_x():\n assert x\n"}
        connector = self.connector(transport_for(entries=entries, blobs=blobs))
        evidence = connector.content_evidence(connector.snapshot(APPROVAL))
        self.assertEqual([item["path"] for item in evidence["examined_blobs"]], ["rollback.sh", "tests/test_ready.py"])
        self.assertEqual([item["category"] for item in evidence["findings"]], ["rollback", "tests"])
        rendered = json.dumps(evidence)
        self.assertNotIn("git revert x", rendered)
        self.assertNotIn("def test_x", rendered)
        self.assertEqual(evidence["policy"]["source_retention"], "NONE")

    def test_content_evidence_refuses_binary_or_size_mismatch_and_tampering(self):
        entries = [{"path": "policy.json", "type": "blob", "sha": BLOB_A, "size": 2}]
        snapshot = self.connector(transport_for(entries=entries, blobs={BLOB_A: b"\xff\x00"})).snapshot(APPROVAL)
        with self.assertRaisesRegex(GitHubConnectorError, "UTF-8"):
            self.connector(transport_for(entries=entries, blobs={BLOB_A: b"\xff\x00"})).content_evidence(snapshot)
        evidence = self.connector(transport_for(entries=entries, blobs={BLOB_A: b"{}"})).content_evidence(snapshot)
        evidence["examined_blobs"][0]["content_sha256"] = "0" * 64
        from deploygrade.engine.contracts import validate_artifact
        with self.assertRaisesRegex(ValueError, "bound|hash"):
            validate_artifact(evidence)
