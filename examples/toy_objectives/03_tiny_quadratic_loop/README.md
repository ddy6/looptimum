# Tiny Quadratic Loop (End-to-End, <1 Minute)

This example is a deliberately boring, universal integration demo:

- deterministic "noisy quadratic" objective
- file-backed `suggest -> evaluate -> ingest -> status` loop
- no external dependencies beyond standard Python

It is intended as a trust-building quick check that the full integration
contract works end-to-end.

## Run

From repo root:

```bash
python3 examples/toy_objectives/03_tiny_quadratic_loop/run_tiny_loop.py --steps 6
```

What it does:

1. Creates an isolated temp copy of `templates/bo_client_demo`
2. Runs 6 suggest/evaluate/ingest cycles using `objective.py`
3. Prints final status JSON and the temp run path

Typical runtime is a few seconds.

## Export the Golden Acquisition Log

To regenerate the Phase 6 golden decision-trace sample:

```bash
python3 examples/toy_objectives/03_tiny_quadratic_loop/run_tiny_loop.py \
  --steps 8 \
  --write-acquisition-log docs/examples/decision_trace/golden_acquisition_log.jsonl
```

## Notes

- This example is an integration pattern reference, not a benchmark.
- Objective output is a scalar `loss` (lower is better).
- The objective includes deterministic pseudo-noise so behavior is stable while
  still looking like a realistic noisy surface.
