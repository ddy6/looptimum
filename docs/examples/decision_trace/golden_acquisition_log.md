# Golden Acquisition Log (Deterministic Sample)

This sample provides a compact decision-trace file with warmup and
surrogate-acquisition records.

File:

- `docs/examples/decision_trace/golden_acquisition_log.jsonl`

## Exact Command Used

Run from repo root:

```bash
python3 examples/toy_objectives/03_tiny_quadratic_loop/run_tiny_loop.py \
  --steps 8 \
  --write-acquisition-log docs/examples/decision_trace/golden_acquisition_log.jsonl
```

Generation context:

- template: `templates/bo_client_demo`
- seed: `17` (from `bo_config.json`)
- objective module:
  `examples/toy_objectives/03_tiny_quadratic_loop/objective.py`

## What the 8 Records Show

1. Records `trial_id=1..6` are warmup (`strategy: "initial_random"`).
2. Records `trial_id=7..8` are surrogate scoring
   (`strategy: "surrogate_acquisition"` with UCB fields).

## Field Annotations

Top-level fields per line:

- `trial_id`: monotonic trial identifier from `suggest`
- `timestamp`: epoch seconds when decision was logged
- `decision`: strategy metadata for suggestion selection

`decision` fields:

- `strategy`:
  - `initial_random` during warmup window
  - `surrogate_acquisition` after warmup
- `acquisition_type`: heuristic used in acquisition mode (`ucb` here)
- `predicted_mean`: surrogate mean estimate for candidate
- `predicted_std`: uncertainty proxy for candidate
- `acquisition_score`: ranking score used to pick emitted candidate

## Usage

Use this file to validate parser expectations, audit-log ingestion paths, and
human debugging workflows against a stable, known-good sample.
