# Repaired-source C5 validation

**C5 benchmark gates passed:** 40/40 campaigns completed all 960/960 evaluation slots on commit `be806882df5286e983db51672f15949b790760ec`.

This is a fresh, separately authorized run under the [approved protocol](../repaired-validation.md). The original [39/40 failed matrix](../readout.md), its summary/audit and the failed one-shot continuation remain preserved. Historical use was 958 calls; this run used 960 additional calls, reaching the approved cumulative cap of **1,918**. The audits performed zero additional evaluations.

All four workloads use the same paired arms and five seeds `17,23,41,67,97`, 24 slots per campaign including six initialization slots, unchanged objective/measurement streams and references, 600-second campaign limits, 120-second numerical workers and at most two workers. No failed case was retried and no source, dependency, seed or reference was retuned during execution.

| Workload (first / second arm) | Complete pairs | Median paired difference | Range |
| --- | --- | --- | --- |
| noisy_scalar (reported_sem / unknown_sem) | 5/5 | 0.000156556105089 | [-0.000742250410961, 0.00593729565926] |
| typed_conditional (ax / random) | 5/5 | 0.0626210851126 | [0.0445973439408, 0.0880479882083] |
| measured_scalar (ax / random) | 5/5 | 0.0789754071256 | [0.052463559373, 0.122687395473] |
| pareto_tradeoff (ax / random) | 5/5 | 0.164194085822 | [0.10643225887, 0.208126209923] |

Positive differences favor the first arm: second-minus-first feasible latent simple regret for scalar workloads, first-minus-second feasible observed hypervolume for Pareto. The noisy-scalar comparison favors reported SEMs on four seeds and unknown SEMs on seed 23. These five-seed synthetic results do not establish general superiority.

## Completion, feasibility and restore checks

- All nine [runner hard gates](summary.json) pass. All 960 attempted evaluations completed; there were no invalid public candidates, unconfigured repeats, partial allocations or unexplained evaluator failures.
- The [independent metric/count audit](audit.json) passes. It recomputes raw charged slots, inclusive measured feasibility, scalar latent regret and 2D feasible hypervolume.
- The [canonical/restore/budget verification](verification.json) matches all 600 Ax observations with their raw evaluation receipts, verifies snapshot digests/configuration/version identities, and finds zero pending trials or allocation journals in all 25 Ax campaigns.
- All 25 saved seeded restore checkpoints independently match the canonical trial and restore-shadow pending trial: exact trial IDs and typed/discrete choices, absolute float tolerance `1e-7`. All Ax campaigns reached modeled MBM generation.
- Every Ax public proposal required one generation attempt. In particular, all five typed-conditional Ax campaigns completed with 24 attempts for 24 accepted proposals and zero forbidden-branch rejections. Seed 41 completed in **180.34 seconds**; the slowest campaign took **187.63 seconds**, below the 600-second cap.

The [run identity](run-identity.json) records the exact source, protocol and artifact hashes. [CI passed for the benchmarked commit](https://github.com/ddy6/looptimum/actions/runs/42077708325). These results close C5's benchmark evidence gate; package publication, intended deployment and browser/accessibility acceptance remain separate owner gates. Raw command, trial, controller and restore receipts remain retained locally.
