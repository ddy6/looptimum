# Ax support and verification

The first table describes contract 1, introduced in v1.0.0 and retained in v1.1.0. It
applies to `bo_client` and `bo_client_full` with `optimizer.backend: "ax"`.
The [installation profile](ax-installation.md) defines the CPU/Python targets.
The default legacy controller and direct BoTorch options retain their existing
behavior. Ax cannot be combined with the full template's direct-GP flag.

The Ax CI lane requires dependencies and prohibits silently skipping its
integration tests. Tests below use real Ax where noted; fault-injection tests
use a deterministic worker to exercise commit boundaries precisely.

| Supported behavior | Verification in this repository |
| --- | --- |
| Bounded float/int, Boolean and string choices; log float | [Real mixed-space integration](../templates/tests/test_ax_integration.py), mixed pipeline example |
| Fixed float/int/single-choice values, numeric categorical choices, log integer, raw parameter aliases | `test_real_ax_fixed_values_numeric_choices_log_integer_and_maximization` in the real integration suite, both templates |
| Primary minimize/maximize; unchanged weighted-sum and weighted-Tchebycheff scalar scores | Real integration primary-direction and imported-scalar tests; [scalar bridge fault tests](../templates/tests/test_ax_recovery.py) preserve full objective vectors and best ranking |
| Bound tightening | Real imported-scalar integration checks tightened bounds before model-guided generation |
| Public `fast` Sobol initialization to CPU BoTorch generation, seeded restart | [Public API probe](../scripts/probe_ax_compatibility.py); real integration asserts `MBM` rather than just trial allocation |
| Complete batches, locked allocation, no partial budget/ID consumption on errors | Real initialization batch test; [allocation recovery suite](../templates/tests/test_ax_recovery.py) tests lock conflicts, commit boundaries and failing workers |
| Out-of-order results, idempotent ingest, timeout/failure/cancel, initialization replacements | Real batch/restart and failed-initialization tests inspect Ax statuses and exclude failed measurements |
| Leases, heartbeat, retirement and late results | Allocation fault tests preserve ingest and heartbeat across repair, stale retirement across generation failure; real rebuild tests preserve pending leases |
| Duplicate rejection, finite-space capacity, repeat-option semantics | Real Boolean exhaustion test; [backend unit tests](../templates/tests/test_optimizer_backend.py) count unique pending/completed capacity and repeat policy; retry exhaustion fault tests |
| Canonical observation import, scoring/provenance, no outstanding work during initial conversion | Real imported-scalar test; backend identity/preflight tests; historical edits rejected by real continuation test |
| Immutable snapshots and strict semantic/version/digest checks | Backend tests and allocation fault tests; real snapshot corruption test proves reads/ingest remain available |
| Recover committed allocation publication exactly once without Ax | Process-exit tests for both templates, every journal publication stage, including interrupted recovery and intervening lifecycle changes |
| Explicit rebuild, new lineage, exact backups, unchanged canonical trials/observations/budget | [Rebuild fault suite](../templates/tests/test_ax_rebuild.py) and real rebuild/resume test for both templates |
| Reset/archive/restore retains optimizer state; portable copies exclude active history | Allocation/rebuild suites and [portable copy tests](../templates/tests/test_portable_copy.py) |
| Read/ingest/lifecycle operations and evaluators run without optimizer imports | Real integration runs terminal commands with `python -S`; [service mutation test](../service/tests/test_mutations.py) actively blocks optimizer imports for reads and leased ingest |
| Full pinned dependency closure, CPU selection, hashed offline install | [Installer boundary tests](../templates/tests/test_ax_install.py), fresh wheelhouse installation + `pip check` + public probe and mixed example in each Ax CI lane |

The [backend comparison](../benchmarks/backend_comparison/gp_fix/readout.md)
adds 200 complete synthetic campaigns across five backends, four workloads
and ten seeds. It is measured evidence for those workloads and the recorded
environment, not a guarantee of performance or identical proposals elsewhere.

## Opt-in contract 2 (v1.1.0)

