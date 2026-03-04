# Example 2: Subprocess / CLI Wrapper

Pattern:

- `client_harness_template/run_one_eval.py` loads `objective.py`
- `objective.py` writes params to a temp JSON file and launches `worker_cli.py`
- `worker_cli.py` returns raw metrics JSON via stdout
- `objective.py` computes a scalar objective (`loss`) from those metrics

This mirrors real integrations where the evaluator lives in a separate executable/script.

## Run

```bash
python3 client_harness_template/run_one_eval.py \
  docs/examples/state_snapshots/suggestion_1.json \
  /tmp/example2_result.json \
  --objective-module examples/toy-objectives/02_subprocess_cli/objective.py \
  --objective-name loss \
  --print-result
```

## Failure Handling (Demonstrated)

- `worker_cli.py` exits with code `2` for a synthetic invalid region
- `objective.py` maps that to `status: "failed"`, `objective: null`, and
  `penalty_objective`
- Other unexpected subprocess errors are re-raised so `run_one_eval.py` can apply its default failure policy
