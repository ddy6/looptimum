# Quick Reference

Use this page as the spec-style contract summary for day-to-day integration,
automation wiring, and runbook checks.

## Public Command Surface (`v0.3.x`)

Stable command names and required flag posture are documented in
[`stability-guarantees.md`](./stability-guarantees.md).

- core loop: `suggest`, `ingest`, `status`, `demo`
- lifecycle ops: `cancel`, `retire`, `heartbeat`
- support ops: `report`, `reset`, `validate`, `doctor`

## Core Loop Contract

1. `suggest`: emits one trial proposal (`trial_id`, `params`, `suggested_at`,
   `schema_version`) and records pending state on success.
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

- `schema_version`: semver string emitted by runtime
- `trial_id`: unique integer identifier in run scope
- `params`: exact parameter payload for external evaluation
- `suggested_at`: suggestion timestamp

Constraint note:

- if constraints eliminate all sampled attempts, `suggest` exits nonzero,
  creates no pending trial, and records the failure in `acquisition_log.jsonl`

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

Optional compatibility fields:

- `schema_version` (emitted by runtime; optional in ingest schema)
- legacy `success` alias (normalized to `ok`)
- legacy `failure_reason` alias (normalized to `terminal_reason`)

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

## State and Artifact Definitions

Default file-backed artifacts under each template's `state/` path:

- `bo_state.json`: authoritative resumable state (`schema_version`,
  observations, pending, best, counters)
- `observations.csv`: flattened observation export
- `acquisition_log.jsonl`: append-only suggestion-decision trace
- `event_log.jsonl`: append-only lifecycle/ops trace
- `trials/trial_<id>/manifest.json`: per-trial manifest/audit record
- `report.json` and `report.md`: explicit `report` command outputs, including
  objective-config and Pareto summaries for multi-objective campaigns

## Concurrency and Recovery

- one controller/writer per state path is required; multi-controller writes to
  the same state path are unsupported.
- mutating commands (`suggest`, `ingest`, lifecycle ops, `report`, `reset`)
  run under exclusive file lock semantics.
- `reset` removes runtime artifacts with confirmation; archive is enabled by
  default unless `--no-archive` is passed.
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
