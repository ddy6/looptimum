# Integration Starter Kit

This page explains the optional starter-kit assets under
`client_harness_template/` that help teams wire Looptimum into schedulers,
event sidecars, and experiment trackers without changing the core
file-backed authority model.

The source of truth remains the same:

1. controller runs `suggest`
2. evaluator runs externally
3. controller or worker wrapper runs `ingest`
4. state, reports, and logs stay local under `state/`

## What Ships

Current starter-kit modules:

- `client_harness_template/starterkit_config.py` and
  `client_harness_template/starterkit_events.py`: config loading plus
  normalized lifecycle-event replay from `state/event_log.jsonl`
- `client_harness_template/starterkit_scheduler.py`: canonical suggestion
  parsing and shell-command rendering
- `client_harness_template/starterkit_queue_worker.py`: generic queue-worker
  wrapper for `suggest -> run_one_eval.py -> ingest`
- `client_harness_template/starterkit_airflow.py`: Airflow DAG render helper
- `client_harness_template/starterkit_slurm.py`: Slurm array-script render helper
- `client_harness_template/starterkit_tracking.py`: canonical state/report /
  manifest snapshot loader for reporting adapters
- `client_harness_template/starterkit_mlflow.py` and
  `client_harness_template/starterkit_wandb.py`: optional post-hoc tracker
  adapters with lazy imports

These helpers are optional. They wrap existing public contracts instead of
adding a second runtime path.

## Safe Topology

Recommended ownership boundaries:

- one controller owns `suggest` for a given campaign root
- workers may evaluate one allocated suggestion and optionally call
  `heartbeat` / `ingest` for that same trial
- webhook delivery runs as an event-log sidecar that reads
  `state/event_log.jsonl`; it does not sit inline on mutating CLI commands
- MLflow / W&B synchronization runs post-hoc or post-ingest and stays
  read-only with respect to Looptimum state

Do not run multiple controllers against the same `state/` root. The starter-kit
assets assume the same one-controller/file-lock model as the core CLI.

## Scheduler Patterns

### Generic Queue Worker

Use `starterkit_queue_worker.py` when you already have a batch of canonical
suggestion payloads and want one worker process per suggestion.

The worker wrapper:

- selects one suggestion from JSON, bundle JSON, or JSONL input
- writes a one-suggestion JSON file for auditability
- runs `run_one_eval.py`
- runs `ingest`, including `--lease-token` when the suggestion carries one

This is the smallest starter path for Kubernetes jobs, internal queues, or
simple subprocess-based schedulers.

### Airflow

Use `starterkit_airflow.py` when you want one controller task and a bounded
fan-out of worker tasks.

Recommended posture:

- controller task runs `suggest --count N --jsonl`
- worker tasks consume the shared JSONL file via `--worker-index`
- `max_active_runs=1` keeps one-controller semantics explicit

### Slurm

Use `starterkit_slurm.py` when you want one controller step and a Slurm array
for workers.

Recommended posture:

- controller runs `suggest --count N --jsonl`
- `sbatch --array 0-(N-1)` launches workers
- each array task passes `--worker-index "${SLURM_ARRAY_TASK_ID}"`

## Webhook Delivery Posture

Webhook integration is intentionally sidecar-only in the starter kit.

Use `starterkit_config.py` plus `starterkit_events.py` to:

- load a local config file that points at `state/event_log.jsonl`
- normalize runtime events into higher-level topics:
  `suggested`, `ingested`, `failed`, `reset`, `restore`
- replay only unseen events with a cursor file
- shape outbound webhook payloads without mutating Looptimum state

Operational rule:

- advance the cursor only after downstream delivery is durably acknowledged

That keeps retries external to the optimizer and avoids coupling network health
to CLI mutation success.

## Tracker Boundaries

`starterkit_mlflow.py` and `starterkit_wandb.py` consume canonical local
artifacts:

- `state/bo_state.json`
- optional `state/report.json`
- trial manifests
- normalized starter lifecycle events

They are designed for:

- post-ingest synchronization
- report publication
- ad hoc state snapshots after a controller step

They are not designed to mutate campaign state or to become a second control
plane.

## Retry Guidance

Keep retries at the correct boundary:

1. Do not blindly retry `suggest` from multiple controller processes. Treat it
   as a single-owner mutation.
2. Worker-side evaluation retries are safe before a successful `ingest`, as
   long as the suggestion payload stays unchanged.
3. If an `ingest` outcome is uncertain, inspect `status`, the pending list, and
   the trial manifest first. Identical replay is acceptable; conflicting replay
   is rejected by contract.
4. Webhook delivery retries should happen in the sidecar, not by re-running
   optimizer mutations.
5. Tracker synchronization retries are safe because they are read-only with
   respect to Looptimum state.

## Example Pack

Reference assets for the starter-kit surface live in:

- [`docs/examples/starterkit/README.md`](./examples/starterkit/README.md)

That pack includes:

- webhook config and normalized payload examples
- rendered Airflow and Slurm starter assets
- a queue-worker execution plan
- MLflow and W&B payload examples built around the canonical state/report view

Related packs:

- [`docs/examples/batch_async/README.md`](./examples/batch_async/README.md)
- [`docs/examples/warm_start/README.md`](./examples/warm_start/README.md)

These files are integration references, not benchmark claims.
