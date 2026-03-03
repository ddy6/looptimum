# Integration Guide

This guide explains how to connect your evaluation system to the optimization
templates in this repository using the file-backed
`suggest -> evaluate -> ingest` contract.

The Looptimum CLI exposes a stable `suggest` / `ingest` / `status` / `demo` workflow across template variants.

It is designed for expensive black-box objectives such as simulations,
calibrations, pipeline tuning, and process optimization.

## What You Are Integrating

The Looptimum templates in `templates/` provide a restartable loop that:

1. Suggests one parameter set (`suggest`)
2. Waits for your system to run one evaluation
3. Ingests a result payload (`ingest`)
4. Updates state and repeats

The loop does not need raw data or internal model internals. It just needs:

- parameter values
- one scalar objective value
- a trial status (`ok` or `failed`)

## Repository Paths You Will Use

- `templates/`: runnable optimization harness variants
  (`bo_client_demo`, `bo_client`, `bo_client_full`)
- `client_harness_template/`: starter adapter for one-evaluation integration
- `examples/toy-objectives/`: reference integration patterns
- `quickstart/README.md`: repo-root commands and state/resume examples
- `intake.md`: project intake checklist
- `SECURITY.MD`: top-level security/data-handling summary

## Choose a Template Variant

### `templates/bo_client_demo`

Use when you want the lightest path to validate integration and process.

- proxy-only surrogate backend
- minimal dependency overhead
- best for contract testing and onboarding

### `templates/bo_client`

Use as the default baseline for most client integrations.

- same CLI/file contract
- config-selected backend (`rbf_proxy` or optional `gp`)
- stronger test coverage and modular backend code

### `templates/bo_client_full`

Use when you want the same contract with optional feature-flag GP behavior in
the public template.

- proxy fallback path
- optional `--enable-botorch-gp` flag

## Core Contract: `suggest -> evaluate -> ingest`

### 1. Generate a Suggestion

Example (repo root):

```bash
python3 templates/bo_client_demo/run_bo.py suggest --project-root templates/bo_client_demo --json-only
```

This emits a suggestion containing:

- `trial_id`
- `params`
- `suggested_at`

Important:

- Treat `trial_id` and `params` as immutable for that trial.
- The `suggest` command also records a pending trial in the state file.
- Use `--json-only` when piping/parsing output programmatically.

### Parameter Types (Current Public Templates)

Current public templates support:

- `float`
- `int`

Categorical parameters can be modeled with custom extensions, but are not
native in the default `run_bo.py` implementations yet.

### 2. Run One Evaluation

You run your external system using the suggested `params`.

This can be implemented as:

- a Python function
- a CLI/script
- an API call
- a scheduler job wrapper

Use `client_harness_template/run_one_eval.py` as a starting adapter.

### 3. Write an Ingest-Compatible Result Payload

Minimum payload shape:

```json
{
  "trial_id": 3,
  "params": {"x1": 0.31, "x2": 0.72},
  "objectives": {"loss": 0.1182},
  "status": "ok"
}
```

Requirements:

- `trial_id` must match the pending suggestion
- `params` must exactly match the pending suggestion
- objective must be numeric and finite
- `status` should be `ok` or `failed`

### 4. Ingest the Result

```bash
python3 templates/bo_client_demo/run_bo.py ingest \
  --project-root templates/bo_client_demo \
  --results-file /path/to/result.json
```

If valid:

- pending trial is cleared
- observation is appended
- best-so-far is updated
- `state/observations.csv` is rewritten

## Minimal Working Integration (Recommended Path)

Start with `client_harness_template` (it usually saves time).

### Step A: Implement `evaluate(params)`

Edit:

- `client_harness_template/objective.py`

Replace the stubbed `evaluate(params)` function with your real evaluation logic.

### Step B: Use the Adapter to Produce Result Payloads

```bash
python3 client_harness_template/run_one_eval.py \
  /path/to/suggestion.json \
  /path/to/result.json \
  --objective-module client_harness_template/objective.py \
  --objective-name loss
```

The adapter supports:

- pure suggestion JSON, or
- raw `suggest` stdout (it strips trailing non-JSON lines)

### Step C: Ingest Result Payloads into the Optimization Template

