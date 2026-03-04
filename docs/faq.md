# FAQ

## What is this repository?

This repository provides a drop-in, file-backed Bayesian optimization loop for expensive black-box objectives.

It includes:

- three runnable optimization template variants
- a client integration harness template
- quickstart instructions
- example integrations
- intake and security docs

## What kinds of problems is this for?

Best fit:

- simulations
- model calibration
- black-box hyperparameter/pipeline tuning
- process optimization
- scheduling/resource allocation (when a scalar objective can be computed)
- pricing/marketing experiments with expensive evaluations

See `docs/use-cases.md` for more detail.

## What does "file-based" mean?

The loop communicates through JSON files and local state, rather than requiring a hosted service.

Typical flow:

1. `suggest` writes a pending trial into local state
2. your system runs an evaluation
3. your system writes a result JSON
4. `ingest` updates local state

## Can this run fully offline / air-gapped?

Yes. The optimization templates and client harness template are designed to support fully local/offline execution.

No hosted service is needed.

See `SECURITY.MD` and `docs/security-data-handling.md`.

## Which template should I start with?

Start with:

- `templates/bo_client_demo` if you want the lightest dependency path and quickest integration validation
- `templates/bo_client` for the default baseline template in most client setups

Use `templates/bo_client_full` if you specifically want the optional feature-flag GP path in that variant.

## What is the difference between proxy-only and GP-backed variants?

### Proxy-only (`rbf_proxy`)

- lightweight
- easy to run in constrained environments
- good for onboarding and process validation

### GP-backed (`gp` in `bo_client`, optional BoTorch GP in `bo_client_full`)

- can be more expressive for some objective landscapes
- requires heavier dependencies (PyTorch/BoTorch/GPyTorch)
- may be less convenient in restricted or air-gapped environments

A practical approach:

1. validate the integration with proxy-only
2. switch to GP mode later if it is useful for the problem and environment

## How many iterations do I need?

It depends on:

- parameter dimensionality
- objective noise
- evaluation cost
- constraint severity
- how broad the bounds are

For a pilot:

- 10-30 evaluations can be enough to validate the integration and learn something
- 30-100+ evaluations may be needed for stronger optimization gains on harder problems

Treat early runs as a learning phase for refining bounds and the objective definition.

## What if my objective is noisy or stochastic?

This is pretty common. Start by documenting:

- noise sources
- expected variance
- whether repeated runs at the same params are possible

Then choose a simple policy:

- single measurement per trial
- repeated measurement + average
- repeated measurement + robust summary

Consistency matters more than cleverness here. See `docs/integration-guide.md` for implementation guidance.

## How reproducible are runs?

Practical reproducibility comes from controlling both optimizer state and
evaluator behavior.

Designed to be reproducible with stable inputs:

- persisted seed in optimizer state
- trial id progression and pending/observation state transitions
- suggestion sequence for a fixed config/state/backend path

Common nondeterminism sources:

- wall-clock timestamps in artifacts
- external evaluator randomness not tied to fixed seeds
- optional GP backend behavior across dependency/runtime changes

For best results, record:

- config/parameter/objective versions used
- evaluator seed policy
- dependency/runtime versions
- retained state artifacts (`bo_state.json`, `acquisition_log.jsonl`)

## What if an evaluation fails?

Recommended approach:

- return a canonical non-`ok` status (`failed`, `killed`, or `timeout`)
- set primary objective to `null`
- optionally include `penalty_objective` for non-`ok` statuses
- keep `trial_id` and `params` unchanged

This preserves traceability and allows the loop to continue.

Compatibility note:

- legacy non-`ok` payloads with numeric primary objective are still accepted in
  `v0.2.x`, normalized to `objective: null` + `penalty_objective`, and produce
  a deprecation warning

## What if `ingest` rejects my result payload?

Common causes:

- wrong `trial_id`
- `params` mismatch (does not match the pending suggestion exactly)
- missing primary objective
- non-numeric or NaN/Inf objective
- schema mismatch

Fix the payload and re-run `ingest`. Do not mutate the original suggested params.

## Can I use this with a CLI tool instead of Python code?

Yes. That is a common use case.

Use `client_harness_template/run_one_eval.py` plus a custom `objective.py` that:

1. launches your CLI tool/subprocess
2. parses outputs/metrics
3. computes a scalar objective
4. returns `{objective, status}`

See:

- `examples/toy-objectives/02_subprocess_cli/`

## Can I use this with a scheduler or cluster?

Yes, typically by wrapping one-evaluation execution on the client side.

Recommended path:

- keep the optimization interface single-trial at first
- have your client wrapper submit/monitor jobs
- only ingest after a result is ready

This reduces integration risk while preserving resumability.

## Does this store sensitive data?

By default, the optimization loop only needs:

- proposed parameters
- scalar objective values
- status values

State files remain local unless you choose to share them.

See:

- `SECURITY.MD`
- `docs/security-data-handling.md`

## Is this a hosted product / SaaS?

No. The repo is a local, file-backed workflow and template set.

You can run it entirely in your own environment.

## When should I not use this?

Examples of poor fit:

- gradient-friendly smooth problems with standard solvers
- very high-dimensional problems without structure
- real-time optimization loops with very tight latency requirements

See `docs/integration-guide.md` for a short "When Not To Use This" section.
