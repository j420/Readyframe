# Schema migration policy

Every schema declares a version (`schema_version` for artifact contracts and `x-schema-version` for schema metadata). Artifacts retain their `$schema` URI permanently: consumers use that URI to select the appropriate validator rather than silently coercing historic data.

`readiness_score.v1.schema.json` is retained for previously stored v1 artifacts. New producers emit `readiness_score.schema.json` at schema version `2.0`; v2 adds confidence bounds and drivers, actionable counterfactuals, a signed audit envelope, and semantic consistency checks. Consumers must load v1 unchanged, while any explicit conversion to v2 must be a separately audit-logged transform.
