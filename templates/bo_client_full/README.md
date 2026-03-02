# bo_client_full

Single-stage optimization harness with an optional BoTorch GP backend behind a feature flag.

## Backends

- `rbf_proxy`: always available, no extra dependencies
- `botorch_gp`: optional (`SingleTaskGP`, default training via `fit_gpytorch_mll`)

## Files

- `run_bo.py`: `suggest`, `ingest`, `status`, `demo`
- `bo_config.yaml`: includes `feature_flags.enable_botorch_gp`
- `parameter_space.yaml`: typed parameter bounds
- `objective_schema.yaml`: objective direction and handling
- `experiment_interface.md`: async I/O contract
- `tests/`: `pytest` suite for CLI/state behavior

## Enable BoTorch GP

```bash
python3 run_bo.py suggest --enable-botorch-gp
```

Or set `feature_flags.enable_botorch_gp` to `true` in config.

## Notes

- `.yaml` files use JSON syntax (valid YAML subset).
- Acquisition logs record selected backend and fallback reason when applicable.
