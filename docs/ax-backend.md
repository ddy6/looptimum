# Ax backend

The native Ax backend is under development for the planned Looptimum `v1.0.0`
release. It uses Ax 1.3.1 and its compatible BoTorch stack to generate trials
through the existing `suggest -> evaluate -> ingest` workflow. Default proxy
behavior and the existing direct BoTorch options remain available.

## Install and select

From a repository checkout, install optional controller dependencies:

```bash
python -m pip install '.[ax]'
```

This installs dependencies for repository templates; it does not install a
new public Python controller API. A portable controller can instead use its
`requirements-ax.txt`. Only the controller environment needs Ax. Evaluators
can continue running their existing scripts and returning ordinary results.

In `bo_client` or `bo_client_full`, add this object to `bo_config.json`:

```json
{
  "optimizer": {
    "backend": "ax",
    "ax": {
      "method": "fast",
      "initialization_budget": 6,
      "min_observed_initialization_trials": 6,
      "initialize_with_center": false,
      "generation_timeout_seconds": 120,
      "max_generation_attempts": 8,
      "allow_completed_repeats": false
    }
  }
}
```

Omitting `optimizer`, or selecting `backend: "legacy"`, preserves legacy
selection. Ax cannot be combined with `enable_botorch_gp`. The demo template
remains lightweight and rejects explicit Ax selection.

With Ax selected, legacy `initial_random_trials`, `candidate_pool_size`,
`surrogate`, and `acquisition` settings are inactive. Ax's public `fast`
generation strategy owns initialization and model-guided selection. The
minimum completed initialization count defaults to the initialization budget.
Initialization failures do not become successful measurements. Ax can replace
failed or abandoned initialization trials with additional Sobol trials; these
attempts still consume Looptimum's evaluation budget. If Ax cannot
advance until results arrive, generation fails explicitly without allocating
part of a requested batch. Try a smaller batch or complete outstanding work.

Generation happens in an isolated CPU subprocess with a timeout. Ax logging
does not appear in the public JSON payload. Backend errors do not silently
switch the campaign to proxy generation.

## Supported development surface

- Flat float/int/bool parameters and homogeneous categorical choices.
- Linear/log numeric scales and fixed bounds, subject to the selected Ax
  release's supported parameter configurations.
- Primary objectives and the exact scalar scores produced by existing
  weighted-sum or weighted-Tchebycheff policies.
- Bound tightening; raw parameter types and units remain evaluator-facing.
- Locked complete batches, ordinary worker leases, out-of-order terminal
  results, failures, and cancellations.
- Existing canonical observation import; first-time conversion of an existing
  campaign requires no outstanding pending work.

Conditional parameters, mixed-type categorical choices, linear inequality
constraints, forbidden combinations, lexicographic objectives, known
measurement errors, measured outcome constraints, and true Pareto acquisition
are not supported yet. Unsupported selections fail before trial allocation.
Existing observed Pareto reporting does not imply Pareto-directed acquisition.

Currently pending parameterizations cannot be duplicated. Completed
parameterizations are also excluded unless `allow_completed_repeats` is true.
Finite spaces can therefore exhaust. Retries are bounded; rejected Ax arms
do not consume public trial IDs or evaluation budget. Canonical `best` still
ranks successful observed results through Looptimum's objective helpers.
Reporting penalties for failed trials are never used as training data.
For spaces consisting entirely of choices, integers, and fixed numeric
values, the adapter checks remaining unique capacity before starting Ax.
A batch larger than that capacity fails without fitting a model or allocating
part of the batch. The completed-repeat option permits reuse; it does not
guarantee that Ax's selected method will propose a repeat.

## State and recovery boundaries

Ax campaigns persist state series `0.4.x`; legacy campaigns remain `0.3.x`.
Older controllers reject the Ax series rather than accidentally generate a
proxy suggestion. Evaluator suggestion/result/status payloads retain the
existing `0.3.x` surface. Status additionally identifies the internal
`state_schema_version` and optimizer snapshot pointer for an Ax campaign.
These state versions are independent of the package's planned `1.0.0` tag.

Immutable JSON snapshots live in `state/optimizer/ax/snapshots/`. The pointer
in `bo_state.json` selects the committed snapshot. New snapshots are installed
before pending work and the pointer are saved together. A failed canonical
write may leave an unreferenced snapshot, but it does not commit a partial
allocation. Back up canonical state and the optimizer directory together.
Reset archives include optimizer files; fresh portable copies exclude them.

Ax allocations also stage a checksummed journal at
`state/optimizer/ax/allocation.json`. Canonical state replacement is the
commit point; manifests and allocation decision/event records are published
afterward. Allocation log records carry an `allocation_id`. Publication
preserves existing log contents and adds the batch through atomic replacement
so a process exit cannot leave half of an allocation-owned JSONL record.
The journal is removed after publication finishes.

If `suggest` exits before returning its payload, inspect `status` first.
Committed pending trials retain their IDs, parameter values, and lease
tokens; retrieve them from canonical `bo_state.json` rather than allocating
replacement work. `status` reports `allocation_recovery` when a journal is
present, and `validate`/`health` flag unfinished publication. Reads do not
repair files. Under the ordinary campaign lock, run:

```bash
python run_bo.py recover-allocation
python run_bo.py validate --strict
```

`recover-allocation` needs no Ax/Torch installation and does not load the
optimizer snapshot. A preparation that never committed is discarded without
advancing trial IDs. A committed allocation has its manifests and log records
repaired exactly once. Results, cancellations, and heartbeats delivered before
repair are preserved by rebuilding manifests from current canonical records.
The command does not generate trials or change canonical state. The next
`suggest` also completes this recovery before attempting generation.
Corrupt/conflicting journals stop recovery and generation explicitly;
canonical reads and result/lifecycle operations remain available. Preserve
the files and restore a matching backup rather than deleting the journal.
Recovery also requires the original objective configuration so manifests
cannot silently be reconstructed with different scoring semantics.
This command repairs allocation publication; it does not rebuild lost Ax
optimizer history or repair arbitrary pre-journal artifacts.

