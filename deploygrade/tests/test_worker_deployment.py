import os
import unittest
from pathlib import Path

from deploygrade.worker.service import _require_runtime_config

ROOT = Path(__file__).resolve().parents[2]


class WorkerDeploymentTests(unittest.TestCase):
    def test_runtime_requires_pinned_image_and_real_secret(self):
        with self.assertRaises(RuntimeError):
            _require_runtime_config({})
        config = _require_runtime_config({
            "DEPLOYGRADE_WORKER_AUTH_TOKEN": "a" * 32,
            "DEPLOYGRADE_WORKER_IMAGE_DIGEST": "sha256:" + "a" * 64,
            "DEPLOYGRADE_WORKER_POLICY_VERSION": "worker-policy-v1",
        })
        self.assertEqual(config["policy_version"], "worker-policy-v1")

    def test_container_hardening_assets_fail_closed(self):
        dockerfile = (ROOT / "deploygrade/worker/Dockerfile").read_text()
        compose = (ROOT / "deploygrade/deployment/worker/compose.yaml").read_text()
        kubernetes = (ROOT / "deploygrade/deployment/worker/kubernetes.yaml").read_text()
        self.assertIn("USER 10001:10001", dockerfile)
        self.assertIn("read_only: true", compose)
        self.assertIn("no-new-privileges:true", compose)
        self.assertIn('cap_drop: ["ALL"]', compose)
        self.assertIn("pids_limit: 64", compose)
        self.assertIn("internal: true", compose)
        self.assertIn("ports: []", compose)
        self.assertIn("automountServiceAccountToken: false", kubernetes)
        self.assertIn("readOnlyRootFilesystem: true", kubernetes)
        self.assertIn("allowPrivilegeEscalation: false", kubernetes)
        self.assertIn("policyTypes: [Ingress, Egress]", kubernetes)
        self.assertIn("egress: []", kubernetes)

    def test_service_never_uses_subprocess_or_shell(self):
        service = (ROOT / "deploygrade/worker/service.py").read_text()
        self.assertNotIn("subprocess", service)
        self.assertNotIn("os.system", service)
        self.assertIn("PILOT", service)
        self.assertIn("worker_runtime import run", service)


if __name__ == "__main__":
    unittest.main()
