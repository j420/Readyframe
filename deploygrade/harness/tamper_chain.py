"""Adversarial proof that a mid-chain artifact mutation cannot advance."""
import tempfile
from pathlib import Path
from deploygrade.engine.orchestrator import dry_run, run_handoff, _fixture

with tempfile.TemporaryDirectory() as directory:
    log = Path(directory) / "audit.jsonl"
    dry_run(log, "deploygrade/knowledge/customer-memory.json", "1970-01-01T00:00:00Z")
    tampered = _fixture("rubric.json")
    tampered["rubric_version"] = "tampered"
    try:
        run_handoff(log, phase="post_tamper", inputs=tampered, outputs=_fixture("alert.json"), timestamp="1970-01-01T00:00:00Z")
    except ValueError as error:
        if "handoff integrity failure" not in str(error):
            raise
        print(f"tamper detection: PASS — {error}")
    else:
        raise SystemExit("tamper detection: FAILURE — altered artifact advanced")
