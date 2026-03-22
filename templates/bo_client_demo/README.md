# bo_client_demo

Proxy-surrogate optimization harness (`rbf_proxy`) with explicit configuration and restartable state.

## Files

- `run_bo.py`: `suggest`, `ingest`, `import-observations`,
  `export-observations`, `status`, `demo`, `cancel`, `retire`, `heartbeat`,
  `report`, `reset`, `list-archives`, `restore`, `prune-archives`,
  `validate`, `doctor`
- `bo_config.json`: budget, surrogate/acquisition, shared `feature_flags`,
  seed, paths
- `parameter_space.json`: typed parameter bounds
- `constraints.json` (optional): hard-feasibility rules for `suggest`
- `objective_schema.json`: primary objective, optional secondary objectives,
  and optional scalarization policy
- `experiment_interface.md`: async I/O contract
- `examples/`: sample success/failure payloads and run script
- `schemas/`: compatibility copies of shared schemas (`ingest_payload`,
  `search_space`, `suggestion_payload`)
- `scripts/`: synthetic objective helper
- `tests/`: `pytest` CLI and state-flow coverage

## Notes

- JSON (`.json`) is the required contract format.
- `feature_flags` exists in all templates; preview flags are reserved scaffolding
  and no-op in the current file-backed runtime.
- This demo variant intentionally leaves out BoTorch.
- Mutating commands use an exclusive lock (`state/.looptimum.lock`) with
  wait+timeout behavior and optional `--fail-fast`.
- `suggest` keeps count-1 output backward compatible, supports locked batches
  via `--count N` / `bo_config.batch_size`, and can emit worker-oriented
  JSONL with `--jsonl`.
- `max_pending_trials`, when configured, rejects the whole requested batch
  before pending state is mutated.
- `import-observations` supports strict and permissive warm-start seeding;
  permissive runs write reports under `state/import_reports/`.
- `export-observations` writes canonical JSONL or flat CSV rows from
  authoritative state for future campaign seeding.
- optional worker leases add `lease_token` to suggestions and require matching
  `--lease-token` on `heartbeat` / `ingest`.
- Runtime artifacts include `state/event_log.jsonl` and per-trial manifests in
  `state/trials/trial_<id>/manifest.json`.
- Archive-management commands cover inventory (`list-archives`), rollback
  (`restore`), and retention cleanup (`prune-archives`).
- Acquisition decisions include `surrogate_backend` and feasibility metadata in
  `state/acquisition_log.jsonl`.
- Multi-objective manifests and reports preserve raw `objective_vector` values,
  scalarized ranking metadata, and Pareto summaries.

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
