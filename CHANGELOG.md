# Changelog

All notable changes to this repository are documented in this file.

The format is inspired by Keep a Changelog and follows the repository's
`0.x` compatibility policy.

## [0.3.2] - 2026-03-08

Patch release for the `v0.3.x` line focused on richer non-`ok` ingest
diagnostics and safe one-command campaign reset.

### Added

- Optional `terminal_reason` ingest field is now wired end-to-end in contracts,
  template schemas, client harness tooling, and persisted observation artifacts.
- Legacy `failure_reason` ingest/objective output alias is accepted and
  normalized to `terminal_reason` with deprecation warnings.
- Non-`ok` payloads missing an explicit reason now get deterministic fallback
  `terminal_reason: "status=<status>"`.
- New `reset` runtime command across `bo_client`, `bo_client_demo`, and
  `bo_client_full` with explicit confirmation safeguards.
- Default archive-on-reset behavior (`state/reset_archives/reset-<id>/...`) and
  `--no-archive` override for explicit opt-out.

### Changed

- Public docs and template READMEs now document `terminal_reason` semantics,
  reset behavior, and `v0.3.2` as the current patch tag.
- Package metadata now targets `0.3.2`.

## [0.3.1] - 2026-03-07

Patch release for the `v0.3.x` line focused on surrogate robustness when state
contains failed/non-`ok` observations.

### Fixed

- Fixed `suggest` crash on campaigns containing only failed/non-`ok`
  observations (`float(None)` from surrogate objective casting).
- Surrogate proposal paths in `bo_client`, `bo_client_demo`, and
  `bo_client_full` now train/score only with usable rows
  (`status == "ok"` with finite numeric primary objective values).
- `suggest` now falls back to random suggestion when no usable observations are
  available after the initial-random phase.
- GP and BoTorch fit paths now fall back to random suggestion when usable
  observations are below minimum fit requirements.

### Added

- Regression tests covering non-`ok`-only campaigns, mixed `ok`/failed state,
  and GP/BoTorch insufficient-usable fallback behavior across template
  variants.

## [0.3.0] - 2026-03-06

Compatibility-forward line cut that closes out the `v0.2.9` patch cycle and
establishes the `v0.3.x` baseline.

### Added

- Final release-readiness and operator sign-off artifacts:
  `reports/v0.3.0_release_readiness.md`,
  `reports/v0.3.0_release_candidate_checklist.md`.

### Changed

- Project release baseline now targets `0.3.0` in package metadata and public
  docs.
- Stability policy docs now describe active guarantees for the `v0.3.x` line.
- Runtime sentinel-deprecation messaging now points to `v0.4.0` removal target
  (compatibility retained in `v0.3.0`).

### Deprecated

- `success` ingest status alias remains supported but deprecated in favor of
  `ok`.
- Legacy non-`ok` numeric primary-objective sentinel payloads remain
  compatibility-only and warn.
- Legacy `paths.result_schema_file` and YAML compatibility-mode paths remain
  warn-only compatibility behavior with documented `v0.4.0` removal target.

### Compatibility Notes

- `state.schema_version` is required for `v0.3.0` state artifacts.
- Legacy `v0.2.x` (or missing-version) state auto-upgrades in-memory and
  persists on next mutating command.
- Earlier `v0.3.x` state versions load transparently in `v0.3.x`.

### Migration

- Canonical migration spec: `docs/migrations/v0.2.x-to-v0.3.0.md`.

## [0.2.9] - 2026-03-06

Patch release for the `v0.2.x` line focused on Phase 9 documentation trust
pass and public-doc consistency guardrails.

### Added

- Spec-style quick reference for contract semantics and state artifacts:
  `docs/quick-reference.md`.
- Opinionated mainstream ETL/pipeline scenario quickstart:
  `quickstart/etl-pipeline-knob-tuning.md`.
- Lightweight public docs consistency checker:
  `scripts/check_docs_consistency.py`.
- Phase 9 asset guard tests:
  `client_harness_template/tests/test_phase9_assets.py`.

### Changed

- README now includes CI + latest-release trust badges and explicit trust-anchor
  links for key product claims.
- CI quality gate now enforces public-doc consistency and scopes markdown-link
  checks to public docs (`README.md`, `docs/`, `quickstart/`).
- Contributor validation flow now includes public docs consistency checks.

### Notes

- This patch release preserves the `v0.2.x` no-breaking-change contract while
  improving documentation auditability and reducing public-doc drift risk.

## [0.2.8] - 2026-03-05

Patch release for the `v0.2.x` line focused on Phase 8 evidence anchors and
performance-credibility assets.

### Added

- Canonical benchmark/evidence suite and golden artifacts:
  `benchmarks/run_trial_efficiency_benchmark.py`,
  `benchmarks/summary.json`,
  `benchmarks/case_study.md`,
  `benchmarks/README.md`.
- Lightweight benchmark-sanity checker and CI integration:
  `scripts/check_benchmark_sanity.py`,
  `.github/workflows/ci.yml`.
