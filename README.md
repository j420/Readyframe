# DeployGrade

**DeployGrade is FICO for AI-agent deployment: a portable, explainable readiness signal with gated rollout—not certification.**

## Three novel mechanisms

1. **Trust spine:** deterministic score, confidence bounds, evidence, counterfactual, and hash-chained audit. **Codex primitives:** Goal mode orchestration, Sites dashboard, Programmatic Tool Calling for Discovery scans.
2. **Honest safety:** a PreToolUse deny-gate blocks risky execution; a compensating controller uses `git revert` only after landing. **Codex primitives:** PreToolUse hook, workspace-scoped Pilot subagent, Skills.
3. **Compounding without opacity:** quality-gated anonymized outcomes re-fit transparent per-vertical weights with holdout validation. **Codex primitives:** Cloud-task Flywheel with deterministic local fallback, subagents, Skills.

Feedback session ID: `/feedback`.

Codex accelerated the build by parallelizing evidence collection, wiring schema contracts, generating deterministic harnesses, and repeatedly red-teaming the hero path—not by inventing numeric decisions.

## WHY THIS IS OUTSTANDING, NOT JUST NOVEL

| Judging criterion | Concrete feature | Buyer objection defeated |
|---|---|---|
| Trust | Confidence interval, evidence URIs, signed audit | “This score looks made up.” |
| Honesty | Deny-gate, revert semantics, transparent refusal | “Can it really stop before damage?” |
| Compounding moat | Validated corpus and network-value readout | “A weekend clone can copy this.” |
| Operator value | Counterfactual checklist and risk portfolio | “Is this actionable or a vanity wall?” |

A hostile judge should find no magic claim here: scores are code, not prose; rollback is compensation, not undo; the open Standard is copyable, while the quality-gated accumulated outcome corpus is not.

## Run

```sh
make demo
make verify
make redteam
```
