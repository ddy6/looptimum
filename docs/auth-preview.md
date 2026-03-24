# Auth Preview

This page documents the preview-only auth, RBAC, and OIDC posture for the
local `service/` API and `/dashboard` UI.

It does not change the file-backed runtime authority: campaign state, trial
artifacts, and CLI flows remain local and authoritative under the registered
campaign root.

## Scope Boundary

- preview only: this surface is not part of the stable `v0.3.x`
  compatibility guarantee
- service-scoped only: auth applies to the preview API and dashboard, not to
  direct CLI/runtime usage inside a campaign root
- disabled by default: you must opt in at both the service config layer and
  the campaign-root feature-flag layer
- local-first: audit events are written under `service_state/`, separate from
  campaign runtime logs
- no hosted-control-plane claim: this is a local preview auth surface for the
  preview service stack

## Startup

Local-dev bootstrap mode is HTTP Basic with static users configured through
service env vars.

Example:

```bash
LOOPTIMUM_SERVICE_REGISTRY_FILE=service_state/campaign_registry.json \
LOOPTIMUM_SERVICE_AUTH_MODE=basic \
LOOPTIMUM_SERVICE_AUTH_USERS='[
  {"username":"viewer","password":"viewer-secret","role":"viewer"},
  {"username":"operator","password":"operator-secret","role":"operator"},
  {"username":"admin","password":"admin-secret","role":"admin"}
]' \
python -m uvicorn service.app:create_app --factory
```

Campaign roots must opt in before they can be used behind auth-protected
preview routes:

```json
{
  "feature_flags": {
    "enable_service_api_preview": true,
    "enable_dashboard_preview": true,
    "enable_auth_preview": true
  }
}
```

Notes:

- `enable_service_api_preview = true` is still required for campaign
  registration and any preview API usage
- `enable_dashboard_preview = true` is additionally required for
  `/dashboard/campaigns/{campaign_id}`
- `enable_auth_preview = true` is required only when the service itself is
  running with auth enabled
- `GET /health` stays unauthenticated for local probes even when preview auth
  is enabled

Example read-only request:

```bash
curl -u viewer:viewer-secret http://127.0.0.1:8000/campaigns
```

## Role Matrix

- `viewer`: read-only API routes, dashboard routes, and export endpoints
- `operator`: `viewer` permissions plus `suggest` and `ingest`
- `admin`: `operator` permissions plus campaign registration, `reset`, and
  `restore`

Practical route posture:

- `/health`: unauthenticated
- `/dashboard` and `/dashboard/campaigns/{campaign_id}`: `viewer` or higher
- `GET /campaigns*`, `status`, `report`, trial detail, alerts, timeseries,
  and export routes: `viewer` or higher
- `POST /campaigns/{campaign_id}/suggest` and `ingest`: `operator` or higher
- `POST /campaigns`, `reset`, and `restore`: `admin`

## Audit Events

When preview auth is enabled, the service writes auth audit events to:

```text
service_state/auth_audit_log.jsonl
```

Current event types:

- `authz_failure`: missing role, denied route access, or
  `enable_auth_preview = false` campaign use while service auth is enabled
- `privileged_action`: successful campaign registration, `reset`, and
  `restore`

These events are service-owned sidecar records. They do not replace or merge
into the campaign runtime's `state/event_log.jsonl`.

## OIDC Preview

OIDC is a separate preview auth mode and is off by default.

Example:

```bash
LOOPTIMUM_SERVICE_REGISTRY_FILE=service_state/campaign_registry.json \
LOOPTIMUM_SERVICE_AUTH_MODE=oidc \
LOOPTIMUM_SERVICE_OIDC_CONFIG='{
  "issuer": "https://issuer.example.test",
  "audience": "looptimum-preview",
  "subject_claim": "sub",
  "role_claim": "roles",
  "role_mapping": {
    "group:viewers": "viewer",
    "group:operators": "operator",
    "group:admins": "admin"
  }
}' \
python -m uvicorn service.app:create_app --factory
```

Current preview behavior:

- bearer tokens are parsed in-process by the preview service
- issuer and audience are checked against the configured values
- the configured subject and role claims are required
- external claim values are mapped into the existing `viewer` / `operator` /
  `admin` role matrix

Production recommendation:

- treat the current OIDC path as preview-only and trusted-environment scoped
- use it for local evaluation, internal demos, or behind an authenticating
  proxy/gateway
- do not treat this preview path as a full production identity boundary yet;
  it is intentionally narrower than a full enterprise SSO deployment

## API and Dashboard Posture

- the dashboard remains read-only even when preview auth is enabled
- the dashboard does not introduce its own session store or a second policy
  layer; it inherits the preview service route policy
- authenticated service usage does not bypass campaign file locks, preview
  coordination leases, worker `lease_token` rules, or explicit `report`
  generation semantics

Companion docs:

- [`service-api-preview.md`](./service-api-preview.md)
- [`dashboard-preview.md`](./dashboard-preview.md)
- [`coordination-preview.md`](./coordination-preview.md)

## Example Pack

Reference auth-preview artifacts:

- [`examples/auth_preview/README.md`](./examples/auth_preview/README.md)

That pack includes local-dev basic-auth user config, an OIDC config example,
captured auth failure payloads, an authenticated list response, and
service-owned audit-log lines.
