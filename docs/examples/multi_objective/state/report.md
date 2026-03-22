# Looptimum Report

- Generated at: `1774146359.1225019`
- Objective: `loss` (minimize)
- Best ranking target: `scalarized`
- Scalarization policy: `weighted_sum`
- Objectives: `["loss", "throughput"]`
- Observations: `2`
- Pending: `0`
- Failure rate: `0.0000`

## Best

- trial_id: `1`
- objective_name: `scalarized`
- objective_value: `-0.85`
- scalarization_policy: `weighted_sum`
- objective_vector: `{"loss": 0.3, "throughput": 2.0}`
- params: `{"x1": 0.18126486333322134, "x2": 0.6614305484952444}`

## Pareto Front

- count: `2`
- trial_ids: `[1, 2]`
- trial `1`: objective=0.3, scalarized=-0.85, vector={"loss": 0.3, "throughput": 2.0}
- trial `2`: objective=0.2, scalarized=-0.4, vector={"loss": 0.2, "throughput": 1.0}

## Top Trials

- trial `1`: objective=0.3, scalarized=-0.85, status=ok
- trial `2`: objective=0.2, scalarized=-0.4, status=ok

## Runtime Summary

No runtime_seconds fields found in observations.
