# Changelog

All notable changes to this repository are documented in this file.

The format is inspired by Keep a Changelog and follows the repository's
`0.x` compatibility policy.

## [0.2.0] - 2026-03-04

This release packages the end-to-end 2026 update program (phases 1-8) into a
stable `v0.2.x` line.

### Added

- New contract and operating docs:
  `docs/operational-semantics.md`, `docs/search-space.md`,
  `docs/decision-trace.md`, `docs/pilot-checklist.md`.
- Lifecycle and ops command surface in templates:
  `cancel`, `retire`, `heartbeat`, `report`, `validate`, `doctor`.
- Trial artifact manifests and event logging under `state/trials/` and
  `state/event_log.jsonl`.
- Trust-building assets:
  tiny objective loop, deterministic decision-trace samples, and transcript
  references.
- CI quality gates for format/lint/internal-links and test matrix.

### Changed

- README and docs were rewritten to be mainstream-first and contract-forward.
- Config and schema handling is now explicitly JSON-first with optional YAML
  support.
- Ingest/state semantics were hardened across demo/default/full templates with
  explicit parity tests for contract-critical behavior.
- Runtime state persistence now uses stronger locking and atomic-write patterns
  for mutating commands.

### Deprecated

- `success` ingest status alias remains accepted but normalized to `ok`.
- Legacy non-`ok` payloads with numeric primary objective remain accepted in
  `v0.2.x` and are normalized to `objective: null` plus `penalty_objective`.
- Sentinel primary-objective compatibility is planned for removal in `v0.3.0`.

### Migration Notes

- Contract files are canonically JSON (`bo_config.json`, `parameter_space.json`,
  `objective_schema.json`); legacy YAML paths remain accepted with deprecation
  warnings.
- Consumers should treat `state/bo_state.json` as authoritative and
  `acquisition_log.jsonl`/`event_log.jsonl` as audit trails.
- Integrations that previously sent non-`ok` + numeric primary objective should
  move to `objective: null` and optional `penalty_objective`.
- Release-line stability and upgrade guarantees are documented in
  `docs/stability-guarantees.md`.
