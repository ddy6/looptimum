# Toy Objectives

This folder provides small, runnable examples that plug into
`client_harness_template/run_one_eval.py`.

They are intentionally simple and dependency-lightweight, but they are
positioned as integration-pattern references:

1. `01_python_function/`: direct in-process Python function (`evaluate(params) -> float`)
2. `02_subprocess_cli/`: wrapper calls a subprocess/CLI worker, parses raw
   metrics, computes scalar objective

These examples mainly answer:

- "How do I connect my evaluator to the optimization file contract?"
- "How do I produce one scalar objective for `ingest`?"
- "How do I handle subprocess outputs and failures?"

## Common Input

All examples can be run using the checked-in suggestion snapshot:

- `docs/examples/state_snapshots/suggestion_1.json`

## Common Runner

Use the shared adapter:

```bash
python3 client_harness_template/run_one_eval.py \
  <suggestion.json> \
  <result.json> \
  --objective-module <path/to/objective.py> \
  --objective-name loss
```

## Quick Try (Both Examples)

```bash
python3 client_harness_template/run_one_eval.py \
  docs/examples/state_snapshots/suggestion_1.json \
  /tmp/toy_py_result.json \
  --objective-module examples/toy-objectives/01_python_function/objective.py \
  --objective-name loss \
  --print-result
python3 client_harness_template/run_one_eval.py \
  docs/examples/state_snapshots/suggestion_1.json \
  /tmp/toy_cli_result.json \
  --objective-module examples/toy-objectives/02_subprocess_cli/objective.py \
  --objective-name loss \
  --print-result
```

## Why These Examples

- They validate the `client_harness_template` flow without requiring special infrastructure.
- They cover a progression from simplest integration to a more realistic wrapper pattern.
- Treat them as copy-and-adapt templates, not performance benchmarks.

## Suggested Reading Order

1. `01_python_function/` (simplest possible integration)
2. `02_subprocess_cli/` (separate executable + parsing + failure mapping)
3. Later advanced examples (domain-specific, environment-heavy)
