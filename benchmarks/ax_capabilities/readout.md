# Ax capability evidence: original bounded run

The original matrix completed **39 of 40 campaigns and 958 of 960 invocation slots**. One typed-conditional Ax campaign (seed 41) reached its 600-second wall limit after 22 of 24 evaluations. Original strict completion/time gates remain unmet; this is qualified incomplete evidence. No failed case was rerun, and no seed, reference, code or dependency was retuned.

The [complete summary](summary.json) retains every per-seed result, source/environment/protocol hash and failed case. The [independent audit](audit.json) recomputes counts, inclusive outcome feasibility, scalar latent regret and hypervolume with zero evaluator calls; its sole error is the retained incomplete campaign. Raw command/trial/controller receipts are retained in the local execution handoff.

| Workload (first / second arm) | Complete pairs | Median paired difference | Range |
| --- | --- | --- | --- |
| noisy_scalar (reported_sem / unknown_sem) | 5/5 | 0.000156556105 | [-0.000742250411, 0.00593729566] |
| typed_conditional (ax / random) | 4/5 | 0.0726347778 | [0.0446118853, 0.0880308682] |
| measured_scalar (ax / random) | 5/5 | 0.0789754071 | [0.0524635594, 0.122687395] |
| pareto_tradeoff (ax / random) | 5/5 | 0.164194086 | [0.106432259, 0.20812621] |

Positive differences favor the first arm: second-minus-first feasible latent simple regret for scalar workloads, first-minus-second feasible observed hypervolume for Pareto. The incomplete typed seed 41 is excluded from paired fixed-budget comparisons; its 22-slot result remains visible. Five synthetic paired seeds do not establish general superiority.

All 958 attempted evaluations completed successfully. Every public candidate was valid; there were no unconfigured repeats or partial allocations. All Ax campaigns reached MBM generation. All 25 actual Ax restore receipts passed exact trial-ID and typed-choice checks and absolute float tolerance 1e-7, including the failed case at trial 13. The original aggregate `seeded_restore` gate is false because its failed-case result omits that saved checkpoint; the original summary is preserved.

The failed case recorded 42 generation attempts for 22 accepted proposals before its last command. Suggestion 21 took 53.65s, suggestion 22 took 29.46s, and suggestion 23 was stopped after 106.84s when the remaining campaign wall time expired. Its final receipt reports 600.014s including process-group cleanup, with 22 canonical observations, next trial ID 23, no pending work and no partial allocation. The last worker’s internal attempt count is unavailable.

The measured source passed 946 lean tests (37 optional-stack skips), 185 real Ax tests with no skips, and a current-source six-slot CI smoke plus independent audit. An earlier 32-slot all-workload correctness smoke passed before later reporting/rebuild hardening; its original source hashes are retained. Correctness smoke and required remote OS/Python CI are separate from this incomplete full matrix.

## Bounded follow-up under an explicit time amendment

A subsequent one-shot continuation permitted up to 300 additional seconds and
only the two remaining evaluator calls, keeping the total cap at 960. Source,
configuration, environment, seed and reference stayed unchanged. The original
600-second failure and all original raw results were preserved.

The [follow-up receipt](continuation.json) records a generation failure after
107.15s: all eight internal Ax proposals violated `forbidden_combinations[0]`.
The configured eight-attempt limit was reached before a valid public candidate
was available. No new trial was allocated and **zero additional evaluator calls**
were made. Both canonical state copies retain 22 observations, next ID 23 and no
pending work; their bytes and the original evidence are unchanged.

The matrix therefore remains 39/40 complete and 958/960 slots. Increasing campaign
time does not change the generation-attempt limit. The selected bounded
post-filtering mechanism can stall on a forbidden branch; any exact generation
repair requires its own source/design and validation evidence. No failed attempt
was automatically retried, and the original or amended completion gates are
not reported as passed.

## Restore receipt reconciliation and generation repair

A later [read-only reconciliation](restore-reconciliation.json) independently
compared all 25 saved restore checkpoints with the original canonical observation
and restore-shadow pending trial. All trial IDs and typed choices agree, with
absolute float tolerance `1e-7`. The sole omitted aggregate checkpoint is
typed-conditional Ax seed 41. This used zero evaluator calls and leaves the
original summary, strict completion flags and failed case unchanged. The runner
now retains a completed checkpoint even if a later command fails.

Repaired source prunes eligible forbidden finite choices from the Ax generation
space by proving their activation context. Exhaustive small-space equivalence
tests and real modeled generation/restore for both controllers at seeds 17 and 41
pass. This is separate correctness evidence, not a completed benchmark rerun.
The [proposed repaired-source protocol](repaired-validation.md) requires a new
explicit execution budget; no repaired matrix has started.
