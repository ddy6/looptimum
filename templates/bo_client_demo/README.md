# bo_client_demo

Proxy-surrogate optimization harness (`rbf_proxy`) with explicit configuration and restartable state.

## Files

- `run_bo.py`: `suggest`, `ingest`, `status`, `demo`
- `bo_config.json`: budget, surrogate/acquisition, seed, paths
- `parameter_space.json`: typed parameter bounds
- `objective_schema.json`: objective direction and handling
- `experiment_interface.md`: async I/O contract
- `examples/`: sample success/failure payloads and run script
- `schemas/`: compatibility copy of ingest schema (canonical schemas live under `templates/_shared/schemas/`)
- `scripts/`: synthetic objective helper
- `tests/`: `pytest` CLI and state-flow coverage

## Notes

- JSON (`.json`) is the canonical contract format.
- Legacy `.yaml`/`.yml` files still load with deprecation warnings; full YAML
  parsing requires `pip install "looptimum[yaml]"`.
- This demo variant intentionally leaves out BoTorch.
