# DeployGrade production deployment runbook

DeployGrade is a readiness signal, **not certification**. Do not label a release
production-ready until every item in this runbook is completed and recorded in
the engagement audit.

## 1. Provision and isolate services

1. Deploy the Vercel operator UI/API separately from the worker runtime.
2. Provision the production control-plane datastore with tenant isolation. The
   checked-in Supabase migration is the required starting point:
   `supabase/migrations/0001_deploygrade_core.sql`.
3. Deploy the worker into a separate account/project/network boundary. Vercel
   must never scan customer repositories or execute Pilot actions directly.
4. Create one least-privilege service identity per component: Vercel API,
   control plane, each worker, and each SCM connector.
5. Configure encrypted secrets in the platform secret manager. Do not commit
   `.env`, raw tokens, database URLs containing credentials, or callback keys.

## 2. Configure before promotion

1. Copy `.env.example` into the deployment platform's secret/configuration UI.
2. Set `DEPLOYGRADE_ENVIRONMENT=production` and non-placeholder values.
3. Run the fail-closed configuration check in the exact release environment:

   ```sh
   DEPLOYGRADE_ENVIRONMENT=production python3 -m deploygrade.harness.verify_runtime_config
   ```

4. Ensure `DEPLOYGRADE_AUTH_SECRET` and every `DEPLOYGRADE_PILOT_CALLBACK_ROUTES`
   signing secret are independent, random, at least 32 characters, and stored
   server-side only. `PILOT_CALLBACK_SECRET` is development/test-only and is
   rejected by production callback ingress.
5. Apply the Supabase migration and confirm RLS prevents cross-tenant reads and
   writes. Record the migration version and the validation result.
6. Configure a durable callback authorization route for each Pilot job. Pin its
   organization, Pilot job ID, exact blueprint hash, route ID, and callback key.
   A callback body must not choose any of those values.

## 3. Build and verification gate

Run these checks from the exact release commit:

```sh
make bootstrap
make verify
make redteam
make verify-static-site
```

Deploy a Vercel preview. Set `DEPLOYGRADE_DEPLOYED_URL` to its HTTPS origin and
validate the live contract:

```sh
DEPLOYGRADE_DEPLOYED_URL=https://preview.example.com make verify-deployed
```

Promote only if all commands pass and an operator records the preview URL,
commit SHA, rubric manifest hash, and approver in the deployment audit.

For a production promotion, create a private release-evidence JSON artifact using
`production_release_evidence.schema.json`. It must record the exact release
commit, managed Postgres backend/migration, isolated worker image digest and
endpoint, deployed origin, and accountable verifier. Validate it from the exact
release checkout with `DEPLOYGRADE_RELEASE_EVIDENCE_FILE=/secure/path/release.json make verify-release-evidence`.

## 4. Post-deploy smoke test

1. Authenticate as two separate organizations and verify one cannot read or
   mutate the other's engagement/artifacts/jobs.
2. Store a schema-valid inventory, score it, compile a blueprint, and approve
   that exact blueprint hash.
3. Dispatch only to the separately isolated worker using a pinned repository
   revision and approved connector identity.
4. Send one valid signed worker callback and verify durable persistence.
5. Replay the same event; it must be rejected.
6. Trigger a breach/rollback event; the job must pause and require human
   escalation. A compensating `git revert` must be recorded as compensation,
   never represented as undo.
7. Confirm logs correlate organization, engagement, artifact hash, Pilot job,
   dispatch, and callback event IDs without exposing secret values.

## 5. Rollback and unknown state

If Vercel, database, worker, callback delivery, or repository state is unknown:

1. Stop dispatching new work.
2. Mark affected Pilot jobs `PAUSED` and notify the human approver.
3. Preserve artifacts and logs; do not rewrite audit history.
4. If work landed, use a compensating revert through the approved worker path.
5. Reconcile durable job/event state before requalification. Never resume from a
   stale callback or an inferred state.

See `CALLBACK_KEY_ROTATION.md` and `WORKER_SANDBOX_CHECKLIST.md` for the
required incident procedures and runtime boundaries.
