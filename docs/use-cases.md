# Use Cases and Fit

This page frames Looptimum in cross-vertical language for teams that run
expensive evaluations and need a reliable `suggest -> evaluate -> ingest` loop.

## First-Principles Fit

Looptimum is a strong fit when:

- each evaluation is costly enough that sample efficiency matters
- you can compute one scalar objective (or explicit scalarization)
- you can run evaluations programmatically (function, CLI, API, scheduler job)
- you need resumable state and auditability

## Vertical 1: Engineering and Simulation Teams

Typical users:

- simulation engineers (CFD/FEA/system models)
- platform/performance teams tuning infra knobs
- operations teams tuning scheduling/replay systems

Common tuning knobs:

- solver tolerances, mesh controls, calibration coefficients
- thread pools, cache TTLs, queue concurrency, memory limits
- scheduling weights, timeout limits, penalty coefficients

Why this is a fit:

- run costs are often high (minutes to hours)
- invalid regions and occasional failures are expected
- deterministic state and restart safety matter for long campaigns

## Vertical 2: Biotech, Lab, and Process Pipelines

Typical users:

- assay/protocol optimization teams
- lab automation and process engineering teams
- quality/yield optimization programs

Common tuning knobs:

- concentrations, temperature/time windows, mixing rates
- process recipe settings, throughput controls, quality guardrails
- analysis thresholds and pipeline parameters

Why this is a fit:

- each run consumes real time/materials
- failures and invalid outcomes need explicit tracking
- pilot planning usually requires clear budget and deliverable alignment

## Vertical 3: ML and Large-Model HPO Teams

Typical users:

- teams with expensive model training/evaluation loops
- large-model platform teams running long training or offline evaluation jobs
- teams without dedicated HPO platform ownership
- teams needing repeatable optimization in restricted environments

Common tuning knobs:

- learning rate, batch size, regularization strength
- augmentation controls, early-stopping thresholds
- runtime-cost penalties combined with quality metrics
- routing controls and dataset-mixture weights in bounded search spaces

Why this is a fit:

- can wrap existing training scripts or job schedulers
- works as an outer loop above trainer/runtime internals
- supports local/offline execution paths
- keeps optimization artifacts auditable for experiment review

## Case-Study Gallery (Equal Mainstream/Specialized Coverage)

The gallery below is intentionally balanced across mainstream and specialized
workloads. Each row states what is tuned and the scalar score fed into
`ingest`.

| Segment | Scenario | What is being optimized | Score definition (example) |
|---|---|---|---|
| Mainstream | ETL throughput vs cost | batch size, worker parallelism, retry/backoff | `cost_per_gb + latency_penalty` |
| Mainstream | API latency reliability | cache TTL, concurrency limits, timeout values | `p95_latency_ms + error_rate_penalty` |
| Mainstream | Search/recommendation calibration | relevance weights, eligibility thresholds, exploration ratio | `-relevance_metric + latency_penalty` |
| Mainstream | Build/compile performance | compiler/linker flags, optimization levels, thread counts | `binary_runtime_ms + compile_time_penalty` |
| Mainstream | Large-model training recipe tuning | learning rate, warmup ratio, gradient accumulation, weight decay | `validation_loss + runtime_penalty` |
| Specialized | CFD/meshing stability | mesh density, refinement controls, solver tolerances | `runtime_minutes + instability_penalty` |
| Specialized | Assay/protocol optimization | concentration, temperature/time windows, mixing rates | `-yield + failed_run_penalty` |
| Specialized | Battery model calibration | diffusion coefficients, degradation factors, fit constraints | `fit_error + simulation_cost_penalty` |
| Specialized | Mixture-of-experts routing design | experts-per-token, router temperature, capacity factor | `validation_loss + imbalance_penalty + latency_penalty` |
| Specialized | OpenFOAM-style meshing workflow | mesh controls, relaxation settings, solver parameters | `wall_clock_time + nonconvergence_penalty` |

## Reproducibility and Determinism Boundaries

What is reproducible with stable config/state:

- suggestion order and trial-id progression
- state-file schema and contract-level payload shape
- decision trace chronology in `acquisition_log.jsonl`

What is not fully deterministic by default:

- wall-clock timing and runtime jitter
- external evaluator stochasticity unless controlled by client
- GP backend numerics across dependency/runtime variations

Practical guidance:

- define seed policy before pilot start
- record dependency/runtime versions used during runs
- treat state files as the canonical audit source

## Common Challenges (Normal)

- multi-metric objectives that need scalarization
- invalid parameter combinations discovered during execution
- noisy/stochastic evaluations
- budget limits that require tight trial prioritization

These are expected and should be addressed through clear objective and failure
policy design.

## Weaker-Fit Cases

Looptimum is usually not the best choice when:

- objective evaluations are cheap and simple sweeps are sufficient
- gradients are reliable and gradient methods are clearly better
- search space is extremely high-dimensional without structure
- no scalar objective can be defined or agreed

## Pilot Scoping Guidance

For first pilot execution:

1. Start with a bounded subset of high-leverage parameters.
2. Freeze one primary objective and failure policy.
3. Run 10-30 evaluations for initial learning.
4. Review results, then expand bounds/variables only if needed.

## Related Docs

- `docs/integration-guide.md`
- `docs/operational-semantics.md`
- `docs/search-space.md`
- `docs/decision-trace.md`
- `docs/pilot-checklist.md`
- `docs/faq.md`
- `intake.md`
