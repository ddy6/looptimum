# bo_client

Minimal single-stage optimization harness with explicit config, a swappable
surrogate backend, and restartable JSON state.

## Path Guidance

- Running this template directly means you are on the repo path.
- Optional preview service/dashboard/auth/coordination layers sit on top of the
  same file-backed runtime and are not required for this template.
- High-level path overview:
  `../../docs/packages.md`
- Public compatibility posture:
  `../../docs/stability-guarantees.md`

## Files

- `run_bo.py`: driver for `suggest`, `ingest`, `import-observations`,
  `export-observations`, `status`, `demo`, `cancel`, `retire`, `heartbeat`,
  `report`, `reset`, `list-archives`, `restore`, `prune-archives`,
  `validate`, and `doctor`.
- `bo_config.json`: run budget, surrogate/acquisition choices, shared
  `feature_flags`, seed, and state paths.
- `parameter_space.json`: explicit parameter types and bounds.
- `constraints.json` (optional): hard-feasibility rules for `suggest`.
- `objective_schema.json`: primary objective, optional secondary objectives,
  and optional scalarization policy.
- `experiment_interface.md`: async experiment I/O contract.
- `examples/`: sample success/failure result payloads and runnable command sequence.
- `schemas/`: compatibility copies of shared schemas (`ingest_payload`,
  `search_space`, `suggestion_payload`).
- `scripts/`: synthetic objective helper.
- `surrogate_proxy.py`: proxy backend scoring.
- `surrogate_gp.py`: BoTorch/GPyTorch backend scoring.
- `acquisition.py`: acquisition scoring (`ei` default, `ucb` optional).

## Notes

- JSON (`.json`) is the required contract format.
- `feature_flags` exists in all templates; preview flags are reserved scaffolding
  and no-op in the current file-backed runtime.
- State persists in `state/bo_state.json` and can be resumed between runs
  (no hidden service state).
- Mutating commands use an exclusive lock file (`state/.looptimum.lock`);
  default behavior waits with timeout and supports `--fail-fast`.
- `suggest` keeps count-1 output backward compatible, supports locked batches
  via `--count N` / `bo_config.batch_size`, and can emit worker-oriented
  JSONL with `--jsonl`.
- `max_pending_trials`, when configured, rejects the whole requested batch
  before pending state is mutated.
- `ingest` validates payload structure via `paths.ingest_schema_file` and
  enforces the full configured `objectives` map.
- `import-observations` supports strict and permissive warm-start seeding;
  permissive runs write reports under `state/import_reports/`.
- `export-observations` writes canonical JSONL or flat CSV rows from
  authoritative state for future campaign seeding.
- optional worker leases add `lease_token` to suggestions and require matching
  `--lease-token` on `heartbeat` / `ingest`.
- Runtime artifacts include `state/event_log.jsonl`, per-trial manifests in
  `state/trials/trial_<id>/manifest.json`, and explicit `report` outputs.
- Archive-management commands cover inventory (`list-archives`), rollback
  (`restore`), and retention cleanup (`prune-archives`).
- Read-only `health` and `metrics` expose lock, status, retention, and
  governance summaries without mutating campaign state.
- Multi-objective manifests and reports preserve raw `objective_vector` values,
  scalarized ranking metadata, and Pareto summaries.
- Acquisition decisions now include backend labels and feasibility metadata in
  `state/acquisition_log.jsonl`; all-infeasible constrained attempts are logged
  before `suggest` exits nonzero.

## Surrogate Selection

Set `surrogate.type` in `bo_config.json`:

- `rbf_proxy` (default): no heavy dependencies.
- `gp`: BoTorch `SingleTaskGP` with Matern 2.5 kernel.

No CLI changes are needed when switching backend.

## Reproducibility

- Random candidate generation is seeded from config/state.
- State and trial IDs are resumable via `state/bo_state.json`.
- Acquisition decisions are logged in `state/acquisition_log.jsonl`.
- Lifecycle and ops events are logged in `state/event_log.jsonl`, including
  `governance_override_used` and `governance_violations_detected`.

## Example Payloads

- `examples/example_results.json`: success (`status: "ok"`)
- `examples/example_results_timeout.json`: non-`ok` sample
  (`status: "timeout"`, configured objectives `null`, `terminal_reason`,
  `penalty_objective`)
- `examples/example_run.sh [results-file]`: run script; optional arg selects
  which sample payload to ingest

## Cross-Repo References

- Tiny end-to-end objective loop:
  `examples/toy_objectives/03_tiny_quadratic_loop/`
- Golden decision-trace sample:
  `docs/examples/decision_trace/golden_acquisition_log.jsonl`
- Multi-objective example pack:
  `docs/examples/multi_objective/README.md`
- Batch + async worker example pack:
  `docs/examples/batch_async/README.md`
- Warm-start import/export example pack:
  `docs/examples/warm_start/README.md`
- Text transcript of `suggest -> evaluate -> ingest -> status`:
  `docs/examples/decision_trace/cli_transcript.md`

## Dependencies

- Core/demo mode: Python standard library + `pytest` for tests.
- GP mode: install `torch`, `botorch`, `gpytorch`.

## Tests

```bash
pytest -q
```

Test files are split by behavior:

- `tests/test_suggest.py`
- `tests/test_ingest.py`
- `tests/test_resume.py`

Run GP-specific coverage explicitly:

```bash
RUN_GP_TESTS=1 pytest -q tests/test_suggest.py::test_suggest_works_with_gp_backend
```
