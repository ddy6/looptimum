# Looptimum

Fewer expensive experiments. Faster convergence.

Looptimum is a file-backed optimization loop for tuning parameters when each
trial is costly (time, compute, money, or operational risk).
You provide a parameter space and one scalar objective; Looptimum suggests the
next trial, records decisions, and resumes cleanly after interruptions.

## If You've Ever Said...

- "We're wasting time on parameter sweeps and manual tuning."
- "Each run is expensive, so we need fewer total experiments."
- "We can run evaluations, but we do not want to build optimization infra."
- "Runs sometimes fail; we need resumable state and traceability."
- "We have lots of knobs and no reliable way to tune them."

## What Looptimum Does

Looptimum replaces ad hoc sweep loops with a small, explicit workflow:

1. Define parameter bounds and objective direction.
2. `suggest` one trial.
3. Run that trial in your environment.
4. `ingest` the result and repeat.

Instead of broad grid/random sweeps, Looptimum uses prior observations to choose
what to test next.

### What Runs Where

| Component | Typical Location | Responsibility |
|---|---|---|
| Looptimum controller | Local machine, CI runner, or client host | `suggest`, `ingest`, `status`, local state |
| Evaluator | Your runtime (script, cluster job, lab workflow, API) | Execute one trial from suggested params |
| State and logs | Local files under template `state/` | Resume, audit trail, best-so-far tracking |

## Common Use Cases

- Data/ETL pipelines: batch size, parallelism, retry/backoff, memory limits.
- Infra/performance tuning: concurrency, cache TTLs, connection pools,
  thread counts.
- Search/recommendation knobs: threshold and weighting calibration.
- Pricing/growth experiments: eligibility thresholds, ramp controls,
  and guardrail tradeoffs.
- Build and compile tuning: optimization flags, link-time settings,
  and benchmark-driven runtime tradeoffs.
- ML training loops: learning rate, batch size, regularization, early-stop
  settings.
- Simulation and engineering workflows: solver tolerances, mesh controls,
  calibration settings.
- Operations/process tuning: throughput vs. quality/cost tradeoffs.

For many small-to-moderate parameter spaces, teams can find competitive
configurations in fewer runs than naive sweeps (problem dependent).

## Quickstart (2 Minutes)

From repo root:

```bash
python3 templates/bo_client_demo/run_bo.py demo \
  --project-root templates/bo_client_demo \
  --steps 5
python3 templates/bo_client_demo/run_bo.py status \
  --project-root templates/bo_client_demo
```

Real captured `status` output (from `templates/bo_client_demo` on
March 3, 2026):

```json
{
  "observations": 3,
  "pending": 0,
  "next_trial_id": 4,
  "best": {
    "trial_id": 2,
    "objective_name": "loss",
    "objective_value": 0.03128341826910849,
    "updated_at": 1772392830.7282188
  }
}
```

Key fields:

- `observations`
- `pending`
- `next_trial_id`
- `best`

For full command sets and resume behavior, see `quickstart/README.md`.

## When To Use Looptimum

- Each evaluation is expensive enough that sample efficiency matters.
- You can define one scalar objective (`minimize` or `maximize`).
- You have a bounded parameter set (commonly small-to-moderate dimensional).
- You want resumable, file-backed operation in local/offline/restricted
  environments.
- You prefer a small integration contract over building custom BO orchestration.

## When Not To Use Looptimum

- Objective evaluation is cheap and simple random/grid search is sufficient.
- Reliable gradients are available and gradient-based methods are a better fit.
- Search space is extremely high-dimensional without useful structure.
- You cannot define a scalar objective or acceptable scalarization rule.

## Contract (Current)

### Inputs

- Parameter space definition (`float` and `int` currently supported in public
  templates).
- Objective schema (name + direction).
- Trial budget and seed/config settings.

### `suggest` Output

Each suggestion includes:

- `trial_id`
- `params`
- `suggested_at`

### `ingest` Required Fields

- `trial_id` (must match a pending trial)
- `params` (must match suggested params exactly)
- `objectives`:
  - `status: ok` -> primary objective must be numeric and finite
  - non-`ok` status -> primary objective must be `null`
- `status`: `ok`, `failed`, `killed`, `timeout`

### `ingest` Optional Fields

- `penalty_objective` (number, only for non-`ok` statuses)

### `status` Headline Fields

- `observations`
- `pending`
- `next_trial_id`
- `best`

### Local State Files

- `state/bo_state.json`: source of truth for observations/pending/best.
- `state/observations.csv`: flattened observation export.
- `state/acquisition_log.jsonl`: append-only decision trace.

### Compatibility Notes

- `success` is accepted as a deprecated alias and normalized to `ok`.
- Legacy non-`ok` payloads with numeric primary objective are accepted in
  `v0.2.x`, normalized to `objective: null` + `penalty_objective`, and emit a
  deprecation warning.
- Sentinel primary-objective compatibility is planned for removal in `v0.3.0`.

### Duplicate Ingest Behavior

- Identical replay of an already ingested trial: explicit no-op success.
- Conflicting replay for an already ingested trial: rejected with field-level
  diff details.

## Templates (Choose Your Starting Level)

### Demo (dependency-light)

- Directory: `templates/bo_client_demo`
- Backend: proxy (`rbf_proxy`)
- Best for: quick validation of contract and workflow

### Default (recommended baseline)

- Directory: `templates/bo_client`
- Backends: proxy by default, optional GP backend by config
- Best for: most client integrations

### Full (feature-flag GP path)

- Directory: `templates/bo_client_full`
- Backends: proxy + optional BoTorch GP via flag
- Best for: same public contract with optional advanced backend behavior

## Examples and Case Studies

The `examples/` folder shows integration patterns, not benchmark leaderboards.

- `examples/toy-objectives/01_python_function/`: in-process evaluator pattern
- `examples/toy-objectives/02_subprocess_cli/`: subprocess/CLI wrapper pattern
- `meshing_example/`: advanced, environment-specific OpenFOAM-style case study

## Pilot and Service Options

- Self-serve: use templates directly in your environment.
- Assisted integration: wire your evaluator with the starter harness.
- Managed execution support: run a pilot loop with clear deliverables.
- Optional on-prem/offline support: operate entirely in client-controlled
  infrastructure.

If you have an expensive tuning problem, start with `intake.md` and open an
issue describing your use case.

## Deeper Docs

- `docs/integration-guide.md`
- `docs/operational-semantics.md`
- `docs/search-space.md`
- `docs/decision-trace.md`
- `docs/pilot-checklist.md`
- `docs/faq.md`
- `docs/security-data-handling.md`
- `docs/use-cases.md`
- `client_harness_template/README_INTEGRATION.md`
- `quickstart/README.md`

## Testing

Install test dependencies:

```bash
python3 -m pip install -r requirements-dev.txt
```

Run template test suites:

```bash
python3 -m pytest -q templates
```

Optional GP backend validation for `bo_client`:

```bash
RUN_GP_TESTS=1 python3 -m pytest -q \
  templates/bo_client/tests/test_suggest.py::test_suggest_works_with_gp_backend
```

## Automation Note (Machine-Readable Suggest)

For machine parsing of `suggest` output, use:

```bash
python3 templates/bo_client_demo/run_bo.py suggest \
  --project-root templates/bo_client_demo \
  --json-only
```
