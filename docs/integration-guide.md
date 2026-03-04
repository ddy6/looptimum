# Integration Guide

This guide explains how to connect your evaluation system to the optimization
templates in this repository using the file-backed
`suggest -> evaluate -> ingest` contract.

The Looptimum CLI exposes a stable command contract across template variants:
`suggest`, `ingest`, `status`, `demo`, lifecycle controls (`cancel`, `retire`,
`heartbeat`), and support ops (`report`, `validate`, `doctor`).

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
- one primary objective value (`number` for `ok`, `null` for non-`ok`)
- a trial status (`ok`, `failed`, `killed`, or `timeout`)

## Repository Paths You Will Use

- `templates/`: runnable optimization harness variants
  (`bo_client_demo`, `bo_client`, `bo_client_full`)
- `client_harness_template/`: starter adapter for one-evaluation integration
- `examples/toy-objectives/`: reference integration patterns
- `examples/toy_objectives/03_tiny_quadratic_loop/`: dedicated tiny end-to-end
  objective loop example
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

## Copy-Paste Evaluator Stub (Fuller Version)

Use this as a starting point for `client_harness_template/objective.py`:

```python
#!/usr/bin/env python3
from __future__ import annotations

from typing import Any

DEFAULT_FAILURE_PENALTY = 1e12  # for minimize objectives


def _require_float(params: dict[str, Any], name: str) -> float:
    value = params.get(name)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"missing/invalid numeric param: {name}")
    return float(value)


def evaluate(params: dict[str, Any]) -> dict[str, Any]:
    x1 = _require_float(params, "x1")
    x2 = _require_float(params, "x2")
    try:
        # Replace this with your real evaluator call + metric parsing.
        loss = (x1 - 0.3) ** 2 + (x2 - 0.7) ** 2
        return {"status": "ok", "objective": float(loss)}
    except TimeoutError:
        return {
            "status": "timeout",
            "objective": None,
            "penalty_objective": DEFAULT_FAILURE_PENALTY,
        }
    except Exception:
        return {
            "status": "failed",
            "objective": None,
            "penalty_objective": DEFAULT_FAILURE_PENALTY,
        }
```

Notes:

- For maximize objectives, use a directionally bad penalty (for example `-1e12`).
- Keep `trial_id` and `params` unchanged; only return objective/status fields.
- If you prefer automatic failure wrapping, raise exceptions and use
  `run_one_eval.py --on-exception failed`.

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
- status must be one of `ok`, `failed`, `killed`, `timeout`
- for `status: ok`, primary objective must be numeric and finite
- for non-`ok` statuses, primary objective should be `null`
- optional `penalty_objective` can be included for non-`ok` statuses

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
- per-trial manifest is updated under `state/trials/trial_<id>/manifest.json`
- lifecycle events are appended to `state/event_log.jsonl`

Schema path note:

- canonical config key is `paths.ingest_schema_file`
- legacy `paths.result_schema_file` is still accepted with a deprecation warning

## Lifecycle and Runtime Ops

Runtime control commands used during long-running integrations:

- `cancel --trial-id <id>`: operator-cancel pending trial and record a terminal
  `killed` observation (`objective: null`).
- `retire --trial-id <id>`: retire a pending trial with an explicit reason.
- `retire --stale [--max-age-seconds]`: retire pending trials beyond stale age
  threshold.
- `heartbeat --trial-id <id>`: update pending liveness metadata.
- `report`: write `state/report.json` and `state/report.md`.
- `validate [--strict]`: run config/schema/state checks (`--strict` makes warnings fatal).
- `doctor [--json]`: print environment/backend/state diagnostics.

Operational notes:

- Mutating commands use an exclusive lock (`state/.looptimum.lock`) with
  wait+timeout default behavior.
- Use `--fail-fast` on mutating commands when your automation should fail
  immediately under lock contention.

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

Objective direction is configured in `objective_schema.json` in your chosen template.

For `client_harness_template/run_one_eval.py --objective-schema`, `.json` is
preferred; legacy `.yaml`/`.yml` objective schema files are accepted with
deprecation warnings.

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
- Use non-`ok` status (`failed`, `killed`, or `timeout`) as appropriate
- Set primary objective to `null`
- Optionally include `penalty_objective` when numeric penalty ranking/reporting
  is useful
- `penalty_objective` is not used for best-trial ranking; `best` is computed
  from `status: "ok"` primary objective values only

Compatibility note (v0.2.x line):

- Legacy sentinel payloads for non-`ok` statuses are still accepted and
  normalized to `objective: null` + `penalty_objective`.
- Ingest emits a deprecation warning for this path.
- Sentinel primary objective compatibility is planned for removal in `v0.3.0`.

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
- objective/status policy mismatch (`ok` requires numeric finite; non-`ok`
  requires `null`)
- `trial_id` is not pending
- `params` do not match the pending suggestion
- conflicting duplicate replay (same `trial_id` with different payload fields)

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
- `state/event_log.jsonl`
- `state/trials/trial_<id>/manifest.json`
- `state/report.json` and `state/report.md` (written when `report` is run)

Behavior:

- `suggest` creates a pending trial and increments `next_trial_id`
- `ingest` consumes a matching pending trial
- duplicate ingest with identical payload is accepted as explicit no-op
- duplicate ingest with conflicting fields is rejected with diff details
- if the budget is exhausted, `suggest` exits cleanly without creating a new pending trial
- stale pending trials can be retired automatically during `suggest` (when
  `max_pending_age_seconds` is configured/enabled)

See:

- `quickstart/README.md`
- `docs/examples/state_snapshots/` (includes both `ok` and non-`ok`
  ingest examples)

## Reproducibility: Seeds and Determinism Boundaries

What is designed to be reproducible:

- persisted optimizer seed in `state.meta.seed`
- trial id sequence (`next_trial_id`) in state
- suggestion ordering for a stable config/state/backend path

What is not fully deterministic:

- wall-clock timestamps in state/log records
- external evaluator randomness unless you control it
- optional GP backends across dependency/runtime changes

Recommended reproducibility checklist:

1. Keep config, parameter space, and objective schema versioned for each pilot.
2. Capture evaluator seed policy (fixed/derived/randomized) in intake notes.
3. Record runtime dependency versions before starting a campaign.
4. Preserve `bo_state.json` as canonical run state and keep
   `acquisition_log.jsonl` + `event_log.jsonl` for decision/lifecycle audit.

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

Important concurrency rule:

- run only one mutating controller process per state path at a time; evaluators
  can execute remotely/in parallel, but state mutation should flow through the
  locked CLI commands.

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
- `docs/operational-semantics.md`
- `docs/search-space.md`
- `docs/decision-trace.md`
- `docs/pilot-checklist.md`
- `docs/faq.md`
- `docs/security-data-handling.md`
- `docs/use-cases.md`
- `SECURITY.MD`
- `intake.md`
