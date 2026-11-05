# Bounded Ax capability evidence (unreleased)

This new synthetic family exercises [Ax contract 2](../../docs/ax-contract2.md).
It preserves the earlier backend comparison and its original failed/reference
outputs. The runner uses fresh portable ordinary controllers for Ax and a
stdlib uniform feasible sampler for the random arm. Random selection ignores
outcomes by definition, while retaining the same objective/measurement information
and using the exact same typed parameter and outcome feasibility rules.

Install the [pinned CPU stack](../../docs/ax-installation.md), then run from the
repository root. Use a fresh output directory outside source templates:

```bash
python -m benchmarks.ax_capabilities.run --output /tmp/ax-capabilities-full
python -m benchmarks.ax_capabilities.audit --output /tmp/ax-capabilities-full
```

The preregistered full design is 40 campaigns / **960 evaluator invocation
slots**, including initialization: four workloads, paired arms, seeds
`17,23,41,67,97`, 24 slots per campaign and six initialization slots. Each
attempt is charged before evaluation; failure consumes its slot, with no
replacement. Every case has a 600-second wall limit, the Ax worker has a
120-second configured timeout, and at most two cases/workers run concurrently.
Timeout handling kills the controller process group. Generation retries and
restore probes are recorded separately from objective calls.

| Workload | Paired arms | Declared mathematical target |
| --- | --- | --- |
| `noisy_scalar` | Ax reported SEM / Ax unknown SEM | Quadratic minimum 0; heteroscedastic Gaussian error `0.02+0.06*x` |
| `typed_conditional` | Ax / feasible uniform random | Typed `1`/`1.0`/`"1"` branches, nested fixed leaf, integer raw linear term, forbidden pair; minimum 0 |
| `measured_scalar` | Ax / feasible uniform random | Resource `x+y<=0.7`; constrained quadratic optimum 0.045 at `(0.65,0.05)` |
| `pareto_tradeoff` | Ax / feasible uniform random | Minimize `x+y²`, maximize `x-y²`, resource `x+0.5*y<=0.8`; fixed reference `(1,-0.1)`, ideal feasible hypervolume 0.58 |

Measurement noise uses paired trial-indexed standardized draws. Simulator truth
is retained for independent regret reporting and never ingested by Ax. Other
workloads are deterministic and report known zero SEMs. Inclusive outcome bounds
compare the actual supplied floating values; no hidden feasibility slack is added.

Scalar metrics include feasible fraction, best feasible latent simple regret,
and latent regret of the configuration selected by its observed value. Pareto
metrics use feasible observed hypervolume relative to the fixed reference.
Results contain every paired per-seed value, median differences and ranges;
positive paired differences favor the first listed arm. Five seeds provide
limited synthetic evidence. A losing Ax arm prevents superiority claims, not
delivery of a correctly qualified capability.

Before the full run, use a small correctness smoke:

```bash
python -m pytest -q benchmarks/ax_capabilities/test_contracts.py
python -m benchmarks.ax_capabilities.run --output /tmp/ax-capabilities-smoke \
  --budget 4 --initialization 2 --seeds 17 --workers 2
```

CI uses only `measured_scalar`, three slots and two initialization slots (six
calls across its two arms). It does not repeat the full matrix.

The output includes `manifest.json` with environment/source/configuration hashes,
`summary.json`, `readout.md`, per-case result files, every attempted evaluator
receipt, command wall times, constraint results, and seeded restore receipts.
The independent audit recomputes raw slot counts, inclusive feasibility, latent
regret and 2D hypervolume using a separate loss sweep, with zero evaluator calls.
An Ax restore shadow allocates a comparison proposal but invokes no evaluator.
Canonical records and snapshot data are retained under each fresh controller.

`--resume` requires exactly matching source/environment/protocol hashes and
campaign configuration. Failed results are retained and never automatically
rerun. A charged slot with uncertain completion or an unreceipted allocation
stops that case for diagnosis. Resume does not reset the original wall deadline
or evaluation allowance. A fresh output path is not authorization to exceed an
already approved total budget.

Hard gates include complete fixed budgets, recomputed counts/metrics, valid
complete public allocations, no unconfigured repeats, observed MBM generation,
seeded restore within absolute `1e-7` on float parameters with exact categorical
types, and campaign wall limits. Failed/incomplete cases remain visible and
prevent a clean acceptance claim. Use the [readout template](readout-template.md)
to distinguish correctness, relative performance and unrun checks.

## Recorded original run

The [original readout](readout.md) reports 39/40 complete campaigns and 958/960
slots, including one correctly stopped 600-second timeout. Its strict completion
gates remain unmet. A subsequent explicitly bounded follow-up used 107.15 additional seconds and
zero evaluator calls, then stopped at eight forbidden proposals. Original
evidence remains intact; no automatic retry was performed. See the
[follow-up receipt](continuation.json).
