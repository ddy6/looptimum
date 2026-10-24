# Recovery Playbook

This is the operator runbook for interrupted or degraded
`suggest -> evaluate -> ingest` workflows.
Use this page for "what to do now" actions.
Normative contract semantics remain in `docs/operational-semantics.md`.

## Scope

This playbook covers:

- interrupted consumers / controller restarts
- ingest failures and replay handling
- stale pending trial recovery
- reset archive inventory / restore / prune handling
- canceled/killed/timeout operational handling in local and CI runs

## Fast Triage

1. Stop parallel writers to the same `state/` path.
2. Run:
   `python3 templates/bo_client/run_bo.py status --project-root <template_dir>`
3. If state integrity is in question, run:
   `python3 templates/bo_client/run_bo.py validate --project-root <template_dir>`
4. If runtime artifacts were reset or look corrupted, inventory archives:
   `python3 templates/bo_client/run_bo.py list-archives --project-root <template_dir>`
5. Then follow the decision tree below.

## Compact Decision Tree

```text
Start
  |
  v
Did `ingest` return non-zero?
  |-- no --> continue normal loop (`suggest` -> evaluate -> `ingest`)
  |
  |-- yes
        |
        v
    Is error "conflicting duplicate ingest"?
      |-- yes --> do NOT overwrite state; compare payload vs prior trial contract; fix evaluator replay source; retry once with corrected payload.
      |
      |-- no
            |
            v
        Is trial still pending?
          |-- yes --> retry `ingest` with same payload (idempotent path).
          |
          |-- no --> run `status`; if already observed, treat as duplicate replay and stop retrying.

After any failed attempt:
  |
  v
Are there stale pending trials?
  |-- yes --> `retire --stale` (or `suggest` with auto-stale enabled), then continue.
  |-- no  --> continue.
```

## Normative Runbooks

### Ax allocation interrupted before a suggestion was returned

For an Ax campaign, start with `status`. Pending entries in canonical
`state/bo_state.json` are committed work even if stdout was lost. Preserve
their IDs, parameters, and lease tokens when dispatching or redispatching
work; coordinate with evaluators to avoid executing it twice.

