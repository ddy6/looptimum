# Service API Preview

This page documents the preview-only local FastAPI wrapper under `service/`.
It is an optional HTTP layer over the same file-backed runtime used by the CLI.

## Scope Boundary

- preview only: this surface is not part of the stable `v0.3.x`
  compatibility guarantee
- local-first: campaign roots remain local directories and stay authoritative
- registry metadata only: the service registry stores campaign id, label, root
  path, and created-at metadata, not optimizer state
- no hosted orchestration claims: this preview is a local API wrapper, not a
  multi-tenant control plane
- preview auth is available, but it remains local-first and service-scoped;
  CLI/runtime file-backed flows stay authless and authoritative

## Startup

From repo root:

```bash
LOOPTIMUM_SERVICE_REGISTRY_FILE=service_state/campaign_registry.json \
python -m uvicorn service.app:create_app --factory
```

Required campaign-side opt-in:

```json
{
  "feature_flags": {
    "enable_service_api_preview": true
  }
}
```

That flag must be present in the target campaign root's `bo_config.json`
before registration.

Optional service-auth preview:

- use [`auth-preview.md`](./auth-preview.md) for local-dev auth startup,
  role boundaries, audit-log posture, and OIDC preview caveats
- when service auth preview is enabled, campaign roots must also set
  `feature_flags.enable_auth_preview = true`

Optional coordination preview:

- use [`coordination-preview.md`](./coordination-preview.md) when you want the
  preview service to serialize mutating routes with a service-owned SQLite
  controller lease before the existing runtime file lock
- coordinated preview additionally requires
  `feature_flags.enable_multi_controller_preview = true`

## Campaign Registration

Register a file-backed campaign root with the preview service:

```bash
curl -X POST http://127.0.0.1:8000/campaigns \
  -H "content-type: application/json" \
  -d '{
    "root_path": "/abs/path/to/templates/bo_client_demo",
    "label": "Demo Preview Campaign"
  }'
```

The service validates that the root exists, contains the required contract
files, and has `feature_flags.enable_service_api_preview = true`.

## Endpoint Scope

Current preview endpoints:

- `GET /health`
- `GET /dashboard`
- `GET /dashboard/campaigns/{campaign_id}`
- `GET /campaigns`
- `POST /campaigns`
- `GET /campaigns/{campaign_id}`
- `GET /campaigns/{campaign_id}/detail`
- `GET /campaigns/{campaign_id}/status`
- `GET /campaigns/{campaign_id}/report`
- `GET /campaigns/{campaign_id}/trials`
- `GET /campaigns/{campaign_id}/trials/{trial_id}`
- `GET /campaigns/{campaign_id}/timeseries/best`
- `GET /campaigns/{campaign_id}/alerts`
- `GET /campaigns/{campaign_id}/decision-trace`
- `GET /campaigns/{campaign_id}/exports/report.json`
- `GET /campaigns/{campaign_id}/exports/report.md`
- `GET /campaigns/{campaign_id}/exports/decision-trace.jsonl`
- `POST /campaigns/{campaign_id}/suggest`
- `POST /campaigns/{campaign_id}/ingest`
- `POST /campaigns/{campaign_id}/reset`
- `POST /campaigns/{campaign_id}/restore`

Important parity rules:

- `suggest` preserves lock behavior, batch semantics, and `output_mode=jsonl`
- `ingest` preserves duplicate replay and lease-token enforcement
- `reset` and `restore` preserve `--yes`-style confirmation requirements and
  archive-id flows
- when service coordination preview is enabled, registration plus mutating
  routes also enforce `feature_flags.enable_multi_controller_preview = true`
- `report` stays read-only at the API layer and reads existing
  `state/report.json`
- campaign-bound dashboard routes additionally require
  `feature_flags.enable_dashboard_preview = true`

## Auth Preview

Preview auth is optional and disabled by default.

When enabled:

- `GET /health` remains unauthenticated for local probes
- all other service routes require an authenticated principal
- campaign roots must opt in with `feature_flags.enable_auth_preview = true`
- roles apply at the route layer:
  - `viewer`: read-only API, dashboard, and export endpoints
  - `operator`: `viewer` permissions plus `suggest` and `ingest`
  - `admin`: `operator` permissions plus campaign registration, `reset`, and
    `restore`
- the service writes a preview auth audit log under `service_state/`,
  separate from campaign runtime event logs

Reference doc:

- [`auth-preview.md`](./auth-preview.md)

## Coordination Preview

Preview coordination is optional and disabled by default.

When enabled:

- the service uses `LOOPTIMUM_SERVICE_COORDINATION_MODE=sqlite_lease`
- campaign roots must opt in with
  `feature_flags.enable_multi_controller_preview = true`
- coordinated `suggest`, `ingest`, `reset`, and `restore` acquire a
  service-owned controller lease before entering the existing runtime file lock
- dead controller leases can be reclaimed conservatively on the next request
- controller coordination leases remain distinct from per-trial worker
  `lease_token` values

Reference doc:

- [`coordination-preview.md`](./coordination-preview.md)

## Dashboard Companion

The preview service now also mounts a read-only operator shell under
`/dashboard`. That shell uses the preview API only and does not read state
files directly.

Reference docs:

- [`dashboard-preview.md`](./dashboard-preview.md)

## Operational Caveats

- one controller/writer per campaign root still applies
- the service does not bypass file locks or create a second mutation path
- mutating endpoints fail whole-command, matching CLI/runtime boundaries
- the registry is only a lookup table for registered roots; deleting it does
  not delete campaign state
- preview auth and preview coordination are still preview-scoped and
  local-first; the service is not a hosted control plane

## Example Pack

Reference request/response artifacts:

- [`examples/service_api_preview/README.md`](./examples/service_api_preview/README.md)
- [`examples/dashboard_preview/README.md`](./examples/dashboard_preview/README.md)
- [`examples/auth_preview/README.md`](./examples/auth_preview/README.md)
- [`examples/coordination_preview/README.md`](./examples/coordination_preview/README.md)

That pack includes sample payloads for campaign create/read, `suggest`,
`ingest`, and `report`, captured from the preview service against a temp
`bo_client_demo` campaign root. The dashboard companion pack adds captured HTML
and the read-model payloads consumed by the preview shell.
