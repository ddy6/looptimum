# Direct GP numerical fit recovery

The direct GP backends in ordinary/full controllers share a small, lazily
imported fitting helper. Normal fits use the existing BoTorch fitter with
its defaults. The kernel, observations, scalarization, acquisition settings,
initialization policy, candidate pool, and evaluation budget are unchanged.
The helper does not select a proxy or invent a measurement.

## Recorded failure

The first [backend reference](../benchmarks/backend_comparison/readout.md)
retained one failure: the mixed pipeline, ordinary GP, seed 97, before trial
12. Eleven successful observations and valid raw parameters remained intact.
The [diagnostic fixture](../benchmarks/backend_comparison/gp_pipeline_seed97_failure.json)
preserves those observations and the tested environment. It is a synthetic
numerical case, not private workload data.

On that recorded Python 3.11/Ax-compatible stack, default fitting exhausted
its attempts with SciPy `ABNORMAL` line-search termination. Keeping the same
model initialization and fit seed 109, a line-search allowance of 50
converged at iteration 75 without optimization warnings. The converged
negative marginal log likelihood was approximately 0.329093. This result
motivates a numerical recovery policy; it does not establish better model
quality on arbitrary data.

## Recovery policy

Only `ModelFittingError` from the default fit triggers recovery:

1. Restore the pre-fit model/likelihood state and CPU Torch RNG state.
2. Make one additional fit with the same SciPy L-BFGS-B optimizer, using
   `maxls=50`, `maxiter=200`, `maxfun=2000`, and a 30-second optimizer timeout.
3. Require explicit optimizer `SUCCESS`, a finite objective, and finite
   model parameters. A timeout/iteration limit (`STOPPED`) is not accepted.
4. Return an evaluation-mode model and add `gp_fit_recovery` to the decision
   trace, including trigger, configured limits, steps, and fitted objective.

The timeout is BoTorch's optimizer timeout, checked during optimization;
it is not a hard process deadline for an arbitrarily expensive individual
linear-algebra operation. The original default-fit attempt budget is
unchanged. The benchmark supervisor additionally enforces its process deadline.

The recovery uses [BoTorch's public SciPy fitter](https://botorch.readthedocs.io/en/stable/optim.html)
and [SciPy's documented line-search option](https://docs.scipy.org/doc/scipy/reference/optimize.minimize-lbfgsb.html).
It does not loosen convergence tolerances, suppress a failed status, change
priors, alter measurement errors, or increase the evaluation budget.

If recovery fails, original model/RNG state is restored and an actionable
fit error propagates. Ordinary GP allocates no new trial. The full controller
retains its existing explicitly configured proxy-fallback policy and trace;
this helper introduces no new fallback. Non-finite posterior/acquisition
values are rejected before selecting a candidate.

## Verification and evidence

Lean fault-injection tests check unchanged normal fitting, original-state/RNG
restoration, one bounded attempt, and rejection of nonconvergence/non-finite
results. Optional real-stack tests exercise the retained history through a
portable controller, real bounded fitting, the full GP dispatch, and atomic
failure without allocating a trial or switching the ordinary backend.

The recorded initialization can still encounter a non-positive-definite
covariance during recovery on another numerical platform. Its integration
test requires either explicit convergence with a finite posterior or an
actionable fitting error with the original model and CPU RNG restored exactly.
A forced covariance failure exercises restoration even on platforms where
the recorded case converges. A separate well-conditioned real-data test
requires successful bounded recovery; numerical failures are not accepted
as success or hidden by a skipped test.

The original failed reference remains preserved. A new complete reference
must use a fresh raw evidence directory; no previously failed campaign is
selectively retried into the old result. New summaries count recorded GP
fit recoveries so numerical recovery remains visible alongside resource cost.

The [fresh validation reference](../benchmarks/backend_comparison/gp_fix/readout.md)
completed all 200 campaigns/2400 evaluations and passed every declared gate.
Recovery was used exactly once on the retained case; all 199 previously
successful campaigns retained identical scores and selected configurations.
The initial failed reference remains available as a separate historical result.
