# User-facing number explainability coverage

| Surface number | Evidence | Confidence | Counterfactual/action | Audit |
|---|---|---|---|---|
| Readiness score | evidence URIs | score confidence + interval | counterfactual checklist | signed audit envelope |
| Readiness sub-score | evidence URI + control | evidence quality | parent counterfactual | parent audit |
| Goal token budget | evidence URIs | budget confidence | policy override (tighten only) | source readiness audit |
| Predicted gain / risk delta | pilot metric URIs | recommendation confidence | what-would-change-my-mind | scaling artifact contract |
| Portfolio risk / velocity | tile evidence URI | tile confidence | tile action | tile audit record |

## Gap fixed

Portfolio risk and velocity previously displayed evidence and action but omitted confidence and audit linkage. `portfolio.json` now requires each seeded tile to carry `confidence`, `counterfactual`, and `audit_record`; the dashboard can render those fields without inventing explanation.
