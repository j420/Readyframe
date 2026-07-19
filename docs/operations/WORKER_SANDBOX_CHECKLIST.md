# Worker sandbox deployment checklist

The worker is a separate execution boundary. A JSON worker-dispatch artifact is
not by itself isolation; all controls below must be enforced by the runtime.

## Preflight

- [ ] Separate cloud account/project, network boundary, and service identity from Vercel.
- [ ] Approved repository connector, repository identity, immutable revision, and human-approved blueprint hash are persisted.
- [ ] Short-lived repository credentials are scoped to the single repository and operation.
- [ ] Credential references, not raw tokens, are passed through dispatch artifacts.
- [ ] Worker image digest, dependency lock, and policy version are recorded.

## Runtime enforcement

- [ ] Read-only filesystem for Discovery; write access only for approved Pilot workspace paths.
- [ ] Default-deny network egress with explicit allowlist only where a blueprint permits it.
- [ ] No host Docker socket, privileged containers, shared credentials, or shell escape paths.
- [ ] CPU, memory, wall-time, process-count, disk, and output limits are enforced.
- [ ] Secrets are injected just-in-time, scoped, redacted from logs, and revoked after the job.
- [ ] Every tool action passes the deny gate before execution.
- [ ] Worker emits signed status/telemetry events with event ID, dispatch hash, and UTC timestamp.

## Failure behavior

- [ ] Worker crash, lost callback acknowledgement, telemetry gap, policy violation, or unknown repository state marks the Pilot `PAUSED`.
- [ ] A breach after landed work performs a compensating `git revert` in the approved sandbox, records the rollback event, then requires human escalation.
- [ ] The worker never reports an operation as "undo" and never resumes from an untrusted event.
- [ ] Operators can correlate worker image digest, dispatch hash, artifact hash, job ID, and callback event ID.

## Release test

Before enabling a worker image, execute a controlled test that proves: blocked
network egress; rejected path traversal; rejected unapproved revision; denied
dangerous tool action; durable callback replay rejection; and pause/escalation
on simulated worker failure.
