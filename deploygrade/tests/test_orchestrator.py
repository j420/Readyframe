import tempfile
import unittest
from pathlib import Path

from deploygrade.engine.audit_log import verify
from deploygrade.engine.orchestrator import dry_run, run_handoff, _fixture


class OrchestratorTests(unittest.TestCase):
    def test_dry_run_audits_all_ten_handoffs(self):
        with tempfile.TemporaryDirectory() as directory:
            log = Path(directory) / "audit.jsonl"
            entries = dry_run(log, "deploygrade/knowledge/customer-memory.json", "1970-01-01T00:00:00Z")
            self.assertEqual(len(entries), 10)
            self.assertEqual([entry["phase"] for entry in entries], ["discovery", "readiness", "blueprint", "pilot", "scale", "portfolio", "risk", "strategic", "replay", "cross_customer"])
            self.assertEqual(entries[3]["human_approvals"], ["approval://human/pilot-owner"])
            self.assertEqual(verify(log), entries)

    def test_tampered_input_is_rejected_against_previous_output_hash(self):
        with tempfile.TemporaryDirectory() as directory:
            log = Path(directory) / "audit.jsonl"
            dry_run(log, "deploygrade/knowledge/customer-memory.json", "1970-01-01T00:00:00Z")
            tampered = _fixture("rubric.json")
            tampered["rubric_version"] = "tampered"
            with self.assertRaisesRegex(ValueError, "handoff integrity failure"):
                run_handoff(log, phase="post_tamper", inputs=tampered, outputs=_fixture("alert.json"), timestamp="1970-01-01T00:00:00Z")

    def test_audit_log_mutation_is_detected(self):
        with tempfile.TemporaryDirectory() as directory:
            log = Path(directory) / "audit.jsonl"
            dry_run(log, "deploygrade/knowledge/customer-memory.json", "1970-01-01T00:00:00Z")
            lines = log.read_text().splitlines()
            lines[4] = lines[4].replace('"phase":"scale"', '"phase":"fraud"')
            log.write_text("\n".join(lines) + "\n")
            with self.assertRaisesRegex(ValueError, "audit log integrity failure"):
                verify(log)

    def test_existing_audit_log_is_not_reset(self):
        with tempfile.TemporaryDirectory() as directory:
            log = Path(directory) / "audit.jsonl"
            dry_run(log, "deploygrade/knowledge/customer-memory.json", "1970-01-01T00:00:00Z")
            with self.assertRaisesRegex(ValueError, "append-only"):
                dry_run(log, "deploygrade/knowledge/customer-memory.json", "1970-01-01T00:00:00Z")