```bash
python3 templates/bo_client_demo/run_bo.py ingest \
  --project-root templates/bo_client_demo \
  --results-file /path/to/result.json
```

## Parameter -> Evaluation -> Scalar Objective Mapping

Define this mapping explicitly before running a pilot:

1. Parameter mapping:
   - How `params` values are injected into your system
2. Execution:
   - What process/job/function runs
3. Raw outputs:
   - What metrics/artifacts are produced
4. Scalarization:
   - How one objective value is computed
5. Failure representation:
   - What happens when the run fails or is invalid

Use `intake.md` to capture this precisely.

## Objective Direction (Minimize vs Maximize)

Objective direction is configured in `objective_schema.yaml` in your chosen template.

Examples:

- `loss` + `minimize`
- `score` + `maximize`

Your evaluator should return the raw scalar in the same direction convention
expected by the harness.

- Do not silently negate values unless you intentionally changed the harness objective definition.

## Failure Modes and Recommended Handling

A failed evaluation should usually still produce an ingest payload so the loop
can continue and the failure is recorded.

### Recommended Failure Payload Strategy

- Keep `trial_id` and `params` unchanged
- Set `status` to `failed`
- Write a finite sentinel objective value that is directionally bad

Sentinel guidance:

- minimize objective: large value (example `1e12`)
- maximize objective: very small value (example `-1e12`)

### Common Failure Modes

- invalid parameter region / infeasible configuration
- solver or training crash
- timeout / runtime limit exceeded
- output parse failure
- infrastructure interruption
  (node failure, scheduler cancellation, transient service error)

### What Happens if `ingest` Fails?

Common `ingest` rejections include:

- result schema violation
- missing primary objective
- objective is not numeric/finite
- `trial_id` is not pending
- `params` do not match the pending suggestion

If `ingest` fails:

1. Fix the payload (or regenerate it from the original suggestion)
2. Re-run `ingest`
3. Do not issue a new `suggest` for that same trial unless you intentionally
   abandon the pending one in your own process

## Resume Semantics (Important)

The templates are restartable and file-backed.

Default state files:

- `state/bo_state.json`
- `state/observations.csv`
- `state/acquisition_log.jsonl`

Behavior:

- `suggest` creates a pending trial and increments `next_trial_id`
- `ingest` consumes a matching pending trial
- duplicate ingest is rejected
- if the budget is exhausted, `suggest` exits cleanly without creating a new pending trial

See:

- `quickstart/README.md`
- `docs/examples/state_snapshots/`

## Noisy Objectives and Repeated Evaluations

If your objective is noisy or stochastic:

- document likely noise sources in `intake.md`
- decide whether repeated evaluations at the same params are allowed
- define a policy for:
  - single measurement
  - repeated measurement + averaging
  - repeated measurement + robust summary (median/trimmed mean)

Start simple; refine the policy after an initial pilot.

## Scaling to Batch / Cluster Execution (Pragmatic Path)

The templates suggest one trial at a time. In practice, that is usually the safest integration surface.

To scale in a cluster environment:

1. `suggest` one trial
2. submit one job
3. wait for completion (or poll)
4. build result payload
5. `ingest`
6. repeat

Once stable, you can build a client-side scheduler wrapper that manages
multiple pending suggestions carefully.

## When Not To Use This (Trust-Building Scope Boundaries)

This repo is a strong fit for expensive black-box evaluations, but it is not
the right tool for every optimization problem.

Poor fits:

- problems with cheap gradients and standard gradient-based solvers
- extremely high-dimensional search spaces without strong structure
- hard real-time control loops requiring millisecond decisions
- situations where no scalar objective can be defined at all

## Suggested First Pilot Workflow

1. Fill in `intake.md`
2. Choose `templates/bo_client_demo` or `templates/bo_client`
3. Implement `client_harness_template/objective.py`
4. Validate one end-to-end `suggest -> run_one_eval -> ingest` cycle
5. Run a small pilot budget (for example, 10-30 evaluations)
6. Review results and adjust:
   - parameter bounds
   - objective definition
   - failure handling policy

## Related Docs

- `quickstart/README.md`
- `client_harness_template/README_INTEGRATION.md`
- `docs/faq.md`
- `docs/security-data-handling.md`
- `docs/use-cases.md`
- `SECURITY.MD`
- `intake.md`
