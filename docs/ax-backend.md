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
Initialization failures do not become successful measurements. If Ax cannot
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

Ingestion, cancellation, retirement, heartbeat, reads, and canonical import
do not require Ax imports. Ax's snapshot can lag these operations; the next
generation reconciles their canonical records. An identical ingest remains
a no-op. Previously projected terminal measurements cannot be silently edited.

Generation rejects missing/corrupt snapshots, changed semantic configuration,
and dependency-version mismatches. Restore the recorded configuration,
snapshot, and environment. Do not delete optimizer metadata to restart a
campaign. A new campaign warm-started from exported observations is a new
optimization history, not exact recovery of the previous generator.

Use `doctor --json` for dependency versions and effective backend settings;
dependency presence is a lightweight diagnostic, not proof of binary import
compatibility. `validate` checks snapshot presence and digest without loading
Ax. Numerical continuation is tested within a fixed stack; identical
suggestions across platforms or dependency versions are not guaranteed.

This development slice establishes canonical-state allocation and snapshot
consistency. Hardening recovery of prepared manifests/decision logs after an
abrupt process exit, broader lifecycle/constraint coverage, performance
comparisons, and the final compatibility audit remain release gates. The
rename-based persistence helper does not promise power-loss durability.

## Verify an environment

The [native quadratic example](../examples/ax_quadratic/README.md) runs a
complete Looptimum campaign in a fresh portable directory.

```bash
python scripts/probe_ax_compatibility.py --output /tmp/ax-compatibility.json
LOOPTIMUM_REQUIRE_AX_TESTS=1 python -m pytest -q templates/tests/test_ax_integration.py
```

The probe reaches real BoTorch generation, compares a seeded resumed run,
and exercises public JSON persistence and terminal transitions. It records
dependency versions and timing. CI runs the optional Ax lane separately on
Python 3.11 and 3.12; the default suite does not install Ax or Torch.
