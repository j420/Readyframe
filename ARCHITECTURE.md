# DeployGrade architecture

`discovery → deployment_inventory → readiness_score → rollout_blueprint → pilot_scorecard → scaling_decision → outcome_record` is the per-engagement flow. The readiness score is the spine: every gate and recommendation traces back to a sub-score, control, evidence, confidence, and rubric version.

The cross-portfolio flow is isolated: anonymized, quality-gated outcome records → holdout-validated per-vertical refit → immutable rubric version. No vertical changes another vertical's weights. The audit spine is the append-only hash chain at every handoff: phase, input/output hashes, rubric version, approvals, timestamp.
