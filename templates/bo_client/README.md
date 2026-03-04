# bo_client

Minimal single-stage optimization harness with explicit config, a swappable
surrogate backend, and restartable JSON state.

## Files

- `run_bo.py`: driver for `suggest`, `ingest`, `status`, `demo`, `cancel`,
  `retire`, `heartbeat`, `report`, `validate`, and `doctor`.
- `bo_config.json`: run budget, surrogate/acquisition choices, seed, and state paths.
- `parameter_space.json`: explicit parameter types and bounds.
- `objective_schema.json`: objective direction and failure policy.
- `experiment_interface.md`: async experiment I/O contract.
- `examples/`: sample success/failure result payloads and runnable command sequence.
- `schemas/`: compatibility copy of ingest schema (canonical schemas live under `templates/_shared/schemas/`).
- `scripts/`: synthetic objective helper.
- `surrogate_proxy.py`: proxy backend scoring.
- `surrogate_gp.py`: BoTorch/GPyTorch backend scoring.
- `acquisition.py`: acquisition scoring (`ei` default, `ucb` optional).

## Notes

- JSON (`.json`) is the canonical contract format.
- Legacy `.yaml`/`.yml` files still load with deprecation warnings; full YAML
  parsing requires `pip install "looptimum[yaml]"`.
- State persists in `state/bo_state.json` and can be resumed between runs
  (no hidden service state).
- Mutating commands use an exclusive lock file (`state/.looptimum.lock`);
  default behavior waits with timeout and supports `--fail-fast`.
- `ingest` validates payload structure via `paths.ingest_schema_file` and
  validates the primary objective value.
- Runtime artifacts include `state/event_log.jsonl`, per-trial manifests in
  `state/trials/trial_<id>/manifest.json`, and explicit `report` outputs.

## Surrogate Selection

Set `surrogate.type` in `bo_config.json`:

- `rbf_proxy` (default): no heavy dependencies.
- `gp`: BoTorch `SingleTaskGP` with Matern 2.5 kernel.

No CLI changes are needed when switching backend.

## Reproducibility

- Random candidate generation is seeded from config/state.
- State and trial IDs are resumable via `state/bo_state.json`.
- Acquisition decisions are logged in `state/acquisition_log.jsonl`.
- Lifecycle and ops events are logged in `state/event_log.jsonl`.

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
