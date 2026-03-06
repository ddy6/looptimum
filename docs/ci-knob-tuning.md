# CI Knob Tuning Playbook

This playbook defines a reproducible CI operating model for
`suggest -> evaluate -> ingest` workflows.
It is platform-agnostic and uses GitHub Actions snippets as concrete examples.

## Scope

Primary goals:

- preserve resumable state across CI runs
- avoid measurement contamination
- scale evaluator throughput safely
- produce robust recommendations, not single-run noise winners

Normative baseline in this document:

- one controller/writer per `state/` path
- CI artifact persistence default
- cold-run objective mode default
- robust-best policy = top-k + median-of-repeats

## 1) Pipeline Topology (Portable)

Recommended topology:

1. `controller_suggest` job acquires/uses state and emits one or more suggestions.
2. `evaluator` jobs fan out and execute suggested params.
3. `controller_ingest` job serially ingests evaluator payloads.
4. `controller_report` job publishes summary artifacts.

Key rule:

- only controller jobs mutate `state/` files.
- evaluator jobs do not write `state/` directly.

## 2) State Persistence Strategy

Default (recommended): CI artifacts.

- upload `state/` artifacts at end of mutating controller jobs
- download the latest artifact at start of next controller job/run
- keep artifact retention short but sufficient for retry/recovery windows

Required artifact set:

- `state/bo_state.json`
- `state/event_log.jsonl`
- `state/acquisition_log.jsonl`
- `state/observations.csv` (derived but useful)
- `state/trials/**` (manifests + payload copies)
- `state/report.json` / `state/report.md` when generated

Enterprise upgrade path:

- use object storage (S3/GCS/Azure Blob/minio) for longer retention,
  cross-runner portability, and larger histories.

Discouraged pattern:

- committing mutable `state/` snapshots to git branches (except tiny demos).
  This introduces merge conflicts, hidden drift, and audit ambiguity.

## 3) Safe Parallelism and Queueing

Supported:

- one controller per `state/` path
- evaluator fan-out behind a queue/worker pool

Unsupported:

- multiple controllers writing to the same `state/` path.

Why unsupported:

- suggestion races
- duplicate/overlapping pending trial creation
- conflicting manifest updates and retry ambiguity

Queueing guidance:

- bound in-flight evaluations using explicit concurrency limit
- ingest results in deterministic order (by completion time or trial id)
- on repeated lock contention, fail fast and retry controller job

## 4) Contamination Controls

Default objective mode: cold-run measurement.

Cold-run controls:

- reset caches between trials where feasible
- standardize runner shape (CPU class/memory)
- pin dependency versions and evaluator settings
- capture warmup count and discard warmup measurements from scoring

Warm-cache mode:

- treat as separate objective mode (or separate benchmark class)
- do not mix cold and warm metrics into one ranking stream
- label reports explicitly (`mode: cold` vs `mode: warm`)

Network/jitter controls:

- cap retries with consistent backoff policy
- record runtime metadata (`runtime_seconds`, timeout reason)
- use repeat measurements for noisy paths

## 5) Robust-Best Selection Policy

Default policy: top-k + median-of-repeats.

Recommended procedure:

1. rank candidate configs by primary objective
2. select top-k (for example `k=3` or `k=5`)
3. run each candidate for `n` repeats (for example `n=3`)
4. choose winner by median objective

Alternatives:

- trimmed mean over repeats (acceptable for smoother noise profiles)
- single best run (fast, but risky and outlier-prone)

Reporting requirement:

- publish both single-run best and robust-best with repeat statistics.

## 6) GitHub Actions Example (Reference)

```yaml
name: ci-knob-tuning-example

on:
  workflow_dispatch:

jobs:
  controller_suggest:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"
      - run: python -m pip install -r requirements-dev.txt
      - run: python templates/bo_client/run_bo.py suggest --project-root templates/bo_client --json-only > /tmp/suggestion.json
      - uses: actions/upload-artifact@v4
        with:
          name: looptimum-state
          path: templates/bo_client/state

  evaluator:
    needs: controller_suggest
    runs-on: ubuntu-latest
    strategy:
      fail-fast: false
      matrix:
        shard: [1, 2, 3]
    steps:
      - uses: actions/checkout@v4
      - uses: actions/download-artifact@v4
        with:
          name: looptimum-state
          path: templates/bo_client/state
      - run: echo "Run external evaluator here; write result payload artifact"

  controller_ingest:
    needs: evaluator
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/download-artifact@v4
        with:
          name: looptimum-state
          path: templates/bo_client/state
      - run: |
          python templates/bo_client/run_bo.py ingest \
            --project-root templates/bo_client \
            --results-file /path/to/result.json
      - uses: actions/upload-artifact@v4
        with:
          name: looptimum-state
          path: templates/bo_client/state
```

Platform translation notes:

- GitLab CI: map artifact upload/download to `artifacts` + `dependencies`.
- Jenkins: map persistence to archived artifacts or external blob store.
- Buildkite: map persistence to artifact API + queue-based fan-out steps.

## 7) Operator Run Sequence (Normative)

If CI run is interrupted or canceled:

1. restore latest persisted `state/` artifact
2. run `status`
3. run `validate`
4. ingest any completed result payloads
5. retire stale pending if needed
6. continue with next `suggest`

Reference commands:

```bash
python3 templates/bo_client/run_bo.py status --project-root templates/bo_client
python3 templates/bo_client/run_bo.py validate --project-root templates/bo_client
python3 templates/bo_client/run_bo.py retire --project-root templates/bo_client --stale
python3 templates/bo_client/run_bo.py report --project-root templates/bo_client
```

For failure triage and replay handling, pair this playbook with
`docs/recovery-playbook.md`.
