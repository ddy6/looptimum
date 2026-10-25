# Reference comparison readout

The declared reference attempted 200 campaigns: five policies, four synthetic
workloads, ten seeds, and 12 evaluations per campaign. **199 campaigns
completed; the full acceptance gate is unmet.** One existing direct-GP
campaign could not fit its model before evaluation 12. All 40 model-guided
Ax campaigns completed their 480 evaluations. Across all policies, 2399 of
the planned 2400 evaluations were allocated. Failed campaigns were retained;
no selective retries or nine-seed aggregate replaced the incomplete cell.

See the [declared protocol](README.md), [complete generated table](report.md),
and [per-seed summary](summary.json). The legacy golden benchmark assets
remain unchanged.

## Quality at the fixed budget

Primary metric is latent regret of the configuration selected by minimum
observed loss. Lower is better. Values below are medians across ten seeds.
For the noisy workload this uses the underlying objective, not an unusually
favorable noise draw. Full quartiles and paired differences are in the summary.

| Workload | Random | Direct GP | Model-guided Ax | Ax wins versus random |
|---|---:|---:|---:|---:|
| Smooth quadratic | 0.028259 | 0.000707 | 0.000294 | 10/10 |
| Multimodal | 0.312209 | 0.242900 | 0.257686 | 8/10 |
| Mixed pipeline | 8.271233 | incomplete | 8.226061 | 5/10 |
| Noisy quadratic | 0.052981 | 0.026055 | 0.013681 | 9/10 |

Ax produced substantially lower regret on the smooth and noisy quadratics
in this small reference. The direct GP had the lowest median on the
multimodal function; its interval overlapped Ax's. Mixed-pipeline medians
were nearly equal for Ax and random, with a wide paired-difference interval
and a slightly negative median paired improvement. These data do not establish
a pipeline advantage. Proxy and Sobol-only results are included in the full
table even where they were weaker.

These are synthetic sequential experiments with different initialization
and acquisition policies. Ten seeds provide descriptive evidence, not a
significance test, a causal attribution to the surrogate alone, or evidence
of improved performance on a production training or ETL workload.

## Cost and environment

Collection used Python 3.11.12 on macOS 26.2 ARM64, Ax 1.3.1,
BoTorch 0.18.1, Torch 2.14.1, GPyTorch 1.15.2, NumPy 2.4.6, and
SciPy 1.17.1. Two independent campaigns ran concurrently with one numerical
thread per controller. Every suggestion and ingest used a fresh process;
wall times include imports and serialization, with shared OS caches.

Model-guided Ax's workload-level p95 suggestion time was about 3.19–3.42s,
compared with about 1.71–1.73s for completed direct-GP cells and 0.12–0.17s
for random/proxy policies. Sobol-only Ax still paid the heavy import cost,
at about 3.00–3.03s. The largest completed-campaign process RSS was
428.5 MiB for Ax. This is the OS child high-water statistic, not simultaneous
controller-plus-worker memory or an aggregate host requirement.

No completed campaign exceeded the declared 60s p95/4096 MiB limits. Under
the explicit one-hour-per-evaluation cost model, measured controller wall
time was at most 0.093% of modeled campaign time among completed campaigns.
No one-hour evaluations were actually run. The same overhead can matter
much more for cheap objectives. Raw per-command CPU/RSS/wall records are
retained locally; aggregate and per-seed CPU costs are in the summary.

The resource and phase gates depend on complete campaign coverage. Their
"not established" status in the generated report reflects the incomplete
reference, rather than a measured resource-limit breach in the 199 completed
campaigns.

## Numerical failure and release follow-up

Pipeline / direct GP / seed 97 completed 11 evaluations. Before allocating
trial 12, BoTorch reported repeated SciPy optimization failures followed by
`All attempts to fit the model have failed.` Canonical history remained
intact with no new pending trial. This was a suggestion/model-fit failure,
not an evaluator failure or a measured low-quality result. It affected one
of 200 attempted campaigns and one of ten campaigns in that comparator cell.

The [bounded diagnostic fixture](gp_pipeline_seed97_failure.json) preserves
the synthetic observations, settings, failed fit seed, and environment without
local paths, timestamps, or lease tokens. It is a diagnostic case, not an
expected-failure assertion across all platforms. To attempt a fresh isolated
reproduction from the repository root in the recorded environment:

```bash
python -m benchmarks.backend_comparison.run \
  --output-dir /tmp/looptimum-gp-pipeline-diagnostic \
  --workloads pipeline --backends gp --seeds 97 \
  --budget 12 --initialization 4 --workers 1
```

The pre-1.0 release follow-up is to diagnose this numerical case, decide and
test the supported GP failure behavior, and obtain a fresh complete reference
under an explicit protocol. Preserve this failed reference. No optimizer
defaults, acceptance thresholds, or evaluation budgets were changed to turn
the result green.

After collection, reporting was updated only to redact local prefixes from
published error text and explain incomplete gates. Execution hashes remain
in the original protocol; current report-analysis hashes are recorded
separately. Numerical results and raw receipts were not changed or rerun.
