# DeployGrade on Vercel

## Supported deployment boundary

The Vercel deployment is the static **trust-surface demo** only. It serves the checked-in dashboard and deterministic example artifacts from `deploygrade/sites/dashboard`; no Python engine, pilot controller, customer audit log, or knowledge corpus is exposed publicly.

`vercel.json` sets that directory as the output and applies browser safety headers. The dashboard has no build step, server-side route, secret, dependency installation, or external runtime call. Its assets and JSON artifacts are relative paths, so preview and production deployments use the same origin.

## Deploy

1. Import this repository into Vercel.
2. Leave the build command empty. The checked-in `vercel.json` selects the output directory.
3. Deploy the default branch to production; use Vercel preview deployments for pull requests.
4. Run `make verify` and `make redteam` before promoting a commit.

## Honest production limits

- `evidence://` and `audit://` links in the demo are opaque identifiers, not public web URLs. They intentionally cannot resolve on a public Vercel deployment. A customer product needs an authenticated evidence/audit resolver before replacing these demo artifacts with real engagement data.
- Vercel does not execute the local Python scoring, pilot, replay, or flywheel modules in this configuration. Run those controls in a customer-controlled CI runner or expose a separately authenticated API only after its threat model is reviewed.
- Do not commit customer artifacts, audit logs, or outcome records into `deploygrade/sites/dashboard`; a Vercel static deployment is public by default.

## Compatibility check

```sh
python3 -m unittest deploygrade.tests.test_vercel -v
```

The check verifies the configured output exists, every static browser asset is present, and the security headers retain the dashboard's required same-origin scripts, JSON fetches, and inline meter style.
