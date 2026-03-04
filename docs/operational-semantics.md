# Operational Semantics

This document defines how the current public templates behave at runtime for
`suggest -> ingest -> status`.

Scope notes:

- Current behavior reference: public `v0.1` templates in `templates/`.
- Forward-looking notes are marked as `v0.2 target` when behavior is frozen in
  planning docs but not fully implemented yet.

## Core Files and Authority

| File | Role | Authority Level |
|---|---|---|
| `state/bo_state.json` | Source of truth for pending trials, observations, best-so-far, and next trial id | Authoritative |
| `state/acquisition_log.jsonl` | Append-only decision log for each suggestion | Audit trail, not authoritative state |
| `state/observations.csv` | Flattened export of observations | Derived artifact |

Operational rule: when files disagree, treat `state/bo_state.json` as canonical.

## Supported Topology

- Supported topology today: one controller process writes state.
- Evaluators can run in separate environments, but should not mutate state
  files directly.
- Multi-writer coordination is not guaranteed in current templates.

## Command Semantics

### `suggest`

`suggest` performs these steps:

1. Load config, parameter space, objective schema, and state.
2. Initialize `state.meta.seed` from config if unset.
3. Check budget using `observations + pending`.
4. Generate candidate parameters and decision metadata.
5. Append a pending trial and increment `next_trial_id`.
6. Append one JSON line to `acquisition_log.jsonl`.
7. Persist updated state with atomic temp-file replace.
8. Print suggestion JSON.

Important implications:

- `suggest` is not idempotent; repeated calls usually produce new pending trials.
- If budget is exhausted, no pending trial is created.

### `ingest`

`ingest` performs these steps:

1. Load config, objective schema, result schema, and state.
2. Validate payload shape and objective value rules.
3. Require `trial_id` to exist in pending set.
4. Require payload `params` to exactly match pending suggestion params.
5. Remove pending trial and append observation.
6. Recompute `best` using `status == "ok"` observations only.
7. Persist state with atomic temp-file replace.
8. Rewrite `observations.csv` from full observation history.

Current behavior (`v0.1`):

- Canonical accepted statuses: `ok`, `failed`.
- Duplicate replay is rejected once a trial is no longer pending.
- Primary objective is required numeric and finite.

### `status`

`status` reads state and prints:

- `observations`
- `pending`
- `next_trial_id`
- `best`

It does not mutate state.

## Pending Trial Semantics

- Pending is created only by `suggest`.
- Pending is resolved only by successful `ingest`.
- Pending entries are counted toward budget.
- Multiple pending entries can exist if `suggest` is called repeatedly before
  ingesting results.
- No built-in stale pending expiry exists yet.

## Duplicate Ingest and Idempotency

| Scenario | Current `v0.1` behavior | `v0.2 target` |
|---|---|---|
| First valid ingest for pending trial | Accepted | Accepted |
| Replaying same payload after resolution | Rejected (`trial_id is not pending`) | Planned idempotent accept/no-op |
| Replaying conflicting payload | Rejected | Rejected with mismatch detail |

For current integrations, treat ingest as strictly single-use per `trial_id`.

## Resume and Crash Recovery

The templates are restartable because state is file-backed and loaded each run.

Recovery model:

- If process exits, next command resumes from `bo_state.json`.
- `observations.csv` can be regenerated from state by re-ingesting or by tooling
  added later.
- `acquisition_log.jsonl` may contain events not represented in state if a crash
  happens after log append but before state save.

Pragmatic recovery playbook:

1. Stop all writers.
2. Inspect `state/bo_state.json` for pending and observations.
3. Treat `acquisition_log.jsonl` as audit context, not source of truth.
4. For each pending trial, either ingest a matching result or mark it failed in
   your external workflow policy.
5. Resume with `status`, then continue `suggest -> ingest`.

## Reproducibility and Determinism Boundaries

Current deterministic anchors:

- Initial seed is persisted in `state.meta.seed`.
- Candidate generation uses deterministic `random.Random(seed + next_trial_id)`.
- With identical state/config/backend path, candidate scoring is intended to be
  reproducible.

Known nondeterminism boundaries:

- Wall-clock timestamps (`suggested_at`, `completed_at`, log timestamps).
- External evaluator runtime behavior and any uncontrolled randomness.
- Optional GP backends may vary by dependency versions and numeric libraries.

## Contract Transition Notes

Planned `v0.2` contract changes (implemented in later phases):

- Status vocabulary expands to `ok|failed|killed|timeout`.
- `success` ingest alias normalizes to `ok`.
- Non-`ok` statuses use `objective: null` with optional `penalty_objective`.
- Duplicate identical ingest replay becomes idempotent.
