# Use Cases and Fit

This document describes where the Looptimum templates are a strong fit, how to frame the optimization problem, and where the approach is a weaker fit.

## What the System Optimizes

The templates are designed for expensive black-box evaluations where:

- you can define a scalar objective
- each evaluation is costly enough that sample efficiency matters
- you can run evaluations programmatically (function, script, API, or job wrapper)

## Strong-Fit Use Cases

### 1. Simulations (CFD, FEA, physics models, system simulators)

Typical pattern:

- parameters configure a simulation setup
- a simulation is executed
- outputs are parsed into one scalar objective (or scalarized)

Examples of objectives:

- minimize error to target behavior
- minimize runtime subject to quality constraints
- maximize efficiency / yield proxy

Why this repo fits:

- expensive evaluations
- failure handling matters
- resumability matters (especially for long-running jobs)

### 2. Model Calibration / Parameter Estimation

Typical pattern:

- parameters define a model configuration
- model outputs are compared against observed data
- mismatch/error metric becomes the scalar objective

Examples:

- minimize RMSE / MAE / weighted loss
- minimize calibration residual under constraints

Why this repo fits:

- black-box calibration loops are often expensive
- restartable local state is useful for long campaigns

### 3. Black-Box ML Tuning (Hyperparameters / Pipelines)

Typical pattern:

- parameters configure training pipeline settings
- a training/evaluation run executes
- validation metric + penalties are converted into a scalar objective

Examples:

- maximize validation score
- minimize validation loss + runtime penalty
- maximize quality under memory/runtime constraints

Why this repo fits:

- can wrap existing training scripts without deep refactoring
- supports subprocess/CLI integration pattern

### 4. Process Optimization (Manufacturing / Industrial / Operations)

Typical pattern:

- parameters define process settings or recipe values
- process outcome is measured or simulated
- output quality/cost/yield is scalarized

Examples:

- maximize yield
- minimize defect rate
- minimize cost while meeting quality thresholds

Why this repo fits:

- explicit constraints and invalid regions are common
- auditability and reproducibility are often important

### 5. Scheduling / Resource Allocation (With a Scalar Objective)

Typical pattern:

- parameters control scheduling heuristics or resource allocation settings
- scheduler/simulator runs
- throughput, lateness, cost, or utilization is scalarized

Examples:

- minimize weighted lateness
- maximize throughput subject to SLA penalties
- minimize cost + penalty score

Why this repo fits:

- useful when each evaluation requires nontrivial simulation or replay
- file-backed integration can wrap existing schedulers

### 6. Pricing and Marketing Optimization (Expensive Evaluations / Simulations)

Typical pattern:

- parameters set campaign/pricing controls
- evaluation is a simulation, historical replay, or expensive model
- KPI(s) are scalarized into one objective

Examples:

- maximize profit proxy
- maximize conversion with spend penalty
- maximize LTV proxy under CAC constraints

Why this repo fits:

- works well for simulation/replay-driven evaluations
- supports constrained optimization framing via penalties and failure handling

## How to Frame a Use Case for This Repo

A strong integration usually has:

1. A finite parameter set with clear types and bounds/choices
2. A programmatic way to run one evaluation
3. A scalar objective (or a clear scalarization rule)
4. A practical evaluation budget
5. A failure/invalid-run policy

Use `intake.md` to capture this before pilot work.

## Common Challenges (Normal, Not Show-Stoppers)

- Objective is multi-metric and needs scalarization
- Some parameter regions are invalid
- Evaluations fail intermittently
- Runtime varies significantly
- The system is noisy/stochastic

These are common and usually manageable with a clear integration contract and failure policy.

## Weaker-Fit / Not-Ideal Cases

This repo may be a weaker fit if:

- the problem has cheap gradients and standard gradient methods are better
- the search space is extremely high-dimensional without structure
- the evaluation loop needs real-time decisions at very low latency
- no scalar objective can be defined or agreed upon

## Pilot Scoping Guidance (Pragmatic)

For a first pilot:

- choose a bounded parameter subset (not every possible knob)
- define one primary objective
- document hard constraints and failure behavior
- set a realistic initial budget (for example, 10-30 evaluations)
- review and refine after the pilot

## Related Docs

- `docs/integration-guide.md`
- `docs/faq.md`
- `intake.md`
- `docs/pricing-tiers.md`
