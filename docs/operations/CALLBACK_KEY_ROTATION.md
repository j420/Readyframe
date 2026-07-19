# Pilot callback key rotation and incident runbook

## Rotation cadence

Rotate every worker callback signing key at least every 90 days, after worker
replacement, and immediately upon suspected disclosure. Keys are route-specific:
never reuse `PILOT_CALLBACK_SECRET`, worker callback secrets, or authentication
secrets.

## Planned rotation

1. Create a new random key in the secret manager; label it with route ID,
   creation time, and expiry. Do not log the key.
2. Add a second trusted callback route authorization pinned to the same
   organization, Pilot job, and blueprint hash, but with the new route/key.
3. Deploy the worker configuration referencing only the new route.
4. Send a signed test event with a new event ID. Verify durable acceptance,
   tenant/job/blueprint binding, and replay rejection.
5. Disable the old route/key after the delivery window expires.
6. Record key IDs (not values), route IDs, operator, time, and verification
   evidence in the audit log.

## Suspected key compromise

1. Immediately disable the affected callback route and pause its Pilot job.
2. Reject all new callbacks for that route; do not rely on in-memory replay
   caches as an incident control.
3. Create a new route/key and redeploy the worker through the planned rotation
   flow.
4. Review durable callback events, artifact lineage, and worker logs from the
   suspected exposure window.
5. Escalate to security and the engagement approver. Requalify the Pilot only
   after the investigation confirms exact blueprint/repository lineage.

## Callback validation invariants

A production callback is accepted only when it has a valid HMAC over the raw
body, a unique durable event ID, a fresh canonical UTC timestamp, and exactly
matches the trusted route's organization, Pilot job, and blueprint hash. Any
ambiguity, duplicate, stale event, mismatch, or unknown state must be rejected
and escalated.
