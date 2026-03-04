# bo_client_full

Single-stage optimization harness with an optional BoTorch GP backend behind a feature flag.

## Backends

- `rbf_proxy`: always available, no extra dependencies
- `botorch_gp`: optional (`SingleTaskGP`, default training via `fit_gpytorch_mll`)

## Files

- `run_bo.py`: `suggest`, `ingest`, `status`, `demo`
- `bo_config.json`: includes `feature_flags.enable_botorch_gp`
- `parameter_space.json`: typed parameter bounds
- `objective_schema.json`: objective direction and handling
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
- Legacy `.yaml`/`.yml` files still load with deprecation warnings; full YAML
  parsing requires `pip install "looptimum[yaml]"`.
- Acquisition logs record selected backend and fallback reason when applicable.
