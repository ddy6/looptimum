# Example 1: Direct Python Function

Pattern:

- `client_harness_template/run_one_eval.py` loads `objective.py`
- `objective.py:evaluate(params)` runs in-process and returns a scalar objective (`float`)

This is the simplest integration pattern and a good starting point when your evaluator is already Python-callable.

## Run

```bash
python3 client_harness_template/run_one_eval.py \
  docs/examples/state_snapshots/suggestion_1.json \
  /tmp/example1_result.json \
  --objective-module examples/toy-objectives/01_python_function/objective.py \
  --objective-name loss \
  --print-result
```

## Notes

- Returns a numeric scalar directly (`status` defaults to `ok` in the adapter)
- Uses a deterministic toy objective based on `x1` and `x2`
