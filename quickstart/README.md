# Quickstart

Run all commands from the repository root.

This is the quickest path to running Looptimum templates locally.

This quickstart uses explicit `--project-root` paths so each command is a
single runnable line (easy copy/paste).

## Interpreter

These templates run with standard `python3` for proxy/demo workflows.

If you prefer a virtual environment, create one and swap `python3` for your venv interpreter.

Check your Python version:

```bash
python3 --version
```

Parameter types currently supported by the public templates: `float`, `int`.

Quickstart noise policy:

- The commands in this guide use canonical JSON contract files/keys and should
  run without compatibility/deprecation warnings on a clean template copy.

## Variant Commands (Repo-Root Single Commands)

### `templates/bo_client_demo` (proxy-only, easiest path)

```bash
python3 templates/bo_client_demo/run_bo.py status --project-root templates/bo_client_demo
python3 templates/bo_client_demo/run_bo.py suggest --project-root templates/bo_client_demo
python3 templates/bo_client_demo/run_bo.py ingest \
  --project-root templates/bo_client_demo \
  --results-file templates/bo_client_demo/examples/example_results.json
python3 templates/bo_client_demo/run_bo.py demo --project-root templates/bo_client_demo --steps 5
```

### `templates/bo_client` (baseline harness, config-selected backend)

```bash
python3 templates/bo_client/run_bo.py status --project-root templates/bo_client
python3 templates/bo_client/run_bo.py suggest --project-root templates/bo_client
python3 templates/bo_client/run_bo.py ingest \
  --project-root templates/bo_client \
  --results-file templates/bo_client/examples/example_results.json
python3 templates/bo_client/run_bo.py demo --project-root templates/bo_client --steps 5
```

Optional GP backend (after dependencies are installed and `surrogate.type` is
set to `gp` in `templates/bo_client/bo_config.json`):

```bash
python3 templates/bo_client/run_bo.py suggest --project-root templates/bo_client
```

### `templates/bo_client_full` (optional BoTorch GP feature flag)

```bash
python3 templates/bo_client_full/run_bo.py status --project-root templates/bo_client_full
python3 templates/bo_client_full/run_bo.py suggest --project-root templates/bo_client_full
python3 templates/bo_client_full/run_bo.py suggest --project-root templates/bo_client_full --enable-botorch-gp
python3 templates/bo_client_full/run_bo.py ingest \
  --project-root templates/bo_client_full \
  --results-file templates/bo_client_full/examples/example_results.json
python3 templates/bo_client_full/run_bo.py demo --project-root templates/bo_client_full --steps 5
```

Note: If BoTorch is unavailable and the template config allows fallback,
`bo_client_full` falls back to proxy mode and records the reason in
acquisition logs.

## Tiny End-to-End Objective (<1 Minute)

For a dedicated trust-building loop demo (separate from template `demo`), run:

```bash
python3 examples/toy_objectives/03_tiny_quadratic_loop/run_tiny_loop.py --steps 6
```

To regenerate the golden decision-trace sample:

```bash
python3 examples/toy_objectives/03_tiny_quadratic_loop/run_tiny_loop.py \
  --steps 8 \
  --write-acquisition-log docs/examples/decision_trace/golden_acquisition_log.jsonl \
  --normalize-acquisition-timestamps
```

Equivalent one-command helper:

```bash
bash docs/examples/decision_trace/regenerate_golden_log.sh
```

Related artifacts:

- `docs/examples/decision_trace/golden_acquisition_log.jsonl`
- `docs/examples/decision_trace/golden_acquisition_log.md`
- `docs/examples/decision_trace/cli_transcript.md`

## Lifecycle and Ops Commands (All Variants)

The same lifecycle/ops commands are available in each template:

```bash
python3 templates/bo_client_demo/run_bo.py cancel --project-root templates/bo_client_demo --trial-id 3
python3 templates/bo_client_demo/run_bo.py retire --project-root templates/bo_client_demo --trial-id 4
python3 templates/bo_client_demo/run_bo.py retire --project-root templates/bo_client_demo --stale
python3 templates/bo_client_demo/run_bo.py heartbeat --project-root templates/bo_client_demo --trial-id 5 --heartbeat-note "still running"
python3 templates/bo_client_demo/run_bo.py report --project-root templates/bo_client_demo --top-n 5
python3 templates/bo_client_demo/run_bo.py validate --project-root templates/bo_client_demo
python3 templates/bo_client_demo/run_bo.py doctor --project-root templates/bo_client_demo --json
```

Mutating commands (`suggest`, `ingest`, `cancel`, `retire`, `heartbeat`,
`report`) use an exclusive lock with wait+timeout defaults.
Add `--fail-fast` to fail immediately on lock contention.
For interruption recovery/teardown decisions, use `docs/recovery-playbook.md`.

## First Clean-Run Flow (Practical Starting Path)

On a clean template copy (no existing state), the bundled
`example_results.json` matches the deterministic first suggestion for the
default seed.

```bash
python3 templates/bo_client_demo/run_bo.py suggest --project-root templates/bo_client_demo
python3 templates/bo_client_demo/run_bo.py ingest \
  --project-root templates/bo_client_demo \
  --results-file templates/bo_client_demo/examples/example_results.json
python3 templates/bo_client_demo/run_bo.py status --project-root templates/bo_client_demo
```

If you already generated a different pending suggestion, generate a matching
payload instead of reusing `example_results.json`.

To test non-`ok` ingest semantics with the bundled sample payload:

```bash
python3 templates/bo_client_demo/run_bo.py ingest \
  --project-root templates/bo_client_demo \
  --results-file templates/bo_client_demo/examples/example_results_timeout.json
```

