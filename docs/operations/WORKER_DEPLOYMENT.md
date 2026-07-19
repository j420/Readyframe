# Isolated worker deployment boundary

This repository ships a hardened **reference worker service** and deployment
manifests. They are a deployment starting point, not proof that a cloud platform
has isolated a customer workload. The service can only consume a private,
authenticated dispatch and delegates execution semantics to `worker_runtime`.
That runtime continues to deny every `PILOT` before a tool action: do **not** turn
that denial into a feature flag or represent this worker as a live remediation
engine.

## Assets and protections

- `deploygrade/worker/Dockerfile` runs non-root with a pinned base digest and no
  shell entrypoint.
- `deploygrade/deployment/worker/compose.yaml` is a local hardening smoke setup:
  read-only root, memory tmpfs, no capabilities, no-new-privileges, pid/memory/CPU
  limits, no published ports, and an internal-only network.
- `deploygrade/deployment/worker/kubernetes.yaml` applies the equivalent pod
  restrictions and a default-deny ingress/egress NetworkPolicy. It permits only
  a labelled private ingress namespace to call port 8080.
- `deploygrade.worker.service` bounds request bodies, uses a constant-time private
  ingress token comparison, refuses non-JSON input, logs no request content, and
  never invokes a subprocess or SCM client.

## Required operator work before deployment

1. Build the Dockerfile in CI, scan it, sign it, and replace the Kubernetes image
   placeholders with the resulting immutable digest. Pinning in source does not
   attest that a deployed image was built from this checkout.
2. Create a separate worker cloud account/project and namespace. Do not share the
   Vercel service identity, production database credentials, host Docker socket,
   or broad CI credentials.
3. Place a private mTLS gateway or queue between the control plane and worker;
   do not expose port 8080 publicly. Rotate the worker ingress token from the
   secret manager and inject short-lived repository credentials only within a
   separately reviewed connector process.
4. Verify NetworkPolicy enforcement in the selected CNI. Kubernetes manifests
   cannot compensate for a CNI that ignores NetworkPolicy.
5. Run an image admission policy that rejects privileged pods, unpinned images,
   writable roots, added Linux capabilities, hostPath mounts, and service-account
   token mounts.
6. Before accepting `PILOT`, implement and independently review a non-bypassable
   tool adapter. It must apply pre-tool deny checks, enforce target/revision/path
   allowlists, record every action, and compensate landed work with a `git revert`
   followed by pause and human escalation.

## Release acceptance test

Run `python3 -m unittest deploygrade.tests.test_worker_deployment -v` for
repository asset checks. In a real cluster additionally prove: no public route;
blocked egress; rejected path traversal; no host mounts/capabilities; rejected
unapproved revision; durable callback replay denial; and pause/escalation after a
simulated worker crash. Record those external results in production release
evidence; local passing tests are not deployment evidence.