If status includes `allocation_recovery`, run the ordinary/full controller's
`recover-allocation` command under the campaign's configured project root,
then `validate --strict`. This requires no Ax installation. It discards an
uncommitted preparation or finishes committed manifests and allocation logs
without advancing counters, generating new trials, or reverting later
results/heartbeats. The next `suggest` also performs this repair, but still
requests additional work; use explicit recovery when no new allocation is
wanted. See [Ax recovery boundaries](./ax-backend.md#state-and-recovery-boundaries).

A corrupt journal or incompatible canonical history requires a matching
backup and diagnosis. Preserve canonical state and the entire optimizer
directory together. Allocation recovery does not recreate a missing Ax
snapshot or promise exact continuation from observations alone.

### Ax optimizer snapshot cannot be restored

First preserve canonical state and all optimizer files. Restore the original
configuration, resolve pending allocation publication with
`recover-allocation`, and install the compatible Ax stack. Then run the
ordinary/full controller's explicit transition:

```bash
python run_bo.py rebuild-optimizer --reason "Original snapshot could not be restored"
python run_bo.py validate --strict
```

The rebuild preserves canonical trial records, leases, and best-so-far,
creates no evaluations, and starts a new optimizer lineage. It retains exact
pre-rebuild state and available snapshot bytes under the optimizer directory.
Future suggestions can differ. See the [rebuild contract and backup
inventory](./ax-backend.md#rebuild-a-lost-optimizer-snapshot), including older
state whose configuration cannot be independently verified.

If status reports unfinished `optimizer_recovery`, rerun the rebuild command
to finish the committed audit without generating work or rebuilding again.
That completion requires no optimizer imports. A rebuild error is not
permission to discard pending workers or alter trial IDs.

### 1) `ingest` failed

Run:

```bash
python3 templates/bo_client/run_bo.py ingest --project-root <template_dir> --results-file <payload.json>
```

If exit code is non-zero:

1. Run `status`.
2. If trial is still pending, retry **once** with the same payload.
3. If error is `conflicting duplicate ingest`, treat as replay mismatch:
   - preserve artifacts/logs,
   - do not mutate payload blindly,
   - regenerate payload from the exact suggestion contract and retry.
4. If still failing, stop and escalate with `state/bo_state.json`,
   `state/event_log.jsonl`, and the payload file attached.

### 2) Pending stale recovery

Preferred explicit command:

```bash
python3 templates/bo_client/run_bo.py retire --project-root <template_dir> --stale --max-age-seconds <seconds>
```

Alternative: use configured `max_pending_age_seconds` and call `suggest` to
trigger automatic stale retirement.

Expected behavior:

- stale trials become terminal `killed` observations with terminal reason
  (`retired_stale` or `retired_stale_auto`)
- state resumes with clean pending set for subsequent suggestions

### 3) Canceled / killed / timeout handling

Operator policy:

1. `cancel` for explicit operator abort.
2. `retire` / `retire --stale` for non-responsive pending work.
3. `timeout` status in ingest payload for evaluator runtime expiration.

Required follow-up:

- generate/refresh `report` after meaningful failure bursts:
  `python3 templates/bo_client/run_bo.py report --project-root <template_dir>`
- inspect `counts.observations_by_status`, `terminal_trials`, and manifests.

### 4) CI-local exit code conventions (normative)

- Exit code `0`: command succeeded (including duplicate no-op ingest).
- Non-zero: treat as operational failure requiring branch action.

Recommended CI actions on non-zero:

1. upload `state/` artifacts (`bo_state.json`, `event_log.jsonl`,
   `trials/`, `report.json` if present),
2. stop further mutating commands in that job,
3. open incident/issue with command stderr + attached artifacts.

### 5) Reset archive inventory and restore

Inspect available runtime checkpoints:

```bash
python3 templates/bo_client/run_bo.py list-archives --project-root <template_dir>
```

Restore a specific archive:

```bash
python3 templates/bo_client/run_bo.py restore \
  --project-root <template_dir> \
  --archive-id <reset-id> \
  --yes
```

Use restore when:

- runtime state was accidentally reset
- runtime artifacts were corrupted or partially deleted
- you need to roll back to a known archived checkpoint before resuming

Restore guarantees:

- archive integrity is checked before mutation
- live lock file is not restored
- runtime-artifact overwrite is all-or-nothing with rollback on failure

### 6) Archive retention and cleanup

Preferred command:

```bash
python3 templates/bo_client/run_bo.py prune-archives \
  --project-root <template_dir> \
  --keep-last <N> \
  --older-than-seconds <seconds> \
  --yes
```

Retention rules:

- `--keep-last N` always protects the newest `N` archives
- `--older-than-seconds` only applies to archives with known manifest
  timestamps
- legacy manifest-less archives are not pruned by age alone

Use `prune-archives` instead of manual filesystem deletion so retention actions
are logged and validated under the normal mutation lock.

Governance follow-up:

- use `health --strict` to fail fast on current governance warnings/violations
- use `metrics` to inspect current archive/log footprint and pending-age totals
- inspect `state/event_log.jsonl` for `governance_override_used` and
  `governance_violations_detected` before deciding whether to prune, restore,
  or accept an operator override as intentional

## Traceability Checklist

After recovery, verify:

1. `state/trials/trial_<id>/manifest.json` contains:
   - `status`, `terminal_reason`, `suggested_at`
   - terminal `completed_at`
   - `objective_vector` and `scalarized_objective` when multi-objective is enabled
   - `penalty_objective` for failed/killed/timeout records
   - `artifact_path` (string when produced, else null)
2. `state/report.json` includes:
   - `objective_config`
   - `terminal_trials`
   - enriched `objective_trace`
   - `pareto_front` when multiple objectives are configured
3. `validate` returns zero (or zero warnings if non-strict policy accepted).
