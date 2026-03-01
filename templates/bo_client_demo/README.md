# bo_client_template (Demo)

Proxy-surrogate optimization harness (`rbf_proxy`) with explicit configuration and restartable state.

## Files

- `run_bo.py`: `suggest`, `ingest`, `status`, `demo`
- `bo_config.yaml`: budget, surrogate/acquisition, seed, paths
- `parameter_space.yaml`: typed parameter bounds
- `objective_schema.yaml`: objective direction and handling
- `experiment_interface.md`: async I/O contract
- `examples/`: sample payload and run script
- `schemas/`: result payload JSON schema
- `scripts/`: synthetic objective helper
- `tests/`: `pytest` CLI and state-flow coverage

## Notes

- `.yaml` files use JSON syntax (valid YAML subset) to avoid parser dependencies.
- This demo variant intentionally leaves out BoTorch.
