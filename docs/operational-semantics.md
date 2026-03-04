# Operational Semantics

This document defines current runtime behavior for public templates under
`templates/` using the file-backed `suggest -> ingest -> status` workflow.

## Contract Files

Canonical contract files are JSON:

- `bo_config.json`
- `parameter_space.json`
- `objective_schema.json`

Legacy `.yaml`/`.yml` contract files are still accepted for compatibility, but
emit deprecation warnings. Full YAML parsing requires installing YAML extras
(`pip install ".[yaml]"` or `pip install "looptimum[yaml]"`).

Schema path compatibility:

- canonical config key: `paths.ingest_schema_file`
- legacy key still accepted: `paths.result_schema_file` (deprecated warning)

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

1. Load config, objective schema, ingest schema, and state.
2. Validate payload shape and normalize status/objective fields.
3. Match `trial_id` to pending trials or evaluate duplicate replay behavior.
4. Require payload `params` to exactly match pending suggestion params.
5. Remove pending trial and append observation.
6. Recompute `best` using only `status == "ok"` observations.
7. Persist state with atomic temp-file replace.
8. Rewrite `observations.csv` from full observation history.

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

It does not mutate state.

## Pending Trial Semantics

- Pending is created only by `suggest`.
- Pending is resolved by successful `ingest`.
- Pending entries are counted toward budget.
- Multiple pending entries can exist if `suggest` is called repeatedly before
  ingesting results.
- No built-in stale pending expiry exists yet.

## Duplicate Ingest and Idempotency

| Scenario | Current behavior |
|---|---|
| First valid ingest for pending trial | Accepted |
| Replay of identical payload after resolution | Accepted as explicit no-op (`No-op: trial_id=<id> already ingested with identical payload.`) |
| Replay of conflicting payload after resolution | Rejected with field-level diff details |
| Replay for unknown non-pending/non-observed trial | Rejected (`trial_id <id> is not pending`) |

## Resume and Crash Recovery

Templates are restartable because state is file-backed and loaded each run.

Recovery model:

- If process exits, next command resumes from `bo_state.json`.
- `observations.csv` can be regenerated from canonical observations in state.
- `acquisition_log.jsonl` may contain events not represented in state if a
  crash happens after log append but before state save.

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
