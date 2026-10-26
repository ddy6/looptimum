# GP fit recovery: fresh reference validation

**All 200 campaigns completed all 2400 evaluations, and every declared
acceptance gate passed.** This is a fresh run with the same five policies,
four synthetic workloads, ten seeds, evaluation budget 12, initialization
budget 4, two concurrent campaign workers, and one numerical thread per
controller. The original [failed reference](../readout.md), its summary,
and diagnostic fixture remain preserved.

See the [generated comparison table](report.md) and [per-seed summary](summary.json).
The numerical policy is documented in [GP fit recovery](../../../docs/gp-fit-recovery.md).

## What changed

The ordinary and full direct-GP paths keep their existing default fitting
call. If that fitter raises `ModelFittingError`, one bounded L-BFGS-B attempt
restores the same pre-fit model and CPU RNG state and increases the line-search
allowance. It requires explicit convergence and finite values. It changes no
kernel, observations, objective, candidate pool, acquisition settings, or
evaluation budget, and introduces no proxy fallback.

Exactly **one** recovery was recorded: pipeline / ordinary GP / seed 97,
before trial 12. Its original 11 observations were identical to the retained
fixture. Recovery converged after 75 iterations with negative MLL
0.3290934376794973. The GP then selected a feasible typed configuration,
and evaluation 12 completed with a finite observed latency of 17.921363 ms.
The preceding best observation remained the campaign incumbent; the fitter
did not substitute a prediction or overwrite observed best-so-far.

Scores, selected configurations, and warmup points/observations for all
**199 previously successful campaigns matched exactly** in the fresh run.
No failed case was selectively retried into the original report. Source and
environment hashes identify the new execution independently.

## Completed comparison and resource limits

The previously incomplete direct-GP pipeline cell now includes all ten seeds:
median selected latent regret 7.4823, Q25–Q75 3.3782–11.832. Ax's pipeline
median was 8.2261 and random search's was 8.2712; these small-seed, overlapping
results do not establish a general pipeline advantage. Smooth/noisy quadratic
and multimodal quality values are unchanged from the earlier completed cells.

Across completed campaigns, maximum suggestion p95 was 3.596s, maximum
OS-reported process RSS was 428.04 MiB, and maximum modeled controller
fraction was 0.095% with the declared 3600-second evaluation cost. The gates
were 60s, 4096 MiB, and 10% respectively. RSS is a largest-process high-water
measure, not simultaneous aggregate controller/worker memory. No one-hour
jobs were actually executed.

Collection used Python 3.11.12 on macOS ARM64 with Ax 1.3.1, BoTorch 0.18.1,
Torch 2.14.1, GPyTorch 1.15.2, NumPy 2.4.6, and SciPy 1.17.1. These are
synthetic sequential comparisons, not production or asynchronous performance
evidence. Medians and quartiles across ten seeds are descriptive.

The retained numerical failure and incomplete-reference blocker are resolved
for this tested scope. Bounded recovery can still fail on other inputs and
then propagates an error without ordinary-GP trial allocation. Platform CI,
the remaining advertised-surface audit, and final 1.0.0 compatibility/release
work remain separate requirements.
