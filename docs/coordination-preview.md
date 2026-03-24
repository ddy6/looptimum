# Coordination Preview

This page documents the preview-only multi-controller coordination layer for
the local `service/` stack.

It does not replace the file-backed runtime authority: campaign state remains
local to each registered root, and the existing runtime file lock stays in
place beneath the preview coordination lease.

## Scope Boundary

- preview only: this surface is not part of the stable `v0.3.x`
  compatibility guarantee
- service-scoped only: direct CLI/runtime usage inside a campaign root remains
  unchanged and uncoordinated by this preview layer
- disabled by default: the service must opt in with
  `LOOPTIMUM_SERVICE_COORDINATION_MODE=sqlite_lease`
- campaign roots must also opt in with
  `feature_flags.enable_multi_controller_preview = true`
- first backend only: the current preview coordination backend is SQLite under
  `service_state/coordination.sqlite3`
- not a hosted control plane: this is a local preview controller-lease layer,
  not a general distributed scheduler

## Startup

From repo root:

```bash
LOOPTIMUM_SERVICE_REGISTRY_FILE=service_state/campaign_registry.json \
LOOPTIMUM_SERVICE_COORDINATION_MODE=sqlite_lease \
LOOPTIMUM_SERVICE_COORDINATION_LEASE_TTL_SECONDS=30 \
python -m uvicorn service.app:create_app --factory
```

Required campaign-side flags:

```json
{
  "feature_flags": {
    "enable_service_api_preview": true,
    "enable_multi_controller_preview": true
  }
}
```

Notes:

- `enable_service_api_preview = true` is still required for campaign
  registration and service usage in general
- `enable_multi_controller_preview = true` is required only when the service
  itself is running in coordinated preview mode
- preview auth and dashboard flags remain independent of coordination

## Lease Model

Current coordinated preview behavior:

- the service acquires one controller lease per campaign id before entering the
  existing runtime file lock
- coordinated preview currently applies to `suggest`, `ingest`, `reset`, and
  `restore`
- registration is still registry-scoped, but campaign registration in
  `sqlite_lease` mode also enforces
  `feature_flags.enable_multi_controller_preview = true`
- if the controller lease cannot be acquired in time, the service returns:

```json
{
  "error": {
    "code": "coordination_unavailable",
    "message": "service coordination lease unavailable for campaign 'example'"
  }
}
```

## Worker Lease Tokens

Controller coordination leases are distinct from Workstream 5 worker
`lease_token` values.

- controller leases are service-owned and campaign-scoped
- worker `lease_token` values remain per-trial handoff tokens for
  `heartbeat` / `ingest` when worker leases are enabled
- coordinated preview does not remove or replace worker-token enforcement

## Failure and Reclaim

Current reclaim posture is conservative:

- controller leases use a duration derived from the effective runtime lock
  timeout so reclaim only targets clearly stale controller rows
- fail-fast preview requests return `409 coordination_unavailable` immediately
  if another live controller holds the lease
- non-fail-fast preview requests wait up to the effective runtime lock timeout
- expired controller rows can be reclaimed by the next request

Operational caveats:

- the SQLite file under `service_state/coordination.sqlite3` stores preview
  coordination state only; it is not optimizer state
- deleting the SQLite file removes preview coordination history, but does not
  delete or repair campaign runtime state
- the dashboard remains read-only and does not create or manage controller
  leases

## Example Pack

Reference coordination-preview artifacts:

- [`examples/coordination_preview/README.md`](./examples/coordination_preview/README.md)

That pack includes a coordinated campaign flag example, service startup env
example, aggregated parallel suggest outcomes, a held-lease failure payload,
and a reclaim example captured at the payload level.

Companion docs:

- [`service-api-preview.md`](./service-api-preview.md)
- [`dashboard-preview.md`](./dashboard-preview.md)
- [`auth-preview.md`](./auth-preview.md)
