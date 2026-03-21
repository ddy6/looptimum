# bo_client_full

Single-stage optimization harness with an optional BoTorch GP backend behind a feature flag.

## Backends

- `rbf_proxy`: always available, no extra dependencies
- `botorch_gp`: optional (`SingleTaskGP`, default training via `fit_gpytorch_mll`)

## Files

- `run_bo.py`: `suggest`, `ingest`, `status`, `demo`, `cancel`, `retire`,
  `heartbeat`, `report`, `reset`, `validate`, `doctor`
- `bo_config.json`: includes shared `feature_flags`; only
  `enable_botorch_gp` and `fallback_to_proxy_if_unavailable` are active in this
  template today
- `parameter_space.json`: typed parameter bounds
- `constraints.json` (optional): hard-feasibility rules for `suggest`
- `objective_schema.json`: objective direction and handling
- `schemas/`: compatibility copies of shared schemas (`ingest_payload`,
  `search_space`, `suggestion_payload`)
- `experiment_interface.md`: async I/O contract
- `examples/`: sample success/failure result payloads and run script
- `tests/`: `pytest` suite for CLI/state behavior

## Enable BoTorch GP

```bash
python3 run_bo.py suggest --enable-botorch-gp
```

Or set `feature_flags.enable_botorch_gp` to `true` in config.

## Notes

- JSON (`.json`) is the required contract format.
- preview flags in `feature_flags` are reserved scaffolding and no-op in the
  current file-backed runtime.
- Acquisition logs record selected backend and fallback reason when applicable.
- Constrained decisions also record feasibility metadata; all-infeasible
  attempts are logged before `suggest` exits nonzero.
- Mutating commands use an exclusive lock (`state/.looptimum.lock`) with
  wait+timeout behavior and optional `--fail-fast`.
- Runtime artifacts include `state/event_log.jsonl`, per-trial manifests in
  `state/trials/trial_<id>/manifest.json`, and explicit report outputs.

## Example Payloads

- `examples/example_results.json`: success (`status: "ok"`)
- `examples/example_results_timeout.json`: non-`ok` sample
  (`status: "timeout"`, `objective: null`, `terminal_reason`, `penalty_objective`)
- `examples/example_run.sh [results-file]`: run script; optional arg selects
  which sample payload to ingest

## Cross-Repo References

- Tiny end-to-end objective loop:
  `examples/toy_objectives/03_tiny_quadratic_loop/`
- Golden decision-trace sample:
  `docs/examples/decision_trace/golden_acquisition_log.jsonl`
- Text transcript of `suggest -> evaluate -> ingest -> status`:
  `docs/examples/decision_trace/cli_transcript.md`
