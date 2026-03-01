# Experiment Interface Contract

## Input (from `suggest`)

`run_bo.py suggest --json-only` returns:

```json
{
  "trial_id": 3,
  "params": {"x1": 0.31, "x2": 0.72},
  "suggested_at": 1738886400.0
}
```

Your experiment runner must consume `params` exactly as provided.

## Output (for `ingest`)

The external runner must write one JSON payload per completed trial:

```json
{
  "trial_id": 3,
  "params": {"x1": 0.31, "x2": 0.72},
  "objectives": {"loss": 0.1182},
  "status": "ok"
}
```

## Failure Handling

- If a trial fails, submit with `status: "failed"` and a sentinel objective value your team defines.
- Failed trials remain in observations for traceability.

## Reproducibility

- All randomness is seeded via `bo_config.yaml`.
- Resume behavior is controlled by `state/bo_state.json`.
- Every suggestion has a matching acquisition decision in `state/acquisition_log.jsonl`.
