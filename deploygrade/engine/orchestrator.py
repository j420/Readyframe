"""Goal-mode orchestration: schema-validated handoffs with append-only audit output."""
import argparse
import json
from pathlib import Path

from deploygrade.engine.audit_log import append_handoff, canonical_hash, verify
from deploygrade.engine.score import score_readiness
from deploygrade.hooks.session_start import load_customer_memory
from deploygrade.hooks.session_stop import validate_before_advance

ROOT = Path(__file__).parents[2]
FIXTURES = ROOT / "deploygrade" / "fixtures"
PHASES = (
    ("discovery", "deployment_inventory.json"),
    ("readiness", None),
    ("blueprint", "rollout_blueprint.json"),
    ("pilot", "pilot_scorecard.json"),
    ("scale", "scaling_decision.json"),
    ("portfolio", "portfolio_view.json"),
    ("risk", "alert.json"),
    ("strategic", "investigation_report.json"),
    ("replay", "outcome_record.json"),
    ("cross_customer", "rubric.json"),
)


def _fixture(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text())


def _rubric_version(output: dict) -> str:
    return output.get("rubric_version", output.get("score", {}).get("rubric_version", "2026.07.0"))


def run_handoff(log_path: str | Path, *, phase: str, inputs: dict, outputs: dict,
                timestamp: str, human_approvals: list[str] | None = None) -> dict:
    """Verify predecessor hash, validate output at Stop, then append immutable evidence."""
    records = verify(log_path)
    if records and canonical_hash(inputs) != records[-1]["outputs_hash"]:
        raise ValueError("handoff integrity failure: input artifact hash differs from preceding audited output")
    validate_before_advance(outputs)
    return append_handoff(log_path, phase=phase, inputs=inputs, outputs=outputs,
                          rubric_version=_rubric_version(outputs),
                          human_approvals=human_approvals or [], timestamp=timestamp)


def dry_run(log_path: str | Path, memory_path: str | Path, timestamp: str) -> list[dict]:
    """Run all ten declared handoffs using fixtures and return the first-class audit log."""
    path = Path(log_path)
    if path.exists():
        raise ValueError("audit log already exists; append-only session logs cannot be reset")
    current = load_customer_memory(memory_path)
    for phase, fixture_name in PHASES:
        output = score_readiness(_fixture("readiness-input.json")) if phase == "readiness" else _fixture(fixture_name)
        approvals = ["approval://human/pilot-owner"] if phase == "pilot" else []
        run_handoff(path, phase=phase, inputs=current, outputs=output, timestamp=timestamp, human_approvals=approvals)
        current = output
    return verify(path)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=["dry-run"])
    parser.add_argument("--audit-log", default="deploygrade/runtime/dry-run.audit.jsonl")
    parser.add_argument("--customer-memory", default="deploygrade/knowledge/customer-memory.json")
    parser.add_argument("--timestamp", default="1970-01-01T00:00:00Z")
    args = parser.parse_args()
    records = dry_run(args.audit_log, args.customer_memory, args.timestamp)
    print(json.dumps(records, sort_keys=True))


if __name__ == "__main__":
    main()