- Benchmark/evidence asset contract tests:
  `client_harness_template/tests/test_phase8_assets.py`.

### Changed

- Top-level README now includes an explicit Evidence section and rerun command
  wiring to benchmark artifacts.
- Contributor and docs index references now include benchmark sanity and
  evidence-entry points (`CONTRIBUTING.md`, `docs/index.md`, `docs/README.md`).

### Notes

- This patch release preserves the `v0.2.x` no-breaking-change contract while
  adding reproducible evidence anchors for optimization trust checks.

## [0.2.7] - 2026-03-05

Patch release for the `v0.2.x` line focused on Phase 7 CI/CD playbook and
reproducible operations.

### Added

- Platform-agnostic CI tuning playbook with GitHub Actions examples:
  `docs/ci-knob-tuning.md`.
- Lightweight docs-sync validator for CI playbook drift:
  `scripts/check_ci_playbook_sync.py`.
- Phase 7 asset guard tests:
  `client_harness_template/tests/test_phase7_assets.py`.

### Changed

- CI quality gates now include CI playbook sync validation:
  `.github/workflows/ci.yml`.
- Contributor validation workflow now includes CI playbook sync check:
  `CONTRIBUTING.md`.
- Quickstart/integration/docs index references now include the CI tuning
  playbook entry points.

### Notes

- This patch release preserves the `v0.2.x` no-breaking-change contract while
  adding reproducible CI runbook guidance and docs-rot guardrails.

## [0.2.6] - 2026-03-05

Patch release for the `v0.2.x` line focused on Phase 6 enterprise readiness
and type-safety hardening.

### Added

- Initial blocking `mypy` CI gate on canonical runtime scope (Python 3.12):
  `templates/_shared/*.py`,
  `templates/bo_client/run_bo.py`,
  `client_harness_template/run_one_eval.py`.
- Type-safety policy doc and contributor guidance:
  `docs/type-safety.md`, `CONTRIBUTING.md`.
- Dev dependency typing support for gate consistency:
  `mypy`, `types-PyYAML`.

### Changed

- Canonical runtime modules now use stronger explicit typing annotations and
  typed dynamic-boundary handling to reduce implicit-`Any` drift.
- `mypy` configuration now enforces staged-moderate strictness rules:
  generic/container typing, typed defs, no implicit re-export leakage, and
  return-`Any` warnings.

### Notes

- This patch release preserves the `v0.2.x` no-breaking-change contract while
  establishing a stricter, auditable typing baseline for `v0.3.0`.

## [0.2.5] - 2026-03-05

Patch release for the `v0.2.x` line focused on Phase 5 reliability,
interruption handling, and operator recovery clarity.

### Added

- Canonical interruption/recovery acceptance coverage in
  `templates/bo_client/tests/`:
  stale pending resume, injected ingest write-failure retry, and duplicate
  ingest replay after retry path.
- Demo/full parity smoke + contract assertions for interruption traceability:
  `templates/bo_client_demo/tests/test_ops_demo.py`,
  `templates/bo_client_full/tests/test_ops_full.py`.
- Dedicated operator runbook:
  `docs/recovery-playbook.md` (decision tree + prescriptive command flows).

### Changed

- Trial/report traceability fields were hardened for terminal and non-`ok`
  outcomes across template variants (`status`, `terminal_reason`,
  terminal timestamp, `penalty_objective`, `artifact_path` contract behavior).
- Integration/quickstart/operational docs now link to a single recovery
  playbook for interruption and CI/local failure handling.

### Notes

- This patch release preserves the `v0.2.x` no-breaking-change contract while
  improving trust in resumability and failure forensics.

## [0.2.4] - 2026-03-05

Patch release for the `v0.2.x` line focused on Phase 4 template/config
consistency completion.

### Added

- Explicit template matrix sections documenting feature parity, backend
  differences, and intended use:
  `README.md`, `docs/integration-guide.md`.
- Canonical template-local shared schema assets in each template:
  `schemas/ingest_payload.schema.json`,
  `schemas/search_space.schema.json`,
  `schemas/suggestion_payload.schema.json`.
- Compatibility asset parity test coverage:
  `templates/tests/test_template_schema_assets.py`.

### Changed

- YAML contract loading is now explicit compatibility mode via
  `LOOPTIMUM_YAML_COMPAT_MODE=1` (optional allowlist:
  `LOOPTIMUM_YAML_COMPAT_ALLOWLIST`) with deprecation/removal target messaging.
- Legacy `paths.result_schema_file` compatibility remains warn-only in `v0.3.x`
  transition flow and now includes removal target (`v0.4.0`) in warnings.
- Template-local `result_payload.schema.json` is now a documented compatibility
  alias aligned to canonical ingest schema content (scheduled removal: `v0.4.0`).
- Quickstart/docs now emphasize the canonical JSON happy path and note that the
  default clean flow runs without compatibility warnings.

### Notes

- This patch release preserves the `v0.2.x` no-breaking-change contract while
  reducing template/config convention drift and deprecation noise.

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
