# DeployGrade Product Vision and Build Guardrails

## The product

**DeployGrade is FICO for AI-agent deployment.** It produces a portable, vendor-neutral, explainable 0–1000 Deployment Readiness Score, runs a gated rollout with honest live rollback, and compounds validated outcomes into transparent per-vertical rubric improvements.

The product is **not** a generic agent chain, a score dashboard, a certification, or an LLM that invents risk numbers. The ten agents are the execution substrate; the durable Readiness Score and the cross-customer flywheel are the category-defining assets.

## Product spine

```text
Discovery → DeploymentInventory → ReadinessScore(vN) → RolloutBlueprint
→ PilotScorecard + RollbackEvent → ScalingDecision → OutcomeRecord
→ deterministic vertical rubric refit → Rubric(vN+1) → re-score
```

Every arrow is a schema-valid JSON artifact. Every downstream artifact retains the exact upstream score/rubric/audit reference that produced it.

## Non-negotiable responsibilities

| Phase | Agent role | Deterministic role |
| --- | --- | --- |
| Discovery (1) | Explore approved, read-only evidence sources; identify ambiguity and gaps. | Validate the inventory and evidence contract. |
| Readiness (2) | Explain results and request missing evidence. | Load immutable rubric data; calculate score, confidence, bands, evidence, and counterfactuals. |
| Blueprint (3) | Propose a low-blast-radius rollout plan. | Clamp autonomy, budgets, approvals, and rollback rules from score/policy inputs. |
| Pilot (4) | Act only in the approved sandbox and interpret observations. | Deny before unsafe execution; pause/escalate on breach; compensate landed work with a recorded revert. |
| Scale (5) | Explain a human-ratified Go/Hold/No-Go recommendation. | Compute metrics and enforce policy thresholds. |
| Portfolio/Risk (6–7) | Prioritize attention and investigate anomalies. | Aggregate validated, tenant-scoped telemetry. |
| Replay (8) | Explain a failure trace and recommended remediation. | Verify hashes and replay deterministic evidence. |
| Flywheel (9) | Select eligible anonymized outcomes and explain conclusions. | Refit weights, holdout-validate, publish immutable rubric artifacts, and re-score. |
| Strategic (10) | Propose reusable standards/templates. | Publish only human-approved, versioned artifacts. |

## Critical safety and honesty rules

1. LLMs may reason, explore, explain, and propose. They must never invent scores, thresholds, weights, confidence intervals, approval outcomes, or rollback decisions.
2. A score must be calculated solely from a checked-in/persisted immutable rubric artifact identified by version **and content hash**.
3. A Flywheel result is real only when it has: accepted anonymized corpus, deterministic train/holdout split, holdout improvement gate, immutable `rubric-vN+1` artifact, rubric diff, and an actual re-score using that new artifact. Never script or claim a fabricated score movement.
4. Pilot rollback is never “undo.” It is a PreToolUse deny before a dangerous action plus a compensating revert for landed work, followed by pause and human escalation.
5. Every public API response must itself validate against a checked-in schema. Every user-facing number at an API boundary has exactly `{value, confidence, evidence_uris, rubric_version}`.
6. Customer code/evidence remains per-engagement and tenant-isolated. Only anonymized, quality-gated structured outcome records may cross into the flywheel.
7. On ambiguity, missing evidence, policy breach, failed validation, weak holdout result, or unknown infrastructure state: fail closed, pause, and escalate.

## Build Week implementation priority

Build **live and real** in this order:

1. Discovery on approved real repositories/connectors.
2. Deterministic Readiness Score under a versioned rubric.
3. Blueprint whose weak sub-scores visibly create tighter gates.
4. Controlled Pilot with live deny gate and compensating rollback.
5. Cross-customer deterministic refit that publishes a rubric and visibly re-scores another engagement.

Agents 5–8 and 10 can use realistic seeded artifacts when necessary, but must never pretend a scripted artifact is a live system result.

## Vercel architecture

Vercel hosts the operator-facing application and control plane: UI, authenticated APIs, workflow controls, approvals, audit/replay views, portfolio, and demo presentation. A separately isolated worker/sandbox runs repository scanning, Pilot actions, telemetry collection, and compensating reverts. Vercel must not be represented as directly executing uncontrolled customer repository operations.

## Before declaring work complete

- Trace the change to this vision and identify which phase/artifact it affects.
- Add schema, determinism, end-to-end, and adversarial tests appropriate to that phase.
- Verify no numeric decision or artifact boundary bypasses the rules above.
- Do not claim Vercel production readiness without a successful Vercel build/preview and deployed endpoint verification.
