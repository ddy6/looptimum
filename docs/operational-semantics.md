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
| `state/event_log.jsonl` | Append-only lifecycle/ops log (locks, heartbeat, import/export, retire/cancel, report, governance events) | Audit trail, not authoritative state |
| `state/import_reports/import-*.json` | Permissive warm-start import summaries plus rejected-row detail | Derived artifact |
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
5. Resolve requested batch count from `--count` or `bo_config.batch_size`.
6. Reject the whole request if `max_pending_trials` or budget would be exceeded.
7. Generate one or more candidate parameter payloads and decision records.
8. If all sampled attempts are infeasible, append a failure decision to
   `acquisition_log.jsonl` and exit nonzero without creating pending state.
9. On success, append all pending trials and increment `next_trial_id` by the
   allocated count.
10. Write/update trial manifests for the pending trials.
11. Append one JSON line per allocated trial to `acquisition_log.jsonl`.
12. Append lifecycle events to `event_log.jsonl`.
13. Persist updated state with atomic write.
14. Print single-suggestion JSON, bundle JSON, or JSONL output.

Important implications:

- `suggest` is not idempotent; repeated calls usually produce new pending trials.
- `count == 1` preserves the historical single-suggestion JSON contract.
- `count > 1` defaults to bundle JSON and `--jsonl` emits one suggestion object
  per line.
- If budget is exhausted, no pending trial is created.
- If `max_pending_trials` would be exceeded, the whole requested batch is
  rejected before any pending state is created.
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

- if non-`ok` payloads omit both fields, `terminal_reason` is synthesized as
  `status=<status>`.

### `status`

`status` reads state and prints:

- `observations`
- `pending`
- `leased_pending`
- `next_trial_id`
- `best`
- `schema_version`
- `stale_pending`
- `observations_by_status`
- `worker_leases_enabled`
- `paths` (state/log/artifact locations)

It does not mutate state.

Multi-objective note:

- when multiple objectives are configured, `best` may also include
  `scalarization_policy` and raw `objective_vector` fields.

### `import-observations`

- `import-observations --input-file <path>` accepts either canonical JSONL
  observation objects or flat CSV rows with `param_*` / `objective_*` columns.
- import requires zero live pending trials in the target campaign.
- imported rows are terminal observations only; pending-trial import is out of
  scope.
- imported rows receive fresh local `trial_id` values from `state.next_trial_id`;
  any source-side ids are preserved only in `source_trial_id`.
- strict mode is all-or-nothing.
- permissive mode applies valid rows, writes
  `state/import_reports/import-*.json`, and records rejected-row detail without
  corrupting accepted observations.
- successful imports rewrite `state/observations.csv`, update manifests,
  recompute `best`, and advance `next_trial_id`.

### `export-observations`

- `export-observations --output-file <path>` writes canonical JSONL or flat CSV
  observations from authoritative state.
- exported JSONL uses canonical observation objects.
- exported CSV uses flat rows with `param_*` / `objective_*` columns and the
  same terminal metadata accepted by warm-start import.
- export does not mutate `state/bo_state.json`, but it does append audit
  provenance to `state/event_log.jsonl` and therefore still runs under the
  normal mutation lock.

### `cancel` and `retire`

- `cancel --trial-id <id>`: removes a pending trial and records terminal
  observation status `killed` with terminal reason (default `canceled`).
- `retire --trial-id <id>`: same terminal behavior with operator-selected reason.
- `retire --stale [--max-age-seconds]`: retire pending trials older than the
  configured/explicit age threshold.

### `heartbeat`

- `heartbeat --trial-id <id>` updates pending liveness metadata:
  `last_heartbeat_at`, `heartbeat_count`, optional note/meta.
- when worker leases are enabled and the pending trial carries `lease_token`,
  `heartbeat` requires matching `--lease-token`.
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

### `list-archives`

- `list-archives` is read-only and does not mutate runtime state.
- It inventories `state/reset_archives/` and surfaces archive id, created-at
  metadata, archived runtime-path summary, and integrity status.
- Manifest-less legacy reset archives remain visible as `status=legacy`.
- Broken or incomplete manifest-backed archives are listed with integrity
  errors instead of being silently ignored.

### `restore`

- `restore --archive-id <id>` is destructive and requires explicit
  confirmation or `--yes`.
- Restore validates archive integrity before mutating runtime artifacts.
- Restore rehydrates only the supported runtime-artifact set and intentionally
  does not restore the live lock file.
- Restore overwrites current runtime artifacts atomically: a failed restore
  rolls back to the pre-restore runtime state.

### `prune-archives`

- `prune-archives` is destructive and requires explicit confirmation or
  `--yes`.
- It applies retention criteria to `state/reset_archives/` without mutating
  active runtime artifacts.
- `--keep-last N` protects the newest `N` archives.
- `--older-than-seconds S` prunes only archives with known `created_at`
  timestamps whose age is at least `S`.
- Legacy archives with unknown age remain protected from age-only prune rules.

### `validate`

- `validate` checks config/schema/state consistency and basic corruption.
- when `constraints.json` is present, `validate` also performs semantic
  constraint normalization checks
- Hard failures return non-zero exit.
- Warnings are informational with exit 0 unless `--strict`.

### `health`

- `health` is read-only and does not mutate runtime artifacts.
- It aggregates validate-aligned hard errors/warnings, path presence, lock
  visibility, status counts, and governance findings into one JSON payload.
- `health_state` is `ok`, `warning`, or `error`.
- `--strict` makes warning-state output exit nonzero.

### `metrics`

- `metrics` is read-only and does not mutate runtime artifacts.
- It layers on top of `health` and adds counts, pending-age bucket summaries,
  explicit suggest-latency summaries from `acquisition_log.jsonl`, and
  governance warning/violation totals.

### `doctor`

- `doctor` prints environment/backend/state diagnostics.
- `doctor --json` emits machine-readable diagnostics for tooling/CI.

## Governance and Retention Semantics

- `governance.allowed_statuses` defines the policy set of accepted terminal
  statuses for the campaign.
- Ingested observations outside that set remain visible in authoritative state;
  they are surfaced as governance violations rather than rewritten or dropped.
- Runtime-generated terminal `killed` observations from `cancel`, `retire`, and
  automatic stale retirement append `governance_override_used` when `killed`
  falls outside `governance.allowed_statuses`.
- `retention.archives.*` and `retention.logs.*` are warn-first limits. They
  do not trigger automatic prune/rotation behavior.
- After successful mutating commands, Looptimum may append
  `governance_violations_detected` when observed statuses, archive inventory,
  or append-only log footprints breach configured policy.

## Pending Trial Semantics

- Pending is created only by `suggest`.
- Pending is resolved by successful `ingest`.
- Pending can be terminally resolved via `cancel`/`retire`.
- Pending entries are counted toward budget.
- Multiple pending entries can exist if `suggest --count N` allocates a batch
  or if `suggest` is called repeatedly before ingesting results.
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

- Mutating commands (`suggest`, `ingest`, `import-observations`,
  `export-observations`, lifecycle ops, `report`, `reset`, `restore`,
  `prune-archives`)
  use an exclusive lock file (`state/.looptimum.lock`).
- `list-archives`, `status`, `validate`, and `doctor` are read-only and do not
  take the mutation lock.
- Default behavior waits for lock with timeout; `--fail-fast` switches to
  immediate failure on contention.
- Batch `suggest` allocation, lease-aware `heartbeat`, and lease-aware `ingest`
  fail as a whole under lock contention; Looptimum does not partially mutate
  state before returning the contention error.
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
