# Benchmarks

Phase 8 evidence anchors live in this directory.

Canonical benchmark script:

- `benchmarks/run_trial_efficiency_benchmark.py`

Canonical objective in this phase:

- `tiny_quadratic` (default)

Optional low-maintenance extension hook (not required for baseline release runs):

- `anisotropic_quadratic`

## Canonical Metric

Primary metric (gate metric):

- `best_objective_at_fixed_budget`

Protocol baseline:

- baseline policy: random search only
- seed protocol: 10 seeds
- report: median + IQR and per-seed results in generated artifacts

## Quick Run (Sanity)

```bash
python3 benchmarks/run_trial_efficiency_benchmark.py \
  --objective tiny_quadratic \
  --budget 6 \
  --seeds 17,29 \
  --write-summary /tmp/looptimum_benchmark_summary.json \
  --write-case-study /tmp/looptimum_benchmark_case_study.md
```

## Canonical Evidence Run

```bash
python3 benchmarks/run_trial_efficiency_benchmark.py \
  --objective tiny_quadratic \
  --budget 20 \
  --seeds 17,29,41,53,67,79,97,113,131,149 \
  --write-summary benchmarks/summary.json \
  --write-case-study benchmarks/case_study.md
```

## Artifact Policy

- commit compact summary artifacts only:
  - `benchmarks/summary.json`
  - `benchmarks/case_study.md`
- do not commit full raw per-seed traces by default
- raw artifacts can be generated on demand into `benchmarks/artifacts/` (git-ignored)

Example raw-artifact run:

```bash
python3 benchmarks/run_trial_efficiency_benchmark.py \
  --raw-artifacts-dir benchmarks/artifacts/phase8_full
```
