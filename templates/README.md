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
