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
- `GET /campaigns`
- `POST /campaigns`
- `GET /campaigns/{campaign_id}`
- `GET /campaigns/{campaign_id}/detail`
- `GET /campaigns/{campaign_id}/status`
- `GET /campaigns/{campaign_id}/report`
- `POST /campaigns/{campaign_id}/suggest`
- `POST /campaigns/{campaign_id}/ingest`
- `POST /campaigns/{campaign_id}/reset`
- `POST /campaigns/{campaign_id}/restore`

Important parity rules:

- `suggest` preserves lock behavior, batch semantics, and `output_mode=jsonl`
- `ingest` preserves duplicate replay and lease-token enforcement
- `reset` and `restore` preserve `--yes`-style confirmation requirements and
  archive-id flows
- `report` stays read-only at the API layer and reads existing
  `state/report.json`

## Operational Caveats

- one controller/writer per campaign root still applies
- the service does not bypass file locks or create a second mutation path
- mutating endpoints fail whole-command, matching CLI/runtime boundaries
- the registry is only a lookup table for registered roots; deleting it does
  not delete campaign state
- dashboard/auth/multi-controller work is out of scope for this preview

## Example Pack

Reference request/response artifacts:

- [`examples/service_api_preview/README.md`](./examples/service_api_preview/README.md)

That pack includes sample payloads for campaign create/read, `suggest`,
`ingest`, and `report`, captured from the preview service against a temp
`bo_client_demo` campaign root.
