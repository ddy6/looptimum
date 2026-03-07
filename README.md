# Looptimum

[![CI](https://github.com/ddy6/looptimum/actions/workflows/ci.yml/badge.svg)](https://github.com/ddy6/looptimum/actions/workflows/ci.yml)
[![Latest Release](https://img.shields.io/github/v/release/ddy6/looptimum?display_name=tag)](https://github.com/ddy6/looptimum/releases)

Fewer expensive experiments. Faster convergence.

Looptimum is a file-backed optimization loop for tuning parameters when each
trial is costly (time, compute, money, or operational risk).
You provide a parameter space and one scalar objective; Looptimum suggests the
next trial, records decisions, and resumes cleanly after interruptions.
Current stable release: `v0.3.0`.
For expensive black-box objectives, Looptimum starts with bounded exploration
and then shifts to surrogate-guided suggestion ranking to reduce wasted trials.
Its key differentiator is operational: a file-backed, resumable workflow that
keeps state and decision trace local, which fits restricted and client-controlled
environments. The usage model stays simple (`suggest -> evaluate -> ingest`);
see [`docs/how-it-works.md`](docs/how-it-works.md) for algorithm behavior and
tuning consequences.
For a spec-style contract summary, use
[`docs/quick-reference.md`](docs/quick-reference.md).

## Trust Anchors

Every core claim in this README has an auditable source:

- contract semantics and payload/state definitions:
  [`docs/quick-reference.md`](docs/quick-reference.md)
- optimizer behavior, backend differences, and failure modes:
  [`docs/how-it-works.md`](docs/how-it-works.md)
- compatibility and breaking-change policy:
  [`docs/stability-guarantees.md`](docs/stability-guarantees.md)
- recovery and interruption handling:
  [`docs/recovery-playbook.md`](docs/recovery-playbook.md)
- CI operational policy for persistence/parallelism/robust best:
  [`docs/ci-knob-tuning.md`](docs/ci-knob-tuning.md)
- benchmark evidence and reproducibility artifacts:
  [`benchmarks/README.md`](benchmarks/README.md),
  [`benchmarks/summary.json`](benchmarks/summary.json),
  [`benchmarks/case_study.md`](benchmarks/case_study.md)

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
| Looptimum controller | Local machine, CI runner, or client host | `suggest`, `ingest`, `status`, lifecycle + ops commands, local state |
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
- Large-model workflow tuning: training recipe knobs, evaluation-policy
  settings, and runtime controls for long-running jobs.
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

Quickstart note:

- The default template files and commands above use canonical JSON contract
  paths and run without compatibility/deprecation warnings on a clean copy.

For full command sets and resume behavior, see `quickstart/README.md`.
For an opinionated mainstream scenario, see
[`quickstart/etl-pipeline-knob-tuning.md`](quickstart/etl-pipeline-knob-tuning.md).
For interruption triage and recovery actions, see
`docs/recovery-playbook.md`.
For the dedicated tiny end-to-end objective walkthrough, see
`examples/toy_objectives/03_tiny_quadratic_loop/README.md`.

## Evidence

Evidence artifacts for optimization-credibility checks are published in
`benchmarks/`:

- benchmark runner script:
  `benchmarks/run_trial_efficiency_benchmark.py`
- committed compact summary (golden):
  `benchmarks/summary.json`
- generated compact case study (derived from summary):
  `benchmarks/case_study.md`

Canonical Phase 8 protocol in this repository:

- objective: `tiny_quadratic`
- baseline: random search
- metric: best objective at fixed budget
- reproducibility: 10 seeds with median + IQR reporting

Re-run canonical evidence locally:

```bash
python3 benchmarks/run_trial_efficiency_benchmark.py \
  --objective tiny_quadratic \
  --budget 20 \
  --seeds 17,29,41,53,67,79,97,113,131,149 \
  --write-summary benchmarks/summary.json \
  --write-case-study benchmarks/case_study.md
```

## Copy/Paste Evaluator Stub (Minimal)

Drop this into `client_harness_template/objective.py` to get started quickly:

```python
def evaluate(params):
    x1 = float(params["x1"])
    x2 = float(params["x2"])
    loss = (x1 - 0.3) ** 2 + (x2 - 0.7) ** 2
    return {"status": "ok", "objective": loss}
```

Use this when your evaluator can return a scalar directly.
For fuller failure handling (`failed`/`timeout` + `penalty_objective`), use the
expanded stub in
[`docs/integration-guide.md#copy-paste-evaluator-stub-fuller-version`](docs/integration-guide.md#copy-paste-evaluator-stub-fuller-version).

## When To Use Looptimum

- Each evaluation is expensive enough that sample efficiency matters.
- Your evaluator runs as external jobs and you want a thin outer loop above
  training/evaluation infrastructure.
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

- `schema_version` (semver string, emitted by runtime)
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

- `schema_version` (semver string, optional in schema and emitted by harness/runtime flows)
- `penalty_objective` (number, only for non-`ok` statuses; reporting/compatibility only)

### `status` Headline Fields

- `schema_version`
- `observations`
- `pending`
- `next_trial_id`
- `best`
- `stale_pending`
- `observations_by_status`
- `paths`

Best ranking rule:

- `best` is computed only from `status: "ok"` observations and their primary
  objective values.
- `penalty_objective` is never used to rank `best`.

### Local State Files

- `state/bo_state.json`: source of truth for observations/pending/best and
  required `schema_version`.
- `state/observations.csv`: flattened observation export.
- `state/acquisition_log.jsonl`: append-only decision trace.
- `state/event_log.jsonl`: append-only lifecycle/operations trace.
- `state/trials/trial_<id>/manifest.json`: per-trial audit manifest.
- `state/report.json` and `state/report.md`: explicit report outputs from `report`.

### Compatibility Notes

- `success` is accepted as a deprecated alias and normalized to `ok`.
- Legacy `v0.2.x` non-`ok` payloads with numeric primary objective are
  accepted in `v0.3.x`, normalized to
  `objective: null` + `penalty_objective`, and emit a deprecation warning.
- Sentinel primary-objective compatibility is planned for removal in `v0.4.0`.
- `v0.2.x` state without `schema_version` (or with `0.2.x`) upgrades in-memory
  to `0.3.0` and persists on next mutating command.
- Earlier `v0.3.x` state versions load transparently in `v0.3.x`.
- Migration policy/specs:
  [`docs/migrations/README.md`](docs/migrations/README.md),
  [`docs/migrations/v0.2.x-to-v0.3.0.md`](docs/migrations/v0.2.x-to-v0.3.0.md).

### Stability Promise (`v0.3.x`)

- No breaking changes within the `v0.3.x` line for CLI command names/required
  flags, ingest required fields/status vocabulary, and core state-file
  compatibility.
- Breaking changes are allowed only on `0.x` major-line increments (for
  example `0.3 -> 0.4`) and require migration notes.
- Current patch tag in this line: `v0.3.0` (see `CHANGELOG.md`).
- Full policy: [`docs/stability-guarantees.md`](docs/stability-guarantees.md).

### Duplicate Ingest Behavior

- Identical replay of an already ingested trial: explicit no-op success.
- Conflicting replay for an already ingested trial: rejected with field-level
  diff details.

### Runtime Ops Commands

- `cancel --trial-id <id>`: operator-cancel a pending trial (recorded as terminal `killed` observation with reason).
- `retire --trial-id <id>` or `retire --stale`: retire pending trials manually or by age policy.
- `heartbeat --trial-id <id>`: update liveness metadata for long-running pending trials.
- `report`: generate `state/report.json` + `state/report.md`.
- `validate [--strict]`: sanity-check config/state; warnings are non-fatal unless `--strict`.
- `doctor [--json]`: print environment/backend/state diagnostics.

## Templates (Choose Your Starting Level)

### Template Matrix (Feature Parity + Intended Use)

| Template | Intended use | Default backend | Optional backend | CLI/lifecycle parity |
|---|---|---|---|---|
| `templates/bo_client_demo` | Fastest onboarding and contract validation | `rbf_proxy` | none | full parity (`suggest`, `ingest`, `status`, `demo`, `cancel`, `retire`, `heartbeat`, `report`, `validate`, `doctor`) |
| `templates/bo_client` | Recommended baseline for most integrations | `rbf_proxy` | `gp` (config-selected) | full parity |
| `templates/bo_client_full` | Same public contract with optional feature-flag GP path | `rbf_proxy` | `botorch_gp` (`--enable-botorch-gp` / config flag) | full parity |

All template variants use the same canonical JSON contract file conventions and
the same state/log artifact model under `state/`.

## Examples and Case Studies

The `examples/` folder shows integration patterns, not benchmark leaderboards.

- `examples/toy-objectives/01_python_function/`: in-process evaluator pattern
- `examples/toy-objectives/02_subprocess_cli/`: subprocess/CLI wrapper pattern
- `examples/toy_objectives/03_tiny_quadratic_loop/`: dedicated tiny end-to-end
  objective (`suggest -> evaluate -> ingest -> status`, typically under one minute)

Run the tiny end-to-end objective from repo root:

```bash
python3 examples/toy_objectives/03_tiny_quadratic_loop/run_tiny_loop.py --steps 6
```

### Case-Study Gallery (Mainstream-First)

- **ETL throughput tuning**: optimize `batch_size`, worker count, and retry policy;
  score = `cost_per_gb + latency_penalty`.
- **API/service tuning**: optimize concurrency limits, cache TTL, and timeout knobs;
  score = `p95_latency + error_rate_penalty`.
- **Search/ranking calibration**: optimize blending weights and threshold gates;
  score = `-relevance_metric + latency_penalty`.
- **Simulation meshing (specialized)**: optimize mesh density/refinement controls;
  score = `runtime + instability_penalty`.
- **Assay/process protocol (specialized)**: optimize concentration/time/temperature;
  score = `-yield + failure_penalty`.
- **OpenFOAM-style workflow (specialized)**: optimize meshing/solver controls;
  score = `wall_clock_time + nonconvergence_penalty`.

Expanded gallery with equal mainstream/specialized coverage is in
[`docs/use-cases.md`](docs/use-cases.md).

### Decision-Trace and CLI Transcript Assets

- `docs/examples/decision_trace/golden_acquisition_log.jsonl`
- `docs/examples/decision_trace/golden_acquisition_log.md`
- `docs/examples/decision_trace/cli_transcript.md`
- `meshing_example/`: advanced, environment-specific OpenFOAM-style case study

## Pilot and Service Options

- Self-serve: use templates directly in your environment.
- Assisted integration: wire your evaluator with the starter harness.
- Managed execution support: run a pilot loop with clear deliverables.
- Optional on-prem/offline support: operate entirely in client-controlled
  infrastructure.

If you have an expensive tuning problem, start with `intake.md` and open an
issue describing your use case.
For first-impression and adoption feedback, use the GitHub Issues template at
`.github/ISSUE_TEMPLATE/first-impressions.yml` (Issues are the primary
feedback source of truth).

## Deeper Docs

- `docs/how-it-works.md`
- `docs/integration-guide.md`
- `docs/operational-semantics.md`
- `docs/recovery-playbook.md`
- `docs/ci-knob-tuning.md`
- `docs/stability-guarantees.md`
- `docs/type-safety.md`
- `docs/feedback-loop.md`
- `docs/search-space.md`
- `docs/decision-trace.md`
- `docs/pilot-checklist.md`
- `docs/faq.md`
- `docs/security-data-handling.md`
- `docs/use-cases.md`
- `client_harness_template/README_INTEGRATION.md`
- `quickstart/README.md`
- `reports/phase8_release_readiness.md`
- `reports/v0.2.0_release_execution_checklist.md`

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