Select `optimizer.ax.contract_version: 2` in ordinary/full Ax controllers.
[Contract 2](ax-contract2.md) defines the exact subset and migration rules;
these v1.1.0 capabilities preserve contract-1 defaults and the original v1.0.0
release identity.

| Source capability | Verification |
| --- | --- |
| Known/unknown per-metric SEM coverage, weighted score SEMs, strict replay/import and typed CSV2 | [Measurement suite](../templates/tests/test_ax_measurements.py), lean ordinary/full ingest, service and harness tests |
| Typed heterogeneous choices, finite conditional trees, exact raw linear/fixed terms, eligible forbidden-choice pruning, bounded remaining rejection and finite feasible capacity | [Exact pruning tests](../templates/tests/test_ax_forbidden_generation.py), [search-space suite](../templates/tests/test_ax_search_spaces.py), real ordinary/full integer-linear modeled generation and seeded restore for seeds 17 and 41 |
| Measured constraints, genuine vector acquisition, mixed directions, no-feasible-yet operation and observed feasible hypervolume | [Outcome suite](../templates/tests/test_ax_outcomes.py), public serialized vector optimization config and MBM inspection, manual 2D/3D volume examples |
| State `0.5.x` / format 2, unchanged real pre-change v1 fingerprints, explicit upgrade/semantic rebuild, exact backups/new lineage | [Rebuild suite](../templates/tests/test_ax_rebuild.py), real upgrade, baseline-code continuation/rollback proof |
| Complete-batch rejection, worker timeout/malformed response, process exits, lost snapshots, archive/restore and canonical result delivery | [Expanded recovery suite](../templates/tests/test_ax_recovery.py), reused transaction and fault hooks for both formats |
| Synthetic paired evidence with fixed calls, explicit failures and restore receipts | [Repaired-source full matrix](../benchmarks/ax_capabilities/repaired/readout.md): 40/40 campaigns, 960/960 new calls, independent metric/count and 25-checkpoint restore audits; original failed evidence retained separately |

The four required Ax OS/Python CI lanes include all three new capability suites
with missing-dependency skip protection. Local passes do not claim those remote
lanes passed on an uncommitted revision.

Eligible contract-2 forbidden finite choices are pruned exactly from the Ax
generation space; remaining rules use bounded rejection. Before that repair,
typed-space seed 41 exhausted eight attempts on forbidden arms without allocating
its next trial; the approved time extension made no additional evaluator calls.
The [original readout](../benchmarks/ax_capabilities/readout.md) retains that
incomplete case. The [repaired-source matrix](../benchmarks/ax_capabilities/repaired/readout.md)
completed all 40 campaigns, including seed 41, with zero compiled forbidden-branch
rejections. Remaining post-filtered rules can still reach the attempt limit
without a feasible proposal.

## Explicit limits

The first two limits below apply to released contract 1. Contract 2 extends only
the subset documented above; custom acquisition, fully Bayesian, GPU and
external/distributed storage remain outside both contracts.

- Conditional parameters, heterogeneous categorical types, linear inequalities,
  forbidden combinations and lexicographic objectives are rejected before Ax
  allocation. Backend capability tests exercise these rejections. Bound
  tightening is the supported constraint mechanism.
- Noise/standard-error inputs, measured outcome constraints, true multi-objective
  or Pareto acquisition, custom acquisition functions, fully Bayesian methods,
  CUDA/MPS execution and distributed Ax storage are outside this surface.
  Observed Pareto reporting does not select a Pareto acquisition strategy.
- `allow_completed_repeats` permits a completed parameterization to be accepted;
  it does not force Ax's selected generation strategy to generate repeats.
- Exact restoration requires canonical state, optimizer files, original
  configuration and matching environment. Rebuild has an explicit new lineage.
  Cross-platform or cross-version numerical identity is not promised.
- Atomic replacement protects the documented controller process-exit boundaries.
  No power-loss durability or transaction across every lifecycle operation is
  claimed. Persistence does not explicitly sync files/directories to disk.

The [v1 stability policy](stability-guarantees.md) defines the compatibility
promise and [migration guide](migration-v1.md) defines upgrade/rollback.
The [release procedure](release-guide.md) requires successful CI on the exact
release commit before tagging; this matrix does not itself publish a release.
