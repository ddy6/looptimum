# Decision Trace and Acquisition Log

This document explains what Looptimum records for each `suggest` attempt and
how to read the acquisition log.

## Where the Trace Lives

Decision traces are written as JSON Lines:

- `state/acquisition_log.jsonl`

Each line corresponds to one trial-level `suggest` decision attempt. Batch
`suggest --count N` writes one line per allocated trial.

Related runtime log:

- `state/event_log.jsonl` tracks lifecycle/ops events (`cancel`, `retire`,
  `heartbeat`, lock events, report generation) and is intentionally separate
  from acquisition decision records.

Reference artifacts:

- `docs/examples/decision_trace/golden_acquisition_log.jsonl`
- `docs/examples/decision_trace/golden_acquisition_log.md`
- `docs/examples/decision_trace/cli_transcript.md`

## Record Shape

Each log line uses the same top-level structure:

```json
{
  "trial_id": 7,
  "decision": {
    "strategy": "surrogate_acquisition",
    "surrogate_backend": "rbf_proxy",
    "constraint_status": {
      "enabled": false,
      "phase": "candidate-pool",
      "requested": 600,
      "accepted": 600,
      "attempted": 600,
      "rejected": 0,
      "feasible_ratio": 1.0,
      "reject_counts": {},
      "warning": null
    }
  },
  "timestamp": 1772392830.728097
}
```

Top-level fields:

- `trial_id`: trial id associated with the decision attempt
- `decision`: strategy, backend, scoring, and feasibility metadata
- `timestamp`: Unix epoch seconds when the decision was logged

Important nuance:

- successful `suggest` attempts create pending state for that `trial_id`
- batched successful `suggest` commands create one such record per allocated
  trial id
- all-infeasible `suggest` attempts still log a decision, but they do not
  create a pending trial or increment authoritative state

## Decision Object Fields

| Field | Meaning | Present When |
|---|---|---|
| `strategy` | Selection path used for the attempt | Always |
| `surrogate_backend` | Backend label (`rbf_proxy`, `gp`, `botorch_gp`, or `null`) | Always |
| `acquisition_type` | Heuristic type (`ei`, `ei_proxy`, or `ucb`) | Surrogate-acquisition mode |
| `predicted_mean` | Predicted objective at the emitted candidate | Surrogate-acquisition success |
| `predicted_std` | Predicted uncertainty proxy | Surrogate-acquisition success |
| `acquisition_score` | Ranking score used to pick the emitted candidate | Surrogate-acquisition success |
| `fallback_reason` | Reason a GP path fell back to random or proxy behavior | Optional |
| `constraint_status` | Nested feasibility metadata for the attempt | Always |
| `constraint_error_reason` | Machine-readable all-infeasible failure reason | All-infeasible attempts |

## `constraint_status` Fields

`constraint_status` records:

- `enabled`: whether `constraints.json` was active
- `phase`: sampling phase (`initial-random`, `fallback-random`, or `candidate-pool`)
- `requested`: requested feasible candidate count for that phase
- `accepted`: feasible candidates that survived filtering
- `attempted`: total sampled attempts
- `rejected`: infeasible attempts
- `feasible_ratio`: `accepted / attempted`
- `reject_counts`: dominant rule-family counts by rule id
- `warning`: human-readable warning when constraints reduced but did not
  eliminate the feasible pool

## Strategy Semantics

### `initial_random`

- used during warmup before enough observations are available
- also used for random fallback paths
- `surrogate_backend` is `null`

### `surrogate_acquisition`

- used after warmup
- candidate pool is sampled, scored, and ranked
- highest acquisition score candidate is emitted on success

### All-Infeasible Failure Attempts

If constraints eliminate every sampled attempt:

- `suggest` exits nonzero
- no pending trial is created
- the decision trace still records the failed attempt with
  `constraint_error_reason`

This is why `acquisition_log.jsonl` can contain entries that do not have a
matching pending/observation record in `bo_state.json`.

## Backend Notes by Template

### `templates/bo_client_demo`

- uses proxy scoring only
- records `surrogate_backend` and `constraint_status` consistently for both
  warmup and acquisition decisions

### `templates/bo_client`

- supports `rbf_proxy` and optional `gp`
- decision records use the same feasibility metadata shape in both paths

### `templates/bo_client_full`

- supports proxy and optional BoTorch GP path
- fallback-to-proxy records still preserve the same `constraint_status` shape

## How to Audit a Run

Recommended audit flow:

1. Read `bo_state.json` for canonical pending/observed/best state.
2. Read `acquisition_log.jsonl` chronologically for decision attempts.
3. Match `trial_id` across suggestion payloads, ingest payloads, and
   observations when the attempt succeeded.
4. If a `trial_id` appears only in the decision trace, check
   `constraint_error_reason` before assuming a state inconsistency.
5. Use `fallback_reason` and `constraint_status.reject_counts` to explain
   backend fallbacks or feasibility collapse.

## Reproducibility Boundaries

Useful anchors:

- trial ids and successful suggestion order are deterministic for a fixed
  state/config/backend path
- decision logs preserve chronological decision order

Known variability:

- timestamp values are wall-clock dependent
- GP behavior may vary with dependency versions and numeric backend details
- external evaluator noise can shift downstream decision trajectories

## What This Trace Is and Is Not

The decision trace is:

- an auditable record of suggestion-time decision metadata
- useful for debugging backend selection and feasibility filtering

The decision trace is not:

- authoritative state
- a proof of global optimality
- a substitute for domain-level validation and review
