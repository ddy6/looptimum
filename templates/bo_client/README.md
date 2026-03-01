# bo_client_template

Minimal single-stage optimization harness with explicit config, a swappable surrogate backend, and restartable JSON state.

## Files

- `run_bo.py`: driver for `suggest`, `ingest`, `status`, and `demo`.
- `bo_config.yaml`: run budget, surrogate/acquisition choices, seed, and state paths.
- `parameter_space.yaml`: explicit parameter types and bounds.
- `objective_schema.yaml`: objective direction and failure policy.
- `experiment_interface.md`: async experiment I/O contract.
- `examples/`: sample result payload and runnable command sequence.
- `schemas/`: JSON schema for result payloads.
- `scripts/`: synthetic objective helper.
- `surrogate_proxy.py`: proxy backend scoring.
- `surrogate_gp.py`: BoTorch/GPyTorch backend scoring.
- `acquisition.py`: acquisition scoring (`ei` default, `ucb` optional).

## Notes

- `.yaml` files intentionally use JSON syntax (valid YAML subset) so no extra parser dependency is required.
- State persists in `state/bo_state.json` and can be resumed between runs (no hidden service state).
- `ingest` validates payload structure via `paths.result_schema_file` and validates the primary objective value.

## Surrogate Selection

Set `surrogate.type` in `bo_config.yaml`:

- `rbf_proxy` (default): no heavy dependencies.
- `gp`: BoTorch `SingleTaskGP` with Matern 2.5 kernel.

No CLI changes are needed when switching backend.

## Reproducibility

- Random candidate generation is seeded from config/state.
- State and trial IDs are resumable via `state/bo_state.json`.
- Acquisition decisions are logged in `state/acquisition_log.jsonl`.

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
