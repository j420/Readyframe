# DeployGrade Enforced Engineering Rules

## Scope and purpose
This repository builds DeployGrade: a portable, explainable, vendor-neutral readiness signal, **not certification**. Every change must preserve trust, honesty, and safe compounding.

## ENGINEERING LAWS (M0 — verbatim)
- Determinism: scores, thresholds, and re-fits are pure functions of (inputs + rubric_version). Same inputs → identical output, always. LLM reasoning is for prose/judgment only, never for a number that must be reproducible.
- Contracts first: nothing flows between phases except JSON that validates against its schema.
- Explainability is an output, not a comment: if you compute something a user relies on, you also emit the evidence, the confidence, and the counterfactual.
- Safety is fail-closed: on ambiguity or breach, pause and escalate to a human; never proceed silently.
- Adversarial by default: after you build anything, try to break it before I do.

## Enforced rules
1. Every user-facing number **must** carry exactly this metadata shape at its API boundary: `{value, confidence, evidence_uris, rubric_version}`. `value` alone is prohibited.
2. All phase artifacts are JSON documents with a `$schema` URI resolving to a checked-in file in `deploygrade/schemas/`; validate them before consuming or producing them.
3. A score path must emit evidence, confidence, and a counterfactual, and must use only versioned rubric inputs for numeric calculations.
4. Safety gates deny before execution on ambiguity or breach; compensating reverts must never be represented as undo.
5. The pre-commit hook is mandatory. It rejects staged scoring paths without a staged determinism test and rejects staged JSON artifacts that lack a valid `$schema` reference. Install it with `make bootstrap`.
6. Before claiming a task complete, run its adversarial check and record the result in the verification output.