## State Files and Resume Behavior

State and logs are configured in each template's `bo_config.json` and default to:

- `state/bo_state.json`: resumable run state
  (`schema_version`, `observations`, `pending`, `next_trial_id`, `best`)
- `state/observations.csv`: flattened observation history written after ingest
- `state/acquisition_log.jsonl`: append-only suggestion decision trace
- `state/event_log.jsonl`: append-only lifecycle/ops trace
- `state/trials/trial_<id>/manifest.json`: per-trial audit manifest
- `state/report.json` and `state/report.md`: explicit report outputs from `report`
- `paths.ingest_schema_file` (default `../_shared/schemas/ingest_payload.schema.json`): payload structure for `ingest`

Resume rules:

1. `suggest` adds a pending trial and increments `next_trial_id`.
2. External evaluation must return the same `trial_id` and exact `params`.
3. `ingest` removes the matching pending trial, appends an observation, updates `best`, and rewrites `observations.csv`.
4. Re-running `ingest` with identical payload is a no-op success; conflicting replay is rejected with mismatch details.
5. If the budget is exhausted, `suggest` exits cleanly with no new pending trial.
6. If `max_pending_age_seconds` is configured/enabled, stale pending trials can
   be auto-retired during `suggest`.

## State File Examples

Reference snapshots (captured from a temp run of
`templates/bo_client_demo`) are checked in under
`docs/examples/state_snapshots/`:

- `docs/examples/state_snapshots/status_empty.json`
- `docs/examples/state_snapshots/suggestion_1.json`
- `docs/examples/state_snapshots/bo_state_after_suggest.json`
- `docs/examples/state_snapshots/acquisition_log_after_suggest.jsonl`
- `docs/examples/state_snapshots/result_1_generated.json`
- `docs/examples/state_snapshots/result_1_timeout_generated.json`
- `docs/examples/state_snapshots/bo_state_after_ingest.json`
- `docs/examples/state_snapshots/bo_state_after_timeout_ingest.json`
- `docs/examples/state_snapshots/observations_after_ingest.csv`
- `docs/examples/state_snapshots/observations_after_timeout_ingest.csv`
- `docs/examples/state_snapshots/status_after_ingest.json`
- `docs/examples/state_snapshots/status_after_timeout_ingest.json`

## Synthetic Helper (Payload Generation Example)

For local testing without an external system, the demo template includes a
helper that converts a suggestion JSON into a valid result payload:

```bash
python3 templates/bo_client_demo/scripts/synthetic_experiment.py \
  docs/examples/state_snapshots/suggestion_1.json \
  /tmp/result.json
```

For a live run, pass the exact suggestion JSON produced by `suggest`
(not full stdout with the trailing `Objective direction: ...` line).
For strict machine-readable `suggest` output, use `--json-only`.

## Test Command (Repo Root)

```bash
python3 -m pytest -q templates
```

## Release Smoke Checks (Automated + Manual)

Canonical automated guardrail:

```bash
python3 scripts/release_smoke.py
```

Manual fallback checklist (run on a temporary copy to avoid mutating tracked
template state):

```bash
TMP_ROOT="$(mktemp -d /tmp/looptimum_release_smoke.XXXXXX)"
cp -R templates "$TMP_ROOT/templates"

python3 "$TMP_ROOT/templates/bo_client_demo/run_bo.py" status --project-root "$TMP_ROOT/templates/bo_client_demo"
python3 "$TMP_ROOT/templates/bo_client_demo/run_bo.py" suggest --project-root "$TMP_ROOT/templates/bo_client_demo"
python3 "$TMP_ROOT/templates/bo_client_demo/run_bo.py" ingest --project-root "$TMP_ROOT/templates/bo_client_demo" --results-file "$TMP_ROOT/templates/bo_client_demo/examples/example_results.json"
python3 "$TMP_ROOT/templates/bo_client_demo/run_bo.py" demo --project-root "$TMP_ROOT/templates/bo_client_demo" --steps 3

python3 "$TMP_ROOT/templates/bo_client/run_bo.py" status --project-root "$TMP_ROOT/templates/bo_client"
python3 "$TMP_ROOT/templates/bo_client/run_bo.py" suggest --project-root "$TMP_ROOT/templates/bo_client"
python3 "$TMP_ROOT/templates/bo_client/run_bo.py" ingest --project-root "$TMP_ROOT/templates/bo_client" --results-file "$TMP_ROOT/templates/bo_client/examples/example_results.json"
python3 "$TMP_ROOT/templates/bo_client/run_bo.py" demo --project-root "$TMP_ROOT/templates/bo_client" --steps 3

python3 "$TMP_ROOT/templates/bo_client_full/run_bo.py" status --project-root "$TMP_ROOT/templates/bo_client_full"
python3 "$TMP_ROOT/templates/bo_client_full/run_bo.py" suggest --project-root "$TMP_ROOT/templates/bo_client_full"
python3 "$TMP_ROOT/templates/bo_client_full/run_bo.py" suggest --project-root "$TMP_ROOT/templates/bo_client_full" --enable-botorch-gp
python3 "$TMP_ROOT/templates/bo_client_full/run_bo.py" ingest --project-root "$TMP_ROOT/templates/bo_client_full" --results-file "$TMP_ROOT/templates/bo_client_full/examples/example_results.json"
python3 "$TMP_ROOT/templates/bo_client_full/run_bo.py" demo --project-root "$TMP_ROOT/templates/bo_client_full" --steps 3

python3 examples/toy_objectives/03_tiny_quadratic_loop/run_tiny_loop.py --steps 4
```

Also run the lifecycle/ops command checklist from the "Lifecycle and Ops
Commands (All Variants)" section for each variant project root.
