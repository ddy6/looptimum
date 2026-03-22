# Operational Semantics

This document defines current runtime behavior for public templates under
`templates/` using the file-backed `suggest -> ingest -> status` workflow.

## Contract Files

Canonical contract files are JSON:

- `bo_config.json`
- `parameter_space.json`
- `objective_schema.json`
- `constraints.json` (optional)

Schema path compatibility:

- canonical config key: `paths.ingest_schema_file`

## Core Files and Authority

| File | Role | Authority Level |
|---|---|---|
| `state/bo_state.json` | Source of truth for `schema_version`, pending trials, observations, best-so-far, and next trial id | Authoritative |
| `state/acquisition_log.jsonl` | Append-only decision log for each suggestion | Audit trail, not authoritative state |
| `state/event_log.jsonl` | Append-only lifecycle/ops log (locks, heartbeat, retire/cancel, report) | Audit trail, not authoritative state |
| `state/trials/trial_<id>/manifest.json` | Per-trial audit manifest and artifact pointers | Derived from authoritative state/payloads |
| `state/observations.csv` | Flattened export of observations | Derived artifact |
| `state/report.json` / `state/report.md` | Explicit generated report outputs | Derived artifact |

Operational rule: when files disagree, treat `state/bo_state.json` as canonical.

State schema versioning rule:

- `state.schema_version` is required for `v0.3.0` state artifacts and follows
  semver string format.
- legacy `v0.2.x` (or missing-version) state is upgraded in-memory and persisted
  on the next mutating command, with a loud warning and migration pointer.
- earlier `v0.3.x` state versions load transparently in `v0.3.x`.

## Supported Topology

- Supported topology today: one controller process writes state.
- Mutating commands enforce an exclusive file lock (`state/.looptimum.lock`) with
  wait+timeout semantics by default.
- Evaluators can run in separate environments, but should not mutate state
  files directly.
- Do not run multiple controllers intentionally against the same state path;
  lock contention is treated as an operational error surface.

## Command Semantics

### `suggest`

`suggest` performs these steps:

1. Load config, parameter space, objective schema, optional constraints, and state.
2. Initialize `state.meta.seed` from config if unset.
3. Acquire exclusive lock for mutation.
4. Optionally auto-retire stale pending trials (based on `max_pending_age_seconds`).
5. Check budget using `observations + pending`.
6. Generate candidate parameters and decision metadata.
7. If all sampled attempts are infeasible, append a failure decision to
   `acquisition_log.jsonl` and exit nonzero without creating pending state.
8. On success, append a pending trial and increment `next_trial_id`.
9. Write/update trial manifest for the pending trial.
10. Append one JSON line to `acquisition_log.jsonl`.
11. Append lifecycle events to `event_log.jsonl`.
12. Persist updated state with atomic write.
13. Print suggestion JSON.

Important implications:

- `suggest` is not idempotent; repeated calls usually produce new pending trials.
- If budget is exhausted, no pending trial is created.
- If constraints eliminate all sampled attempts, no pending trial is created and
  the failed decision is still logged for audit/debugging.
- Automatic stale retirement is conservative and age-based; it records terminal
  `killed` observations with a stale-retire reason.

### `ingest`

`ingest` performs these steps:

1. Load config, objective schema, ingest schema, and state.
2. Acquire exclusive lock for mutation.
3. Validate payload shape and normalize status/objective fields.
4. Match `trial_id` to pending trials or evaluate duplicate replay behavior.
5. Require payload `params` to exactly match pending suggestion params.
6. Remove pending trial and append observation.
7. Merge optional heartbeat metadata fields if provided.
8. Recompute `best` using only `status == "ok"` observations.
9. Persist state and rewrite `observations.csv` using atomic writes.
10. Write/update per-trial manifest and append lifecycle events.

Status handling:

- Canonical statuses: `ok`, `failed`, `killed`, `timeout`
- `success` is accepted as a deprecated alias and normalized to `ok`

Objective handling:

- `status == "ok"`: all configured objective values must be numeric and finite.
- non-`ok` status: all configured objective values must be `null`.
- optional `terminal_reason` is accepted for non-`ok` statuses.
- optional `penalty_objective` is accepted for non-`ok` statuses.
- `best` is computed only from `status == "ok"` observations.
- Single-objective campaigns rank by the primary objective.
- Multi-objective campaigns rank by the configured scalarization or
  lexicographic policy; manifests and reports preserve raw `objective_vector`
  data alongside scalarized metadata.
- `penalty_objective` is not used for ranking.

Terminal-reason handling:

- legacy `failure_reason` is accepted and normalized to `terminal_reason`
  (deprecation warning).
- if non-`ok` payloads omit both fields, `terminal_reason` is synthesized as
  `status=<status>`.

Compatibility path (v0.2.x):

