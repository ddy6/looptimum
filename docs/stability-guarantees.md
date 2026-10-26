# Stability Guarantees

The stable `v1.x` contract covers the repository templates and their file-backed
workflow. Version in this checkout: `v1.0.0`. Publication is identified by the
[GitHub release/tag](https://github.com/ddy6/looptimum/releases), not by this text.
See the [upgrade guide](migration-v1.md) and [release procedure](release-guide.md).

## Stable Surface

The following remain compatible throughout package major version 1:

- Existing CLI command names, required flags and documented meanings for all
  three templates: `suggest`, `ingest`, `status`, `demo`, `cancel`, `retire`,
  `heartbeat`, `import-observations`, `export-observations`, `report`, `reset`,
  `list-archives`, `restore`, `prune-archives`, `health`, `metrics`, `validate`
  and `doctor`. Ordinary/full controllers additionally expose the documented
  Ax `recover-allocation` and `rebuild-optimizer --reason TEXT` operations.
- Required suggestion/result fields, canonical terminal statuses `ok`,
  `failed`, `killed`, `timeout`, and the accepted `success` ingest alias.
  Optional fields can be added; consumers must ignore unknown optional fields.
- Evaluator-facing raw parameter types/units, trial identity, pending and
  evaluation budgets, lease checks, identical-ingest no-op semantics, and
  successful-observation-only best ranking under the configured objective policy.
- Canonical state readability and documented lifecycle/recovery behavior for
  supported state series. Existing proxy/direct-BoTorch selection remains
  available; omitting `optimizer` continues to select the legacy backend.
- Optional native Ax selection in ordinary/full controllers within the
  [supported feature matrix](ax-support-matrix.md) and
  [tested CPU installation profile](ax-installation.md). Ax remains opt-in;
  the demo template does not acquire a numerical dependency.

New optional commands/configuration can be added in minor releases. Bug fixes
and internal numerical improvements can change which point an optimizer
proposes; proposal identity and performance are not stable API guarantees.
Unsupported Ax features are rejected explicitly, not silently approximated.

## Version Boundaries

Package, canonical state, evaluator payload and optimizer snapshot versions
serve different purposes and are not renumbered together:

| Surface | Version in v1.0.0 | Compatibility |
| --- | --- | --- |
| Package / repository tag | `1.0.0` / `v1.0.0` | Semantic Versioning for the stable surface |
| Legacy canonical state | `0.3.x` (new state `0.3.0`) | Existing `0.3.x` remains readable without a forced rewrite |
| Ax canonical state | `0.4.x` (new state `0.4.0`) | Requires explicit Ax backend metadata and optimizer format `1` |
| Suggestion/result/status payloads | Existing `0.3.x`; Ax emits `0.3.0` | Existing evaluator contract remains usable |
| Ax optimizer envelope | Format `1` | Guarded snapshot digest, semantic fingerprint, lineage and dependency versions |

Missing-version or `0.2.x` legacy state is upgraded in memory to `0.3.0`, with
a warning, and persisted on the next mutating command. Read-only commands do
not silently rewrite it. Fixtures live in
[`tests/fixtures/state_versions/`](../tests/fixtures/state_versions/README.md).

Older released controllers must not continue Ax campaigns. The retained state
reader from tag `v0.4.0` is tested to reject Ax `0.4.x`; legacy `0.3.x` remains
readable by that reader. Do not edit a state version or remove optimizer
metadata to force a downgrade.

Canonical state compatibility does not promise that upstream Ax JSON snapshots
can be loaded under arbitrary dependency versions. Generation requires the
recorded six numerical package versions and matching semantic configuration.
Restore that environment and snapshot for exact recovery. If unavailable,
explicit rebuild preserves canonical trials/results but creates a new lineage;
future proposals can differ. Profile updates must document this boundary and
provide fresh compatibility evidence. Canonical reads, ingestion and terminal
lifecycle operations continue to work without importing the optimizer stack.

## Preview and Internal Surfaces

The optional [service API](service-api-preview.md),
[dashboard](dashboard-preview.md), [authentication](auth-preview.md) and
[controller coordination](coordination-preview.md) remain preview-only, outside
the stable `v1.x` compatibility promise. Their `1.0.0-preview` service metadata
does not promote them to a stable hosted or distributed control plane.
The supported topology remains one controller/writer per campaign with local
file locking. External evaluator behavior is owned by the integration.

Python imports from template/shared modules, upstream Ax/BoTorch APIs, optimizer
heuristics, internal snapshot contents and decision diagnostics are not a new
public Python SDK. The package wheel contains the optional service; portable
controllers are produced from the repository templates.

## Breaking Changes and Deprecations

Breaking changes to the stable surface require package `2.0.0` or later,
migration instructions, changelog entries, and an upgrader where feasible.
Minor and patch releases must preserve the documented v1 contracts. A changed
upstream optimizer environment may require the explicit rebuild described
above; it must never silently reset history or fall back to another backend.

Deprecated interfaces remain functional throughout v1.x, emit a warning where
practical, and name their earliest removal major version. Current deprecation:

- Ingest `failure_reason` is an accepted compatibility alias for
  `terminal_reason`, retained throughout v1.x. Earliest removal: `v2.0.0`.
  `terminal_reason` takes precedence when both are supplied. Successful results
  do not retain failure reasons.

## Operational Limits

The contract does not guarantee identical proposals across dependency versions,
operating systems or Python minors, nor a performance advantage on an arbitrary
objective. Numerical tolerances and resource bounds belong to the recorded
probe/benchmark evidence. Snapshot/allocation recovery covers the documented
process-exit boundaries; it is not a transaction over all lifecycle commands
or a power-loss durability promise. Persistence uses atomic replacement without
explicit file/directory syncing. Restore complete matching backups, including
optimizer files, configuration and environment receipts.

Issues and compatibility reports belong in GitHub Issues. Release history is
in [CHANGELOG.md](../CHANGELOG.md); operating procedures are in
[operational semantics](operational-semantics.md) and the
[recovery playbook](recovery-playbook.md).
