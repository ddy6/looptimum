# Upgrade to v1.0.0

v1.0.0 keeps the existing proxy/direct-BoTorch defaults and evaluator contract,
and adds opt-in native Ax in `bo_client` and `bo_client_full`. Package version
`1.0.0` does not imply state or payload version `1.0.0`. Read the
[stability policy](stability-guarantees.md) before changing a live campaign.

## Before replacing a controller

1. Stop suggestion generation and arrange a quiet backup window. Evaluators
   may keep running, but serialize any result/lifecycle writes during backup.
2. Preserve the entire campaign directory, controller/vendor code, parameter
   space, objective schema, constraints and configuration. Include canonical
   state, logs, trial manifests, archives and `state/optimizer/` when present.
3. Preserve the interpreter/dependency receipt or wheelhouse for an Ax campaign.
   Record pending IDs, parameters and lease tokens. Never allocate replacement
   work merely because a controller command stopped before returning JSON.
4. Validate the backup and record `status`/`doctor --json` before changing files.
   An archive is not a complete configuration/environment backup.

Run only one controller/writer per campaign, including during a deployment.
Use a restored copy for upgrade checks before switching the live controller.

## Legacy campaigns from v0.4.0 and earlier

Omit `optimizer`, or select `{"backend": "legacy"}`, to retain legacy behavior.
No Ax/Torch installation is needed for proxy workflows. Existing direct GP
options continue to require their optional numerical stack.

- Existing `0.3.x` state loads without a forced version rewrite. Pending work,
  IDs, observations, budgets, leases and evaluator result formats remain intact.
- Missing-version or `0.2.x` legacy state upgrades in memory to `0.3.0`, warns,
  and persists the upgrade only on the next mutating command.
- Run `status`, `doctor --json` and `validate --strict` against the copied
  campaign. Investigate warnings before resuming suggestions.
- Deliver existing results through the normal `ingest` command with the
  original lease token when required. Identical replay remains a no-op;
  conflicting replay remains an error.

The deprecated `failure_reason` input remains accepted throughout v1.x;
prefer `terminal_reason`. Its earlier removal warning was stale and is corrected
in this release. The `success` status alias also remains accepted.

## Selecting Ax for an existing legacy campaign

1. Finish or explicitly cancel/retire all pending work. Initial conversion to
   Ax rejects a campaign with outstanding pending trials.
2. Review the [supported matrix](ax-support-matrix.md). Conditional parameters,
   heterogeneous choices, forbidden/linear constraints and lexicographic
   objectives cannot be carried into this Ax surface. Do not silently remove
   a constraint or change scoring on an existing history to make it fit.
3. Install the [tested CPU profile](ax-installation.md), preferably from a
   verified matching-target wheelhouse. Run the public model/restart probe.
4. Add the [Ax optimizer configuration](ax-backend.md#install-and-select),
   retaining parameter bounds, objective semantics and seed. Disable the
   full template's direct-GP flag if it was enabled.
5. Generate the next suggestion under the normal campaign lock. Successful
   allocation commits explicitly marked canonical state `0.4.0` and an Ax
   snapshot. Existing terminal history is reconciled through its canonical
   scalar scores; failure penalties are not training measurements.
6. Back up the resulting state and optimizer directory together. External
   evaluators still receive `0.3.0` payloads with raw parameters and do not
   need Ax dependencies.

Alternatively, create a fresh campaign and import exported observations. That
is a warm start with new optimization history, not exact generator continuation.

## Existing native Ax development campaigns

Keep the matching `0.4.x` state, format-1 snapshot, configuration and six
recorded numerical package versions. No package-driven state renumbering is
needed. Run `status`, `doctor --json` and `validate --strict` before generation.
The installation guide's complete dependency receipt supplements the six-version
generation guard; it does not replace it.

If publication was interrupted, inspect status and run `recover-allocation`
before allocating more work. This repair does not need the optimizer stack.
If the snapshot/environment cannot be restored, use the explicit
[rebuild procedure](ax-backend.md#rebuild-a-lost-optimizer-snapshot) after
preserving backups. Rebuild requires the original semantic configuration,
preserves canonical pending work and results, and creates a new lineage.
It does not recover the lost generator's exact next proposal.

## Rollback

| Campaign | Rollback boundary |
| --- | --- |
| Legacy state `0.3.x` | Restore the reviewed older controller/environment with the unchanged legacy configuration. The retained v0.4.0 state reader is tested against this series. Full behavior across arbitrary older releases is not promised. |
| State upgraded from missing/`0.2.x` | Restore the complete pre-upgrade backup when the older controller needs the original representation. |
| Ax state `0.4.x` | Keep a compatible native Ax controller and matching environment, or restore the complete pre-Ax backup. Released v0.4.0 rejects this state. |
| Lost Ax snapshot/environment | Restore a matching backup or explicitly rebuild on the supported native Ax controller; never relabel the state or delete optimizer metadata. |

Restoring a pre-Ax backup discards later Ax allocations/results from that active
history. Reconcile any still-running workers and preserve later results before
switching. Observation export/import into a fresh legacy campaign is a separate
warm start, not rollback with preserved trial IDs, leases or generation state.

Preview service/dashboard/auth/coordination deployments retain preview scope.
Their metadata changes to `1.0.0-preview`; this release does not change their
registry schema or make their APIs part of the stable template contract.
