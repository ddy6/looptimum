# Templates

Public runnable optimization harness variants copied from the current workspace (cleaned for release).

Each variant below is part of the Looptimum template surface.

- `bo_client_demo/`: proxy-only, dependency-light demo path
- `bo_client/`: baseline client harness with config-selected backend (`rbf_proxy` or optional `gp`)
- `bo_client_full/`: proxy + optional BoTorch GP behind feature flag

Each template exposes the same CLI surface:

- `status`
- `suggest`
- `ingest`
- `demo`

## Shared Contract Runtime

Canonical shared contract components live under:

- `templates/_shared/contract.py`
- `templates/_shared/schemas/`

Template-local `schemas/` directories are compatibility copies for standalone
use:

- canonical: `ingest_payload.schema.json`, `search_space.schema.json`,
  `suggestion_payload.schema.json`

Template-local `bo_config.json` files now share a common `feature_flags`
scaffold:

- active today: `enable_botorch_gp`,
  `fallback_to_proxy_if_unavailable` (`bo_client_full` only)
- reserved no-op preview flags:
  `enable_service_api_preview`,
  `enable_dashboard_preview`,
  `enable_auth_preview`

To vendor shared contract helpers/schemas into a standalone template copy:

```bash
python3 templates/_shared/vendor_copy.py templates/bo_client_demo --rewrite-config-paths
```
