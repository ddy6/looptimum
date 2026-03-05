# Operational Semantics

This document defines current runtime behavior for public templates under
`templates/` using the file-backed `suggest -> ingest -> status` workflow.

## Contract Files

Canonical contract files are JSON:

- `bo_config.json`
- `parameter_space.json`
- `objective_schema.json`

Legacy `.yaml`/`.yml` contract files are still accepted for compatibility, but
require compatibility mode:
set `LOOPTIMUM_YAML_COMPAT_MODE=1` (optionally constrain file names via
`LOOPTIMUM_YAML_COMPAT_ALLOWLIST`).
YAML usage emits deprecation warnings and is scheduled for removal in `v0.4.0`.
Full YAML parsing requires installing YAML extras (`pip install ".[yaml]"` or
`pip install "looptimum[yaml]"`).

Schema path compatibility:

- canonical config key: `paths.ingest_schema_file`
- legacy key still accepted: `paths.result_schema_file` (deprecated warning;
  scheduled removal in `v0.4.0`)

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

1. Load config, parameter space, objective schema, and state.
2. Initialize `state.meta.seed` from config if unset.
3. Acquire exclusive lock for mutation.
4. Optionally auto-retire stale pending trials (based on `max_pending_age_seconds`).
5. Check budget using `observations + pending`.
6. Generate candidate parameters and decision metadata.
7. Append a pending trial and increment `next_trial_id`.
8. Write/update trial manifest for pending trial.
9. Append one JSON line to `acquisition_log.jsonl`.
10. Append lifecycle events to `event_log.jsonl`.
11. Persist updated state with atomic write.
12. Print suggestion JSON.

Important implications:

- `suggest` is not idempotent; repeated calls usually produce new pending trials.
- If budget is exhausted, no pending trial is created.
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

Primary objective handling:

- `status == "ok"`: primary objective must be numeric and finite.
- non-`ok` status: primary objective is normalized to `null`.
- optional `penalty_objective` is accepted for non-`ok` statuses.
- `best` is computed only from `status == "ok"` primary objective values;
  `penalty_objective` is not used for ranking.

Compatibility path (v0.2.x):

- Legacy non-`ok` payloads with numeric primary objective are still accepted.
- They are normalized to `objective: null` plus `penalty_objective`.
- A deprecation warning is emitted; sentinel primary objective support is planned
  for removal in `v0.3.0`.

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

### `validate`

- `validate` checks config/schema/state consistency and basic corruption.
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

- Mutating commands use an exclusive lock file (`state/.looptimum.lock`).
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
  crash happens after log append but before state save.
- `event_log.jsonl` provides additional lifecycle trace context but is not
  authoritative state.
- Per-trial manifests in `state/trials/` are audit helpers and can be rebuilt
  from canonical state + payload history.

Pragmatic recovery playbook:

1. Stop all writers.
2. Inspect `state/bo_state.json` for pending and observations.
3. Treat `acquisition_log.jsonl` as audit context, not source of truth.
4. For each pending trial, either ingest a matching result or apply your
   external failure policy.
5. Resume with `status`, then continue `suggest -> ingest`.

## Reproducibility and Determinism Boundaries

Deterministic anchors:

- Initial seed persisted in `state.meta.seed`.
- Candidate generation based on deterministic seed + trial id progression.
- Stable config/state/backend path yields stable suggestion order.

Known nondeterminism boundaries:

- Wall-clock timestamps (`suggested_at`, `completed_at`, log timestamps).
- External evaluator runtime behavior and uncontrolled randomness.
- Optional GP backend numerical/runtime differences across environments.
