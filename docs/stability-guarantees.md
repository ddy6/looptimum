# Stability Guarantees

This document defines what is stable in the `v0.3.x` line, what may change,
and how breaking changes are introduced.
Current patch tag in this line: `v0.3.5`.

## Scope

These guarantees apply to public template workflows and contracts used by
integration consumers:

- CLI command surface in `templates/bo_client_demo`, `templates/bo_client`,
  and `templates/bo_client_full`
- Payload schemas and ingest status vocabulary
- Core state-file compatibility for resumable file-backed runs

## `v0.3.x` Stability Promise

Within `v0.3.x`:

1. No breaking changes to command names and required flags for:
   `suggest`, `ingest`, `status`, `demo`, `cancel`, `retire`, `heartbeat`,
   `report`, `reset`, `validate`, and `doctor`.
2. No breaking changes to ingest required fields and canonical status values:
   `ok`, `failed`, `killed`, `timeout` (`success` remains accepted alias).
3. Core state files remain append-compatible and resumable:
   `state/bo_state.json`, `state/observations.csv`,
   `state/acquisition_log.jsonl`, `state/event_log.jsonl`.

## `v0.3.x` State Compatibility Policy

This policy is active for the `v0.3.x` line:

1. `state/bo_state.json` includes required `schema_version` with semver string
   format (`<major>.<minor>.<patch>`), for example `"0.3.0"`.
2. Any earlier `v0.3.x` state must load transparently in `v0.3.x`.
3. Warn-only deprecations are allowed, but load failures are not allowed for
   earlier `v0.3.x` state versions.
4. Legacy `v0.2.x` states (or missing `schema_version`) are upgraded in-memory
   and persisted on the next mutating command, with a loud warning.
5. Canonical compatibility fixtures live under
   `tests/fixtures/state_versions/`.

## Breaking-Change Policy

Breaking changes are allowed only on `0.x` major-line increments
(for example `0.3` -> `0.4`), and each such change must include:

1. Explicit migration notes in `CHANGELOG.md`.
2. Documentation updates in integration and operational docs.
3. An upgrader or scripted migration path when feasible.

No breaking changes are allowed within a `0.x` minor line.

## Deprecation Policy

When behavior is deprecated in `v0.3.x`:

1. The compatibility path remains functional through the line.
2. A warning is emitted where practical.
3. The planned removal release line is documented.

Current deprecations:

- none tracked in the current public contract surface

## What May Change Without a Breaking Bump

The following may evolve in `v0.3.x` without being treated as breaking:

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
- Compatibility details and release notes:
  `CHANGELOG.md`,
  `docs/stability-guarantees.md`.
- Feedback and compatibility reports should be filed as GitHub Issues (primary
  source of truth).
