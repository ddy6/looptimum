# Phase 8 Benchmark Case Study

This case study is generated directly from benchmark summary artifacts.

## Objective

- Objective id: `tiny_quadratic`
- Description: Canonical deterministic pseudo-noisy quadratic objective used in the tiny loop demo.
- Direction: `minimize`

## Benchmark Protocol

- Fixed budget per seed: `20`
- Seed count: `10`
- Canonical metric: `best_objective_at_fixed_budget`

## Outcome Summary

- Looptimum median best objective: `0.030878`
- Random-search median best objective: `0.015824`
- Median improvement vs random: `-0.015054`
- Win rate vs random: `30.00%`

## Reliability Signal

- Failure rate (best-seed exemplar run): `0.00%`

## Best Config Excerpt

- Seed: `67`
- Best objective: `0.011409`
- Params: `{"x1": 0.32375334582076565, "x2": 0.6200294852155447}`

## Traceability

- Source summary artifact: `benchmarks/summary.json`
