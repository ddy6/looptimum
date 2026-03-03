# Client Integration Template (`client_harness_template`)

This folder is a minimal bridge from optimization suggestions to your real evaluation setup.

The optimization harness (`run_bo.py`) is file-backed:

1. `suggest` emits a JSON suggestion (`trial_id`, `params`)
2. Your runner evaluates those params in your environment
3. Your runner writes a result JSON payload
4. `ingest` consumes that result payload

## Files

- `objective.py`: client-fill stub. Replace `evaluate(params)` with your real
  evaluation code.
- `run_one_eval.py`: thin adapter that reads a suggestion file and writes an
  ingest-ready result JSON.
- `README_INTEGRATION.md`: implementation instructions and failure-mode guidance.

## Expected Input (Suggestion)

Input comes from `run_bo.py suggest` and must preserve:

- `trial_id`
- `params` (exact values, no rounding/reformatting)

Example:

```json
{
  "trial_id": 3,
  "params": {
    "x1": 0.31,
    "x2": 0.72
  },
  "suggested_at": 1738886400.0
}
```

`run_one_eval.py` accepts either:

- a pure suggestion JSON file, or
- raw `suggest` stdout (it strips trailing non-JSON lines if present)

## Expected Output (Result Payload for `ingest`)

Minimum compatible payload:

```json
{
  "trial_id": 3,
  "params": {
    "x1": 0.31,
    "x2": 0.72
  },
  "objectives": {
    "loss": 0.1182
  },
  "status": "ok"
}
```

Required compatibility rules:

1. `trial_id` must exactly match the suggestion.
2. `params` must exactly match the suggestion.
3. Objective value must be numeric and finite.
4. `status` should be `ok` or `failed`.

## Implement `objective.py` (Params -> Run -> Scalar Objective)

Replace `evaluate(params)` in `objective.py` so it:

1. Maps `params` keys/values into your system inputs.
2. Runs one evaluation (simulation, training job, calibration run, etc.).
3. Computes one scalar objective value.
4. Returns either:
   - a number (treated as objective value, status=`ok`), or
   - a dict like `{"objective": 0.123, "status": "ok"}`

Example skeleton pattern:

```python
def evaluate(params):
    # 1) Map params into your run inputs
    # 2) Execute one run (local process, API call, scheduler submit+wait, etc.)
    # 3) Parse outputs / metrics
    # 4) Return a scalar objective (lower is better if objective direction is minimize)
    return objective_value
```

## Objective Direction (Minimize vs Maximize)

The optimization harness objective direction is defined in
`objective_schema.yaml` (for example, `loss` + `minimize`).

Your integration must return the raw scalar in the same direction convention
expected by the harness.

- If the harness is minimizing `loss`, return lower-is-better values directly.
- If the harness is maximizing `score`, return higher-is-better values directly.

Do not negate/invert values unless you intentionally changed the harness objective definition.

## Failure Modes (Recommended Handling)

When an evaluation fails, still produce a result payload so the optimization
loop can continue and the failure is recorded.

Common failure modes include:

- invalid parameter region / infeasible configuration
- solver crash / non-convergence
- timeout / runtime limit exceeded
- missing output files / parse failure
- infrastructure/transient errors
  (node preemption, network, scheduler issues)

Recommended policy:

1. Return `status: "failed"`.
2. Provide a finite sentinel objective value that is directionally bad.
3. Keep `trial_id` and `params` unchanged.
4. Log detailed error context in your local system logs
   (not required in the ingest payload).

Sentinel guidance:

- For `minimize`: use a large value (example: `1e12`)
- For `maximize`: use a very small value (example: `-1e12`)

`run_one_eval.py` default behavior (`--on-exception failed`) writes a failed
payload automatically if `objective.py` raises.
Default sentinel is direction-aware: `+1e12` for `minimize`, `-1e12` for
`maximize`.
Set direction explicitly with `--objective-direction` or provide
`--objective-schema` to auto-read direction/name from `primary_objective`.

## Resume / Idempotency Notes

- `suggest` creates a pending trial in the optimization state file.
- `ingest` only accepts results for pending trial IDs.
- Duplicate ingest for the same trial ID is rejected.
- Param mismatches are rejected.

Practical rule: treat suggestion JSON as immutable and pass it through unchanged.

## One-Evaluation Command (Programmatic, File-Based)

From repo root, using a docs snapshot suggestion as an example:

```bash
python3 client_harness_template/run_one_eval.py \
  docs/examples/state_snapshots/suggestion_1.json \
  /tmp/result.json \
  --objective-direction minimize \
  --objective-name loss \
  --print-result
```

This currently writes a failed payload until you implement `client_harness_template/objective.py`.

## End-to-End Example (With an Optimization Template)

Example with `templates/bo_client_demo`:

```bash
python3 templates/bo_client_demo/run_bo.py suggest \
  --project-root templates/bo_client_demo \
  --json-only > /tmp/suggest_stdout.txt
python3 client_harness_template/run_one_eval.py \
  /tmp/suggest_stdout.txt \
  /tmp/result.json \
  --objective-schema templates/bo_client_demo/objective_schema.yaml
python3 templates/bo_client_demo/run_bo.py ingest \
  --project-root templates/bo_client_demo \
  --results-file /tmp/result.json
python3 templates/bo_client_demo/run_bo.py status --project-root templates/bo_client_demo
```

## Customization Checklist

- Set `--objective-name` (or use `--objective-schema`) to match your harness
  primary objective name.
- Implement `objective.py:evaluate(params)`.
- Pick a failure sentinel consistent with minimize/maximize direction.
- Add any client-specific logging, retries, and timeout handling inside
  `objective.py`.
- If needed, extend your result schema and harness ingest validation in the
  template copy (optional).
