# Quick Reference

Use this page as the spec-style contract summary for day-to-day integration,
automation wiring, and runbook checks.

## Public Command Surface (`v0.3.x`)

Stable command names and required flag posture are documented in
[`stability-guarantees.md`](./stability-guarantees.md).

- core loop: `suggest`, `ingest`, `status`, `demo`
- lifecycle ops: `cancel`, `retire`, `heartbeat`
- support ops: `import-observations`, `export-observations`, `report`, `reset`, `list-archives`, `restore`, `prune-archives`, `health`, `metrics`, `validate`, `doctor`

## Core Loop Contract

1. `suggest`: emits one trial proposal by default, or a locked batch when
   `--count N` / `bo_config.batch_size` requests more than one suggestion.
2. evaluator: runs externally using `params`; Looptimum does not execute your
   workload.
3. `ingest`: validates trial identity and payload shape, then clears pending
   and appends observation.
4. `status`: reports run headline state (`observations`, `pending`, `best`,
   `next_trial_id`, and related metadata).

Objective contract note:

- `objective_schema.json` defines a required `primary_objective`, optional
  `secondary_objectives`, and optional `scalarization` policy.

Optional hard-feasibility contract:

- `constraints.json`: validated by `validate` and enforced by `suggest`

## `suggest` Output (Canonical Fields)

Single-suggestion output (`count == 1`) is the canonical object:

- `schema_version`: semver string emitted by runtime
- `trial_id`: unique integer identifier in run scope
- `params`: exact parameter payload for external evaluation
- `suggested_at`: suggestion timestamp
- `lease_token`: optional opaque worker-claim token when leases are enabled

Batch output (`count > 1`) defaults to:

- `schema_version`
- `count`
- `suggestions`: array of canonical suggestion objects

`--jsonl` emits the same suggestion objects one per line for worker handoff.

Constraint note:

- if constraints eliminate all sampled attempts, `suggest` exits nonzero,
  creates no pending trial, and records the failure in `acquisition_log.jsonl`
- if `max_pending_trials` would be exceeded, the whole requested batch is
  rejected before pending state is mutated

## `ingest` Payload Contract

Required:

- `trial_id`: must match a currently pending trial
- `params`: must exactly match suggested params
- `objectives`: map containing every configured objective name
- `status`: `ok`, `failed`, `killed`, or `timeout`

Rules:

- `status: ok` requires numeric finite values for all configured objectives.
- non-`ok` status requires `null` for all configured objectives.
- optional `terminal_reason` (short string) is recommended for non-`ok`
  outcomes.
- optional `penalty_objective` is allowed for non-`ok` outcomes.
- `schema_version` is emitted by runtime and remains optional in the ingest
  schema.
- when a pending trial carries `lease_token`, the CLI requires matching
  `--lease-token` on `ingest`; the token is not embedded in the ingest payload

## Result and Failure Semantics

- `best` ranking uses only `status: "ok"` observations and the configured
  objective policy.
- multi-objective campaigns preserve raw `objective_vector` values and
  scalarized ranking metadata in status/manifests/reports.
- `penalty_objective` is never used for `best` ranking.
- non-`ok` payloads without an explicit reason are normalized to
  `terminal_reason: "status=<status>"`.
- identical duplicate ingest replay is accepted as explicit no-op success.
- conflicting duplicate ingest replay is rejected with mismatch details.

## Warm-Start Import / Export

- `import-observations --input-file <path>` accepts canonical JSONL observation
  objects or flat CSV rows with `param_*` / `objective_*` columns.
- `--import-mode strict` is all-or-nothing; `--import-mode permissive` applies
  valid rows, rejects invalid rows, and writes a machine-readable report under
  `state/import_reports/`.
- imported rows require zero live pending trials, receive fresh local
  `trial_id` values from `state.next_trial_id`, and preserve any
  `source_trial_id` only as provenance.
- imported observations are first-class terminal observations: manifests,
  `best`, `next_trial_id`, `observations.csv`, and later `report` outputs are
  updated from authoritative state.
- `export-observations --output-file <path>` writes the same canonical JSONL or
  flat CSV observation surface for reuse in future campaigns.

## State and Artifact Definitions

Default file-backed artifacts under each template's `state/` path:

- `bo_state.json`: authoritative resumable state (`schema_version`,
  observations, pending, best, counters)
- `observations.csv`: flattened observation export
- `acquisition_log.jsonl`: append-only suggestion-decision trace
- `event_log.jsonl`: append-only lifecycle/ops trace
- `import_reports/*.json`: permissive warm-start import summaries plus rejected
  row details
- `trials/trial_<id>/manifest.json`: per-trial manifest/audit record
- `report.json` and `report.md`: explicit `report` command outputs, including
  objective-config and Pareto summaries for multi-objective campaigns

## Observability and Governance

- `health [--strict]` is the read-only machine-readable health surface; it
  combines validate-aligned hard errors/warnings, path presence, lock state,
  and governance findings.
- `metrics` is the read-only machine-readable metrics surface; it adds counts,
  pending-age buckets, suggest-latency summaries, and governance totals.
- `bo_config.json` can set `governance.allowed_statuses`,
  `retention.archives.max_count`, `retention.archives.max_age_seconds`,
  `retention.archives.max_total_bytes`,
  `retention.logs.event_log_max_bytes`, and
  `retention.logs.acquisition_log_max_bytes`.
- Retention is warn-first: Looptimum surfaces policy breaches but does not
  auto-prune archives or rotate append-only logs.
- Mutating commands append `governance_override_used` when the runtime itself
  emits a terminal status outside `governance.allowed_statuses`, and
  `governance_violations_detected` when observed statuses or retention
  footprints breach configured policy.

## Concurrency and Recovery

- one controller/writer per state path is required; multi-controller writes to
  the same state path are unsupported.
- mutating commands (`suggest`, `ingest`, `import-observations`, lifecycle ops,
  `report`, `reset`, `restore`, `prune-archives`, `export-observations`)
  run under exclusive file lock semantics.
- batch allocation is atomic under that lock: contention or validation failure
  rejects the whole batch with no partial pending creation.
- `reset` removes runtime artifacts with confirmation; archive is enabled by
  default unless `--no-archive` is passed.
- `list-archives` is read-only and inventories `state/reset_archives/`,
  including legacy manifest-less archives and any integrity warnings.
- `restore --archive-id <id> --yes` rehydrates archived runtime artifacts with
  integrity checks and all-or-nothing overwrite behavior.
- `prune-archives --keep-last N --older-than-seconds S --yes` deletes only
  archives that match the requested retention policy; legacy archives with
  unknown age are never pruned by age alone.
- stale pending handling can be automated via configured age policy or manual
  `retire`.
- interruption recovery runbook:
  [`recovery-playbook.md`](./recovery-playbook.md).

Constraint pointers:

- `search-space.md`: parameter types, `scale`, and `when`
- `constraints.md`: hard-constraint DSL and troubleshooting

## Compatibility

- `v0.2.x` state without `schema_version` (or with `0.2.x`) is upgraded
  in-memory and persisted on the next mutating command.
- earlier `v0.3.x` state is required to load transparently in `v0.3.x`.
- deprecation and compatibility policy:
  [`stability-guarantees.md`](./stability-guarantees.md).

## Reproducibility and Trust Anchors

- algorithm behavior and determinism boundaries:
  [`how-it-works.md`](./how-it-works.md).
- benchmark evidence and reproducibility protocol:
  [`../benchmarks/README.md`](../benchmarks/README.md).
- CI and operational runbook policy:
  [`ci-knob-tuning.md`](./ci-knob-tuning.md).
