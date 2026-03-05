# Changelog

All notable changes to this repository are documented in this file.

The format is inspired by Keep a Changelog and follows the repository's
`0.x` compatibility policy.

## [0.2.3] - 2026-03-05

Patch release for the `v0.2.x` line focused on Phase 3 contract/schema
hardening and migration readiness.

### Added

- Migration documentation set:
  `docs/migrations/README.md`,
  `docs/migrations/template.md`,
  `docs/migrations/v0.2.x-to-v0.3.0.md`.
- Canonical state-version fixture set for compatibility testing:
  `tests/fixtures/state_versions/`.
- Cross-template state-version compatibility and upgrade-path tests:
  `templates/tests/test_state_versions.py`.

### Changed

- Runtime payloads now emit `schema_version` in `suggest`, `status`, `doctor`,
  and `report`.
- Authoritative state handling now normalizes and validates
  `state.schema_version` with semver format and explicit series compatibility.
- Legacy `v0.2.x` (or missing-version) state is auto-upgraded in-memory and
  persisted on the next mutating command with a loud migration warning.
- Shared suggestion/ingest schema files and template compatibility copies now
  include optional `schema_version` contract fields.
- Integration docs and examples now reflect schema-versioned payload/state
  artifacts.

### Notes

- This patch line release preserves existing `v0.2.x` public CLI contract
  semantics while adding transition-safe schema-version metadata.

## [0.2.2] - 2026-03-05

Patch release for the `v0.2.x` line focused on Phase 2 transparency docs and
planning/status alignment.

### Added

- `docs/how-it-works.md` covering backend-by-template behavior, acquisition
  policy, noise handling guidance, constraints posture, known pathologies, and
  determinism boundaries.

### Changed

- README first-screen algorithm summary now links directly to
  `docs/how-it-works.md`.
- Search-space and FAQ guidance now include explicit hard-constraint posture
  and default noisy-objective policy.
- Dev/plan tracking docs updated to reflect Phase 2 completion and
  `v0.2.2` as current patch baseline.

### Notes

- No runtime contract or CLI behavior changes in this patch release.

## [0.2.1] - 2026-03-04

Patch release for the `v0.2.x` line focused on final closeout reporting,
feedback-intake hardening, and documentation consistency.

### Added

- First-impressions GitHub Issue template:
  `.github/ISSUE_TEMPLATE/first-impressions.yml`.

### Changed

- Feedback intake policy and triage workflow documentation:
  `docs/feedback-loop.md`.
- Top-level README feedback template reference updated to
  `.github/ISSUE_TEMPLATE/first-impressions.yml`.
- Phase-8 closeout tracking reports updated with executed external dependency
  evidence:
  `reports/README.md`, `reports/phase8_external_inputs.md`.

### Notes

- No contract or runtime-behavior changes in this patch release.

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
