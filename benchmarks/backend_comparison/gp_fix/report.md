# Optional backend comparison

Synthetic fixed-budget evidence. Interpret results within the limitations below.

Protocol: declared ten-seed reference.
Budget: 12 evaluations per seed; seeds: [17, 29, 41, 53, 67, 79, 97, 113, 131, 149].
Initialization: 4; concurrent campaigns: 2.
Modeled evaluator cost: 3600.0 seconds per evaluation; no actual sleep.

| Workload | Backend | Seeds | Selected latent regret, median [Q25, Q75] | Suggest p95, s | Peak process MiB | Fit recoveries |
|---|---|---:|---:|---:|---:|---:|
| smooth_quadratic | random | 10 | 0.028259 [0.01716, 0.044845] | 0.124 | 36.5 | 0 |
| smooth_quadratic | proxy | 10 | 0.032394 [0.018272, 0.045689] | 0.143 | 36.5 | 0 |
| smooth_quadratic | gp | 10 | 0.00070727 [0.00027238, 0.0008915] | 1.738 | 309.0 | 0 |
| smooth_quadratic | ax_sobol | 10 | 0.021338 [0.0090906, 0.031178] | 3.046 | 412.0 | 0 |
| smooth_quadratic | ax | 10 | 0.00029361 [0.00013463, 0.00047324] | 3.242 | 426.7 | 0 |
| multimodal | random | 10 | 0.31221 [0.26653, 0.40101] | 0.123 | 36.3 | 0 |
| multimodal | proxy | 10 | 0.2981 [0.13175, 0.47507] | 0.141 | 36.5 | 0 |
| multimodal | gp | 10 | 0.2429 [0.15665, 0.28326] | 1.748 | 308.2 | 0 |
| multimodal | ax_sobol | 10 | 0.3367 [0.20285, 0.36812] | 3.024 | 411.8 | 0 |
| multimodal | ax | 10 | 0.25769 [0.19782, 0.34153] | 3.238 | 426.9 | 0 |
| pipeline | random | 10 | 8.2712 [5.3132, 11.419] | 0.122 | 36.4 | 0 |
| pipeline | proxy | 10 | 8.5401 [4.2964, 12.07] | 0.167 | 36.5 | 0 |
| pipeline | gp | 10 | 7.4823 [3.3782, 11.832] | 1.985 | 308.7 | 1 |
| pipeline | ax_sobol | 10 | 8.924 [6.6911, 9.3655] | 3.050 | 412.4 | 0 |
| pipeline | ax | 10 | 8.2261 [7.3928, 9.8503] | 3.502 | 428.0 | 0 |
| noisy_quadratic | random | 10 | 0.052981 [0.030203, 0.072897] | 0.123 | 36.7 | 0 |
| noisy_quadratic | proxy | 10 | 0.048705 [0.03655, 0.074723] | 0.143 | 36.5 | 0 |
| noisy_quadratic | gp | 10 | 0.026055 [0.019191, 0.032494] | 1.731 | 309.2 | 0 |
| noisy_quadratic | ax_sobol | 10 | 0.043999 [0.015102, 0.10206] | 3.011 | 412.0 | 0 |
| noisy_quadratic | ax | 10 | 0.013681 [0.008105, 0.018105] | 3.229 | 426.4 | 0 |

## Acceptance gates

- all_declared_cases_complete: pass
- paired_family_initialization: pass
- fixed_evaluation_budgets: pass
- valid_suggestions_and_backend_phases: pass
- suggestion_latency: pass
- memory: pass
- modeled_overhead: pass

## Limits

- Synthetic sequential workloads; no production or asynchronous performance claims.
- Seed-level median/IQR is descriptive; no statistical significance or universal superiority claim.
- Initialization policies differ; comparisons include their effects.
- Best observed noisy scores can be optimistic; selected latent regret is the primary quality measure.
- Fresh process overhead includes imports; OS caches and concurrent cases are shared.
- RSS is an OS child high-water mark, not simultaneous aggregate memory or GPU memory.

Full per-seed scores, observed values, CPU time, failure/repeat rates, phase counts, paired differences, source hashes, and environment versions are in summary.json.
