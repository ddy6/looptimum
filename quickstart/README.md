# Quickstart

Run all commands from the repository root.

This is the quickest path to running Looptimum templates locally.

This quickstart uses explicit `--project-root` paths so each command is a single runnable line (easy copy/paste).

## Interpreter

These templates run with standard `python3` for proxy/demo workflows.

If you prefer a virtual environment, create one and swap `python3` for your venv interpreter.

Check your Python version:

```bash
python3 --version
```

Parameter types currently supported by the public templates: `float`, `int`.

## Variant Commands (Repo-Root Single Commands)

### `templates/bo_client_demo` (proxy-only, easiest path)

```bash
python3 templates/bo_client_demo/run_bo.py status --project-root templates/bo_client_demo
python3 templates/bo_client_demo/run_bo.py suggest --project-root templates/bo_client_demo
python3 templates/bo_client_demo/run_bo.py ingest --project-root templates/bo_client_demo --results-file templates/bo_client_demo/examples/example_results.json
python3 templates/bo_client_demo/run_bo.py demo --project-root templates/bo_client_demo --steps 5
```

### `templates/bo_client` (baseline harness, config-selected backend)

```bash
python3 templates/bo_client/run_bo.py status --project-root templates/bo_client
python3 templates/bo_client/run_bo.py suggest --project-root templates/bo_client
python3 templates/bo_client/run_bo.py ingest --project-root templates/bo_client --results-file templates/bo_client/examples/example_results.json
python3 templates/bo_client/run_bo.py demo --project-root templates/bo_client --steps 5
```

Optional GP backend (after dependencies are installed and `surrogate.type` is set to `gp` in `templates/bo_client/bo_config.yaml`):

```bash
python3 templates/bo_client/run_bo.py suggest --project-root templates/bo_client
```

### `templates/bo_client_full` (optional BoTorch GP feature flag)

```bash
python3 templates/bo_client_full/run_bo.py status --project-root templates/bo_client_full
python3 templates/bo_client_full/run_bo.py suggest --project-root templates/bo_client_full
python3 templates/bo_client_full/run_bo.py suggest --project-root templates/bo_client_full --enable-botorch-gp
python3 templates/bo_client_full/run_bo.py ingest --project-root templates/bo_client_full --results-file templates/bo_client_full/examples/example_results.json
python3 templates/bo_client_full/run_bo.py demo --project-root templates/bo_client_full --steps 5
```

Note: If BoTorch is unavailable and the template config allows fallback, `bo_client_full` falls back to proxy mode and records the reason in acquisition logs.

## First Clean-Run Flow (Practical Starting Path)

On a clean template copy (no existing state), the bundled `example_results.json` matches the deterministic first suggestion for the default seed.

```bash
python3 templates/bo_client_demo/run_bo.py suggest --project-root templates/bo_client_demo
python3 templates/bo_client_demo/run_bo.py ingest --project-root templates/bo_client_demo --results-file templates/bo_client_demo/examples/example_results.json
python3 templates/bo_client_demo/run_bo.py status --project-root templates/bo_client_demo
```

If you already generated a different pending suggestion, generate a matching payload instead of reusing `example_results.json`.

## State Files and Resume Behavior

State and logs are configured in each template's `bo_config.yaml` and default to:

- `state/bo_state.json`: resumable run state (`observations`, `pending`, `next_trial_id`, `best`)
- `state/observations.csv`: flattened observation history written after ingest
- `state/acquisition_log.jsonl`: append-only suggestion decision trace
- `schemas/result_payload.schema.json`: payload structure for `ingest`

Resume rules:

1. `suggest` adds a pending trial and increments `next_trial_id`.
2. External evaluation must return the same `trial_id` and exact `params`.
3. `ingest` removes the matching pending trial, appends an observation, updates `best`, and rewrites `observations.csv`.
4. Re-running `ingest` for an already ingested trial is rejected (no state corruption).
5. If the budget is exhausted, `suggest` exits cleanly with no new pending trial.

## State File Examples

Reference snapshots (captured from a temp run of `templates/bo_client_demo`) are checked in under `docs/examples/state_snapshots/`:

- `docs/examples/state_snapshots/status_empty.json`
- `docs/examples/state_snapshots/suggestion_1.json`
- `docs/examples/state_snapshots/bo_state_after_suggest.json`
- `docs/examples/state_snapshots/acquisition_log_after_suggest.jsonl`
- `docs/examples/state_snapshots/result_1_generated.json`
- `docs/examples/state_snapshots/bo_state_after_ingest.json`
- `docs/examples/state_snapshots/observations_after_ingest.csv`
- `docs/examples/state_snapshots/status_after_ingest.json`

## Synthetic Helper (Payload Generation Example)

For local testing without an external system, the demo template includes a helper that converts a suggestion JSON into a valid result payload:

```bash
python3 templates/bo_client_demo/scripts/synthetic_experiment.py docs/examples/state_snapshots/suggestion_1.json /tmp/result.json
```

For a live run, pass the exact suggestion JSON produced by `suggest` (not full stdout with the trailing `Objective direction: ...` line).
For strict machine-readable `suggest` output, use `--json-only`.

## Test Command (Repo Root)

```bash
python3 -m pytest -q templates
```
