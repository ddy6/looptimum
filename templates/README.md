# Templates

Start with the [portable ordinary-controller quickstart](../quickstart/README.md).
Each campaign needs its configuration, runtime modules and schemas; copying only
`run_bo.py` is insufficient. The service wheel does not include these templates.

## Backend choices

| Template | Default backend | Optional backends |
| --- | --- | --- |
| `bo_client_demo` | `rbf_proxy` | none |
| `bo_client` | `rbf_proxy` | `gp`, `ax` |
| `bo_client_full` | `rbf_proxy` | `botorch_gp`, `ax` |

Ordinary direct GP uses `surrogate.type: "gp"`. Full BoTorch GP uses
`--enable-botorch-gp` or its configuration flag. Native Ax uses
`optimizer.backend: "ax"` on ordinary/full controllers, not `surrogate.type`.
See [optimizer behavior](../docs/how-it-works.md), the
[Ax support matrix](../docs/ax-support-matrix.md) and
[Ax CPU installation](../docs/ax-installation.md) for dependencies and limits.
Demo remains proxy-only. All defaults stay dependency-light.

## Commands and preview consumers

The core loop is `suggest`, external evaluation, `ingest`, then `status`;
`demo` provides a synthetic loop. Lifecycle, archive, import/export, health,
metrics and diagnostic commands are listed in the
[quick reference](../docs/quick-reference.md). Ordinary/full controllers also
provide Ax allocation recovery and optimizer rebuild commands.

The standalone CLI does not start preview services. These feature flags are
active gates enforced by `service/registry.py` when the corresponding service
routes are used:

| Flag | Consumer |
| --- | --- |
| `enable_service_api_preview` | Campaign registration/service API |
| `enable_dashboard_preview` | Dashboard routes |
| `enable_auth_preview` | Auth-protected preview routes |
| `enable_multi_controller_preview` | Coordinated preview routes |

See [service startup](../docs/service-api-preview.md) before using preview
surfaces. The [effective configuration table](../docs/how-it-works.md#effective-and-ignored-configuration)
distinguishes these external consumers from genuinely ignored sample settings.

## Portable copies and shared contracts

The [quickstart](../quickstart/README.md) demonstrates the supported generator
from stock `bo_client` into an empty directory outside the source templates.
It vendors runtime helpers and schemas under `vendor/looptimum_shared/` and
rewrites controller/schema paths. Copy the root license as shown there.
Named default histories and caches are omitted; arbitrary customized campaign
paths require separate inspection.

Canonical contracts live in `templates/_shared/contract.py` and
`templates/_shared/schemas/`. Template-local `schemas/` directories are
compatibility copies. Keep the full generated bundle with each campaign.

Variant references: [ordinary](./bo_client/README.md),
[full](./bo_client_full/README.md), [demo](./bo_client_demo/README.md).
