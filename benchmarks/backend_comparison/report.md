# Optional backend comparison

Synthetic fixed-budget evidence. Interpret results within the limitations below.

Protocol: declared ten-seed reference.
Budget: 12 evaluations per seed; seeds: [17, 29, 41, 53, 67, 79, 97, 113, 131, 149].
Initialization: 4; concurrent campaigns: 2.
Modeled evaluator cost: 3600.0 seconds per evaluation; no actual sleep.

| Workload | Backend | Seeds | Selected latent regret, median [Q25, Q75] | Suggest p95, s | Peak process MiB |
|---|---|---:|---:|---:|---:|
| smooth_quadratic | random | 10 | 0.028259 [0.01716, 0.044845] | 0.124 | 36.2 |
| smooth_quadratic | proxy | 10 | 0.032394 [0.018272, 0.045689] | 0.140 | 36.3 |
| smooth_quadratic | gp | 10 | 0.00070727 [0.00027238, 0.0008915] | 1.715 | 308.7 |
| smooth_quadratic | ax_sobol | 10 | 0.021338 [0.0090906, 0.031178] | 3.007 | 412.5 |
| smooth_quadratic | ax | 10 | 0.00029361 [0.00013463, 0.00047324] | 3.198 | 426.1 |
| multimodal | random | 10 | 0.31221 [0.26653, 0.40101] | 0.123 | 36.2 |
| multimodal | proxy | 10 | 0.2981 [0.13175, 0.47507] | 0.139 | 36.2 |
| multimodal | gp | 10 | 0.2429 [0.15665, 0.28326] | 1.732 | 308.8 |
| multimodal | ax_sobol | 10 | 0.3367 [0.20285, 0.36812] | 2.997 | 412.3 |
| multimodal | ax | 10 | 0.25769 [0.19782, 0.34153] | 3.241 | 427.8 |
| pipeline | random | 10 | 8.2712 [5.3132, 11.419] | 0.121 | 36.3 |
| pipeline | proxy | 10 | 8.5401 [4.2964, 12.07] | 0.166 | 36.2 |
| pipeline | gp | 9/10 | incomplete | — | — |
| pipeline | ax_sobol | 10 | 8.924 [6.6911, 9.3655] | 3.029 | 412.2 |
| pipeline | ax | 10 | 8.2261 [7.3928, 9.8503] | 3.415 | 428.5 |
| noisy_quadratic | random | 10 | 0.052981 [0.030203, 0.072897] | 0.123 | 36.2 |
| noisy_quadratic | proxy | 10 | 0.048705 [0.03655, 0.074723] | 0.140 | 36.2 |
| noisy_quadratic | gp | 10 | 0.026055 [0.019191, 0.032494] | 1.709 | 308.4 |
| noisy_quadratic | ax_sobol | 10 | 0.043999 [0.015102, 0.10206] | 3.003 | 412.0 |
| noisy_quadratic | ax | 10 | 0.013681 [0.008105, 0.018105] | 3.187 | 426.7 |

## Incomplete campaigns

The reference acceptance gate remains unmet. Failed campaigns are retained and incomplete cells have no aggregate quality result.

- pipeline / gp / seed 97: 11 evaluations allocated; ERROR: All attempts to fit the model have failed.

## Acceptance gates

- all_declared_cases_complete: FAIL
- paired_family_initialization: not established (incomplete campaign set)
- fixed_evaluation_budgets: FAIL
- valid_suggestions_and_backend_phases: not established (incomplete campaign set)
- suggestion_latency: not established (incomplete campaign set)
- memory: not established (incomplete campaign set)
- modeled_overhead: not established (incomplete campaign set)

## Limits

- Synthetic sequential workloads; no production or asynchronous performance claims.
- Seed-level median/IQR is descriptive; no statistical significance or universal superiority claim.
- Initialization policies differ; comparisons include their effects.
- Best observed noisy scores can be optimistic; selected latent regret is the primary quality measure.
- Fresh process overhead includes imports; OS caches and concurrent cases are shared.
- RSS is an OS child high-water mark, not simultaneous aggregate memory or GPU memory.

Full per-seed scores, observed values, CPU time, failure/repeat rates, phase counts, paired differences, source hashes, and environment versions are in summary.json.