With Ax selected, automatic stale retirement commits as a separate lifecycle
change before generation. A subsequent Ax error leaves those trials retired
without allocating new trials.

Ingestion, cancellation, retirement, heartbeat, reads, and canonical import
do not require Ax imports. Ax's snapshot can lag these operations; the next
generation reconciles their canonical records. An identical ingest remains
a no-op. Previously projected terminal measurements cannot be silently edited.

Generation rejects missing/corrupt snapshots, changed semantic configuration,
and dependency-version mismatches. Restore the recorded configuration,
snapshot, and environment. Do not delete optimizer metadata to restart a
campaign. A new campaign warm-started from exported observations is a new
optimization history, not exact recovery of the previous generator.

### Rebuild a lost optimizer snapshot

If the matching snapshot/environment cannot be restored, ordinary/full
controllers provide an explicit rebuild:

```bash
python run_bo.py rebuild-optimizer --reason "Original optimizer snapshot unavailable"
python run_bo.py validate --strict
```

This requires the optional Ax stack. It creates a fresh Ax client from
canonical observations and pending trials, with a new optimizer lineage and
generation counter zero. It generates **no suggestions** and does not change
trial IDs, pending parameters or leases, observations, best-so-far, evaluation
budget usage, manifests, or the observations CSV. Existing workers can still
deliver their results. Subsequent `suggest` uses this new lineage; its next
point may differ from what the lost optimizer would have chosen.

Use the original parameter/objective/constraint configuration. New state
metadata also records its semantic fingerprint outside the snapshot, so a
lost snapshot does not bypass a known configuration mismatch. A rebuild can
adopt the currently installed compatible dependency stack explicitly, with
old/new versions recorded when available. It cannot bypass the pinned Ax
version or unsupported-feature checks. Older development state may lack a
fingerprint outside its lost snapshot. In that case original semantics cannot
be verified; the receipt records `configuration_verified: false`. Restore
and review the original configuration before using this route. Invalid
canonical records, out-of-bounds history, and known semantic changes are
rejected; rebuild does not repair or reweight observations.

Before the canonical pointer changes, a unique directory under
`state/optimizer/ax/rebuilds/<rebuild_id>/` preserves:

- `state-before.json`: exact pre-rebuild canonical state bytes;
- `snapshot-before.bin`: exact old snapshot bytes when available, including
  corrupt or non-UTF-8 contents; the original snapshot is also left intact;
- `rebuild.json`: reason, source hashes, old/new snapshot references, lineage,
  configuration verification, dependency versions, and record counts.

The new immutable snapshot also records rebuild provenance. A single
canonical state replacement commits its pointer and pending audit event.
The `optimizer_rebuilt` event is published once, then the pending marker is
cleared. Status exposes `optimizer_recovery` while publication is unfinished;
`validate`/`health` flag it without repairing files. Rerunning
`rebuild-optimizer --reason "Finish committed recovery"` completes the
already committed audit instead of creating another lineage, and requires
no Ax imports. The next `suggest` also finishes that audit before generation.
An ordinary successful rebuild command issued again starts another lineage.

Finish any `recover-allocation` work before rebuilding. A failure before
canonical commit leaves the previous campaign selected; a failure afterward
leaves the rebuilt campaign selected and its audit repairable. Preparations
may leave unreferenced snapshots/backup directories; they are not proof of
commit. Keep backups with the canonical state and optimizer directory.
Reset/restore retains them and portable copies exclude them. Exact recovery
still means restoring the matching original state and snapshot, not rebuilding.

Use `doctor --json` for dependency versions and effective backend settings;
dependency presence is a lightweight diagnostic, not proof of binary import
compatibility. `validate` checks snapshot presence and digest without loading
Ax. Numerical continuation is tested within a fixed stack; identical
suggestions across platforms or dependency versions are not guaranteed.

Canonical-state allocation, snapshot consistency, and journaled allocation
publication cover controller process exits. This is not a transaction across
every lifecycle command or a promise of power-loss durability: persistence
uses rename without explicit file/directory syncing. Broader
lifecycle/constraint coverage, performance comparisons, platform CI evidence,
and the final compatibility audit remain
release gates. Existing legacy-backend allocation behavior is unchanged.

## Verify an environment

The [native quadratic example](../examples/ax_quadratic/README.md) runs a
complete Looptimum campaign in a fresh portable directory.
The [mixed pipeline example](../examples/ax_pipeline_tuning/README.md) adds
integer, Boolean, categorical, and logarithmic controls around an external
synthetic evaluator. The separate [backend comparison protocol](../benchmarks/backend_comparison/README.md)
declares fixed-budget quality and resource measurements; it does not change
the existing published benchmark evidence.
The first reference [readout](../benchmarks/backend_comparison/readout.md)
retains a direct-GP numerical fit failure; the full comparison acceptance
gate remains unmet. Completed Ax results and resource measurements are
reported with their synthetic-workload and environment limits.

```bash
python scripts/probe_ax_compatibility.py --output /tmp/ax-compatibility.json
LOOPTIMUM_REQUIRE_AX_TESTS=1 python -m pytest -q templates/tests/test_ax_integration.py
```

The probe reaches real BoTorch generation, compares a seeded resumed run,
and exercises public JSON persistence and terminal transitions. It records
dependency versions and timing. CI runs the optional Ax lane separately on
Python 3.11 and 3.12; the default suite does not install Ax or Torch.
