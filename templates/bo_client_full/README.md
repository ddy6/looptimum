# bo_client_full

Single-stage optimization harness with an optional BoTorch GP backend behind a feature flag.

## Backends

- `rbf_proxy`: always available, no extra dependencies
- `botorch_gp`: optional (`SingleTaskGP`, default training via `fit_gpytorch_mll`)

## Files

- `run_bo.py`: `suggest`, `ingest`, `status`, `demo`, `cancel`, `retire`,
  `heartbeat`, `report`, `validate`, `doctor`
- `bo_config.json`: includes `feature_flags.enable_botorch_gp`
- `parameter_space.json`: typed parameter bounds
- `objective_schema.json`: objective direction and handling
- `schemas/`: compatibility copy of ingest schema (canonical schemas live under `templates/_shared/schemas/`)
- `experiment_interface.md`: async I/O contract
- `examples/`: sample success/failure result payloads and run script
- `tests/`: `pytest` suite for CLI/state behavior

## Enable BoTorch GP

```bash
python3 run_bo.py suggest --enable-botorch-gp
```

Or set `feature_flags.enable_botorch_gp` to `true` in config.

## Notes

- JSON (`.json`) is the canonical contract format.
- Legacy `.yaml`/`.yml` files require compatibility mode:
  `LOOPTIMUM_YAML_COMPAT_MODE=1` (optional allowlist via
  `LOOPTIMUM_YAML_COMPAT_ALLOWLIST`).
- YAML usage emits deprecation warnings and is scheduled for removal in
  `v0.4.0`; full YAML parsing requires `pip install "looptimum[yaml]"`.
- Acquisition logs record selected backend and fallback reason when applicable.
- Mutating commands use an exclusive lock (`state/.looptimum.lock`) with
  wait+timeout behavior and optional `--fail-fast`.
- Runtime artifacts include `state/event_log.jsonl`, per-trial manifests in
  `state/trials/trial_<id>/manifest.json`, and explicit report outputs.

## Example Payloads

- `examples/example_results.json`: success (`status: "ok"`)
- `examples/example_results_timeout.json`: non-`ok` sample
  (`status: "timeout"`, `objective: null`, `penalty_objective`)
- `examples/example_run.sh [results-file]`: run script; optional arg selects
  which sample payload to ingest

## Cross-Repo References

- Tiny end-to-end objective loop:
  `examples/toy_objectives/03_tiny_quadratic_loop/`
- Golden decision-trace sample:
  `docs/examples/decision_trace/golden_acquisition_log.jsonl`
- Text transcript of `suggest -> evaluate -> ingest -> status`:
  `docs/examples/decision_trace/cli_transcript.md`
