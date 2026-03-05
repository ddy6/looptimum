# Stability Guarantees

This document defines what is stable in the `v0.2.x` line, what may change,
and how breaking changes will be introduced.
Current patch tag in this line: `v0.2.1`.

## Scope

These guarantees apply to public template workflows and contracts used by
integration consumers:

- CLI command surface in `templates/bo_client_demo`, `templates/bo_client`,
  and `templates/bo_client_full`
- Payload schemas and ingest status vocabulary
- Core state-file compatibility for resumable file-backed runs

## `v0.2.x` Stability Promise

Within `v0.2.x`:

1. No breaking changes to command names and required flags for:
   `suggest`, `ingest`, `status`, `demo`, `cancel`, `retire`, `heartbeat`,
   `report`, `validate`, and `doctor`.
2. No breaking changes to ingest required fields and canonical status values:
   `ok`, `failed`, `killed`, `timeout` (`success` remains accepted alias).
3. Core state files remain append-compatible and resumable:
   `state/bo_state.json`, `state/observations.csv`,
   `state/acquisition_log.jsonl`, `state/event_log.jsonl`.

## Breaking-Change Policy

Breaking changes are allowed only on `0.x` major-line increments
(for example `0.2` -> `0.3`), and each such change must include:

1. Explicit migration notes in `CHANGELOG.md`.
2. Documentation updates in integration and operational docs.
3. An upgrader or scripted migration path when feasible.

No breaking changes are allowed within a `0.x` minor line.

## Deprecation Policy

When behavior is deprecated in `v0.2.x`:

1. The compatibility path remains functional through the line.
2. A warning is emitted where practical.
3. The planned removal release line is documented.

Current deprecations:

- `success` status alias is normalized to `ok`.
- Legacy non-`ok` + numeric primary objective is normalized to
  `objective: null` plus `penalty_objective`.
- Sentinel primary-objective compatibility is planned for removal in `v0.3.0`.

## What May Change Without a Breaking Bump

The following may evolve in `v0.2.x` without being treated as breaking:

- Internal surrogate/proxy implementation details and tuning heuristics.
- Additional optional fields in status/report/log payloads.
- Documentation structure and examples.
- CI workflow structure and release automation internals.

## Non-Guarantee Areas

This policy does not guarantee:

- Bit-for-bit reproducibility across different runtimes/dependencies.
- Stability of experimental/optional backend internals beyond the public
  contract.
- External evaluator behavior outside Looptimum templates.

## Upgrade and Support Path

- Release notes and migration details are tracked in `CHANGELOG.md`.
- Contract and operational behavior references:
  `docs/operational-semantics.md`, `docs/integration-guide.md`.
- Feedback and compatibility reports should be filed as GitHub Issues (primary
  source of truth).
