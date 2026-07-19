-- Server-side DeployGrade control-plane tables.  These use text IDs because
-- authenticated OIDC organization/engagement identifiers are opaque strings,
-- not client-selectable UUIDs.  Apply after 0001; the legacy tables remain for
-- analytics migrations and are never used by the service adapter.
create schema if not exists deploygrade;

create table if not exists deploygrade.organizations (id text primary key, created_at timestamptz not null default now());
create table if not exists deploygrade.engagements (id text primary key, organization_id text not null references deploygrade.organizations(id) on delete cascade, vertical text not null, created_at timestamptz not null default now());
create table if not exists deploygrade.artifacts (hash text primary key, organization_id text not null references deploygrade.organizations(id) on delete cascade, engagement_id text not null references deploygrade.engagements(id) on delete cascade, schema_uri text not null, payload jsonb not null, created_at timestamptz not null default now());
create table if not exists deploygrade.approvals (id text primary key, organization_id text not null references deploygrade.organizations(id) on delete cascade, engagement_id text not null references deploygrade.engagements(id) on delete cascade, artifact_hash text not null references deploygrade.artifacts(hash), decision text not null check (decision in ('APPROVED','REJECTED')), approved_by text not null, created_at timestamptz not null default now());
create table if not exists deploygrade.pilot_jobs (id text primary key, organization_id text not null references deploygrade.organizations(id) on delete cascade, engagement_id text not null references deploygrade.engagements(id) on delete cascade, blueprint_hash text not null references deploygrade.artifacts(hash), approval_id text not null references deploygrade.approvals(id), sandbox_repository text not null, status text not null check (status in ('QUEUED','RUNNING','PAUSED','REVERTED','COMPLETE','FAILED')), created_at timestamptz not null default now());
create table if not exists deploygrade.pilot_events (event_id text primary key, organization_id text not null references deploygrade.organizations(id) on delete cascade, pilot_job_id text not null references deploygrade.pilot_jobs(id) on delete cascade, blueprint_hash text not null, event_type text not null check (event_type in ('PILOT_STARTED','ACTION_DENIED','METRIC_RECORDED','THRESHOLD_BREACHED','ROLLBACK_FIRED','COMPENSATING_REVERTED','PILOT_PAUSED')), payload jsonb not null, created_at timestamptz not null default now());
create table if not exists deploygrade.callback_authorizations (route_id text primary key, organization_id text not null references deploygrade.organizations(id) on delete cascade, pilot_job_id text not null references deploygrade.pilot_jobs(id) on delete cascade, blueprint_hash text not null, signing_secret text not null, expires_at timestamptz not null, revoked_at timestamptz);

create index if not exists deploygrade_engagement_organization_idx on deploygrade.engagements(organization_id);
create index if not exists deploygrade_artifact_tenant_idx on deploygrade.artifacts(organization_id, engagement_id);
create index if not exists deploygrade_job_tenant_idx on deploygrade.pilot_jobs(organization_id, id);

-- The application role must be NOSUPERUSER and NOBYPASSRLS.  Each adapter
-- transaction executes set_config('app.organization_id', org, true).
alter table deploygrade.organizations enable row level security;
alter table deploygrade.organizations force row level security;
alter table deploygrade.engagements enable row level security;
alter table deploygrade.engagements force row level security;
alter table deploygrade.artifacts enable row level security;
alter table deploygrade.artifacts force row level security;
alter table deploygrade.approvals enable row level security;
alter table deploygrade.approvals force row level security;
alter table deploygrade.pilot_jobs enable row level security;
alter table deploygrade.pilot_jobs force row level security;
alter table deploygrade.pilot_events enable row level security;
alter table deploygrade.pilot_events force row level security;
alter table deploygrade.callback_authorizations enable row level security;
alter table deploygrade.callback_authorizations force row level security;

create policy deploygrade_org_isolation on deploygrade.organizations for all using (id = current_setting('app.organization_id', true)) with check (id = current_setting('app.organization_id', true));
create policy deploygrade_engagement_isolation on deploygrade.engagements for all using (organization_id = current_setting('app.organization_id', true)) with check (organization_id = current_setting('app.organization_id', true));
create policy deploygrade_artifact_isolation on deploygrade.artifacts for all using (organization_id = current_setting('app.organization_id', true)) with check (organization_id = current_setting('app.organization_id', true));
create policy deploygrade_approval_isolation on deploygrade.approvals for all using (organization_id = current_setting('app.organization_id', true)) with check (organization_id = current_setting('app.organization_id', true));
create policy deploygrade_job_isolation on deploygrade.pilot_jobs for all using (organization_id = current_setting('app.organization_id', true)) with check (organization_id = current_setting('app.organization_id', true));
create policy deploygrade_event_isolation on deploygrade.pilot_events for all using (organization_id = current_setting('app.organization_id', true)) with check (organization_id = current_setting('app.organization_id', true));
create policy deploygrade_callback_isolation on deploygrade.callback_authorizations for all using (organization_id = current_setting('app.organization_id', true)) with check (organization_id = current_setting('app.organization_id', true));

-- Callback ingress has only an opaque route id.  This security-definer function
-- exposes exactly one active route and is used only to establish RLS context.
create or replace function deploygrade.active_callback_authorization(requested_route_id text)
returns table(route_id text, organization_id text, pilot_job_id text, blueprint_hash text, signing_secret text, expires_at timestamptz)
language sql security definer set search_path = deploygrade, pg_temp as $$
  select c.route_id, c.organization_id, c.pilot_job_id, c.blueprint_hash, c.signing_secret, c.expires_at
  from deploygrade.callback_authorizations c
  where c.route_id = requested_route_id and c.revoked_at is null and c.expires_at > now()
$$;
revoke all on function deploygrade.active_callback_authorization(text) from public;
-- Grant this function and table privileges only to the dedicated NOBYPASSRLS
-- application role during environment provisioning; never grant it to browser roles.