- Legacy `failure_reason` remains the only accepted non-canonical alias in this
  area; numeric objective values for non-`ok` payloads are rejected.

### `status`

`status` reads state and prints:

- `observations`
- `pending`
- `next_trial_id`
- `best`
- `schema_version`
- `stale_pending`
- `observations_by_status`
- `paths` (state/log/artifact locations)

It does not mutate state.

Multi-objective note:

- when multiple objectives are configured, `best` may also include
  `scalarization_policy` and raw `objective_vector` fields.

### `cancel` and `retire`

- `cancel --trial-id <id>`: removes a pending trial and records terminal
  observation status `killed` with terminal reason (default `canceled`).
- `retire --trial-id <id>`: same terminal behavior with operator-selected reason.
- `retire --stale [--max-age-seconds]`: retire pending trials older than the
  configured/explicit age threshold.

### `heartbeat`

- `heartbeat --trial-id <id>` updates pending liveness metadata:
  `last_heartbeat_at`, `heartbeat_count`, optional note/meta.
- `ingest` also accepts optional heartbeat fields in payload for compatibility
  with evaluator-side metadata pipelines.

### `report`

- `report` is explicit (not auto-on-ingest).
- It writes `state/report.json` and `state/report.md` atomically.
- multi-objective reports include normalized `objective_config`, scalarized
  ranking metadata, raw `objective_vector` values, and `pareto_front` summary
  data.

### `reset`

- `reset` is destructive and requires explicit confirmation (interactive token)
  or `--yes`.
- By default, reset archives current runtime artifacts under
  `state/reset_archives/<reset-id>/` before cleanup.
- `--no-archive` skips archive creation.
- Reset cleanup targets runtime artifacts only (state/log/report/trials/demo
  result), not project config/schema/code files.

### `validate`

- `validate` checks config/schema/state consistency and basic corruption.
- when `constraints.json` is present, `validate` also performs semantic
  constraint normalization checks
- Hard failures return non-zero exit.
- Warnings are informational with exit 0 unless `--strict`.

### `doctor`

- `doctor` prints environment/backend/state diagnostics.
- `doctor --json` emits machine-readable diagnostics for tooling/CI.

## Pending Trial Semantics

- Pending is created only by `suggest`.
- Pending is resolved by successful `ingest`.
- Pending can be terminally resolved via `cancel`/`retire`.
- Pending entries are counted toward budget.
- Multiple pending entries can exist if `suggest` is called repeatedly before
  ingesting results.
- Built-in stale handling exists:
  - automatic stale retirement in `suggest` (when `max_pending_age_seconds` is configured/enabled)
  - explicit stale retirement via `retire --stale`

## Duplicate Ingest and Idempotency

| Scenario | Current behavior |
|---|---|
| First valid ingest for pending trial | Accepted |
| Replay of identical payload after resolution | Accepted as explicit no-op (`No-op: trial_id=<id> already ingested with identical payload.`) |
| Replay of conflicting payload after resolution | Rejected with field-level diff details |
| Replay for unknown non-pending/non-observed trial | Rejected (`trial_id <id> is not pending`) |

## Locking Semantics

- Mutating commands (`suggest`, `ingest`, lifecycle ops, `report`, `reset`)
  use an exclusive lock file (`state/.looptimum.lock`).
- Default behavior waits for lock with timeout; `--fail-fast` switches to
  immediate failure on contention.
- Read-oriented commands (`status`, `validate`, `doctor`) do not require
  exclusive lock.

## Resume and Crash Recovery

Templates are restartable because state is file-backed and loaded each run.

Recovery model:

- If process exits, next command resumes from `bo_state.json`.
- `observations.csv` can be regenerated from canonical observations in state.
- `acquisition_log.jsonl` may contain events not represented in state if a
  `suggest` attempt was logged but produced no pending trial (for example an
  all-infeasible constrained attempt), or if a crash happens after log append
  but before state save.
- `event_log.jsonl` provides additional lifecycle trace context but is not
  authoritative state.
- Per-trial manifests in `state/trials/` are audit helpers and can be rebuilt
  from canonical state + payload history.

Operator runbook pointer:

1. Use `docs/recovery-playbook.md` for prescriptive command sequences,
   decision-tree handling (`ingest` failure, stale pending, conflicting replay),
   and CI/local exit-code follow-up actions.
2. Use this document as the normative contract reference when verifying expected
   semantics during recovery.

## Reproducibility and Determinism Boundaries

Deterministic anchors:

- Initial seed persisted in `state.meta.seed`.
- Candidate generation based on deterministic seed + trial id progression.
- Stable config/state/backend path yields stable suggestion order.

Known nondeterminism boundaries:

- Wall-clock timestamps (`suggested_at`, `completed_at`, log timestamps).
- External evaluator runtime behavior and uncontrolled randomness.
- Optional GP backend numerical/runtime differences across environments.
