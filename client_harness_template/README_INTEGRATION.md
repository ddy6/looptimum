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
- `objective_aws_batch_example.py`: optional example wrapper for AWS Batch-backed
  execution.
- `run_one_eval.py`: thin adapter that reads a suggestion file and writes an
  ingest-ready result JSON.
- `starterkit_queue_worker.py`, `starterkit_airflow.py`,
  `starterkit_slurm.py`: optional scheduler starters built on the same
  suggestion/result contract
- `starterkit_config.py`, `starterkit_events.py`: optional event-log sidecar
  helpers for webhook delivery
- `starterkit_tracking.py`, `starterkit_mlflow.py`,
  `starterkit_wandb.py`: optional post-hoc tracker adapters
- `aws_config.py`, `aws_executor.py`, `aws_models.py`: optional AWS Batch
  executor path and recovery sidecars.
- `aws_batch_config.example.json`: committed example config shape for the AWS path.
- `README_INTEGRATION.md`: implementation instructions and failure-mode guidance.

## Executor Selection

`run_one_eval.py` supports two executor modes:

- `--executor local`:
  default path; load `objective.py` (or `--objective-module`) and call
  `evaluate(params)`
- `--executor aws-batch`:
  bypass local `objective.py`, use `aws_executor.py`, and return canonical
  result fields from AWS Batch

AWS mode requires a JSON config path via `--aws-config` or
`LOOPTIMUM_AWS_CONFIG`. For the full AWS path, use
[`docs/aws-batch-integration.md`](../docs/aws-batch-integration.md).

## Expected Input (Suggestion)

Input comes from `run_bo.py suggest` and must preserve:

- `schema_version` (semver string)
- `trial_id`
- `params` (exact values, no rounding/reformatting)

Example:

```json
{
  "schema_version": "0.3.0",
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
  "schema_version": "0.3.0",
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
3. `status` must be one of `ok`, `failed`, `killed`, `timeout` (or legacy
   `success`, normalized to `ok` by ingest).
4. For `status: ok`, primary objective value must be numeric and finite.
5. For non-`ok` statuses, set primary objective to `null`; optional
   `penalty_objective` may be included.
6. For non-`ok` statuses, include optional `terminal_reason` (short string).

## Implement `objective.py` (Params -> Run -> Scalar Objective)

Replace `evaluate(params)` in `objective.py` so it:

1. Maps `params` keys/values into your system inputs.
2. Runs one evaluation (simulation, training job, calibration run, etc.).
3. Computes one scalar objective value.
4. Returns either:
   - a number (treated as objective value, status=`ok`), or
   - a dict like `{"objective": 0.123, "status": "ok"}` for success, or
   - a dict like
     `{"status": "failed", "objective": null, "penalty_objective": 1e12, "terminal_reason": "solver diverged"}`
     for non-`ok` outcomes

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
`objective_schema.json` (for example, `loss` + `minimize`).

`run_one_eval.py --objective-schema` requires the JSON contract file
`objective_schema.json`.

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
2. Set primary objective to `null`.
3. Optionally provide `penalty_objective` as a finite numeric penalty
   (directionally bad for your objective direction).
4. Provide `terminal_reason` as a short human-readable failure summary.
5. Keep `trial_id` and `params` unchanged.
6. Keep detailed logs in your local system logs; the ingest payload reason
   should stay concise.

Penalty guidance:

- For `minimize`: use a large value (example: `1e12`)
- For `maximize`: use a very small value (example: `-1e12`)

`run_one_eval.py` default behavior (`--on-exception failed`) writes a failed
payload automatically if `objective.py` raises.
The emitted payload includes `terminal_reason` as
`<ExceptionClass>: <message>`.
Default `penalty_objective` is direction-aware: `+1e12` for `minimize`,
`-1e12` for `maximize`.
Set direction explicitly with `--objective-direction` or provide
`--objective-schema` to auto-read direction/name from `primary_objective`.
Override the default penalty with `--failure-penalty-objective <value>`.
Legacy alias `--failure-sentinel` is still accepted with a deprecation warning.

## Resume / Idempotency Notes

- `suggest` creates a pending trial in the optimization state file.
- `ingest` only accepts results for pending trial IDs.
- Duplicate ingest for the same trial ID is idempotent:
  identical replay is accepted as a no-op; conflicting replay is rejected.
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
  --objective-schema templates/bo_client_demo/objective_schema.json
python3 templates/bo_client_demo/run_bo.py ingest \
  --project-root templates/bo_client_demo \
  --results-file /tmp/result.json
python3 templates/bo_client_demo/run_bo.py status --project-root templates/bo_client_demo
```

AWS Batch executor example:

```bash
export LOOPTIMUM_AWS_CONFIG=/path/to/aws_batch_config.json
python3 client_harness_template/run_one_eval.py \
  /tmp/suggest_stdout.txt \
  /tmp/result.json \
  --executor aws-batch \
  --objective-schema templates/bo_client_demo/objective_schema.json
```

## Starter-Kit Sidecars (Optional)

The starter-kit modules under `client_harness_template/` are convenience
wrappers around the same public Looptimum contract.

Use them when you want:

- queue-worker execution for batch suggestions
- rendered Airflow or Slurm starter assets
- an event-log-driven webhook sidecar
- post-hoc MLflow or W&B synchronization from canonical state/report files

Boundary rules:

- keep one controller responsible for `suggest`
- let workers own only the trial payload they were handed
- keep webhook delivery outside the mutating CLI path
- keep tracker adapters read-only with respect to optimizer state

Reference docs:

- [`../docs/integration-starter-kit.md`](../docs/integration-starter-kit.md)
- [`../docs/examples/starterkit/README.md`](../docs/examples/starterkit/README.md)

## Retry and Ownership Guidance

Recommended posture:

1. Do not retry `suggest` from multiple controllers against the same campaign
   root.
2. Retrying evaluation work is safe before a successful `ingest` as long as the
   suggestion payload stays unchanged.
3. If an `ingest` outcome is uncertain, inspect `status`, the pending list, and
   the trial manifest before replaying the same result payload.
4. Webhook delivery retries belong in the sidecar, not in optimizer mutation
   commands.
5. Tracker synchronization retries are safe because they do not mutate campaign
   state.

## Customization Checklist

- Set `--objective-name` (or use `--objective-schema`) to match your harness
  primary objective name.
- Implement `objective.py:evaluate(params)`.
- Pick a non-`ok` policy (`failed`/`killed`/`timeout`) and optional
  `penalty_objective` policy consistent with objective direction.
- Add any client-specific logging, retries, and timeout handling inside
  `objective.py`.
- If needed, extend your result schema and harness ingest validation in the
  template copy (optional).
