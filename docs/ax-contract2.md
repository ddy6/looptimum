# Ax adapter contract 2 (v1.1.0)

Looptimum v1.1.0 adds an explicit opt-in for ordinary/full Ax controllers.
Dependency pins, legacy defaults and Ax contract 1 retain their existing
identities. Package, campaign state, evaluator payload and optimizer versions
remain separate; publication is identified by the GitHub release/tag.
Install the same [pinned CPU profile](ax-installation.md).

```json
{
  "optimizer": {
    "backend": "ax",
    "ax": {"contract_version": 2, "acquisition": "scalar", "initialization_budget": 6}
  }
}
```

`contract_version` defaults to `1`; `acquisition` defaults to `scalar`. New
fields require contract 2 and are rejected on legacy, direct-GP and demo paths.
The opt-in is Looptimum's adapter contract, independent of the Ax package version.

## Measurements and standard errors

Declare extra measured metrics separately from objectives in `objective_schema.json`:

```json
{
  "primary_objective": {"name": "loss", "direction": "minimize"},
  "measurement_metrics": ["resource"],
  "outcome_constraints": [{"metric": "resource", "op": "<=", "bound": 0.7}]
}
```

A successful result supplies every configured objective and declared measurement:

```json
{
  "schema_version": "0.4.0",
  "trial_id": 1,
  "params": {"x": 0.3},
  "status": "ok",
  "objectives": {"loss": 0.2},
  "objective_sems": {"loss": 0.03},
  "measurements": {"resource": 0.6},
  "measurement_sems": {"resource": 0}
}
```

SEMs are standard errors of the reported estimates. Values must be finite,
nonnegative numbers; Boolean/string/null/NaN/infinity values are rejected. Zero
is known error. Missing map entries mean unknown error; absent and empty maps
have the same canonical meaning. Unknown names are rejected. Non-`ok` results
carry null objectives and no measured values or SEMs; reporting penalties never
become model data. The existing evaluator harness forwards complete `objectives`
maps and these named fields from callback dictionaries.

For **each modeled metric**, all successful observations in a campaign must
have known SEMs, or all must have unknown SEMs. Different metrics may choose
different modes. The first successful observation establishes coverage; failures
do not. Ingest/import checks the entire proposed history, including out-of-order
results and batches, before consuming pending work. Missing errors are never
imputed and known errors are never discarded. A coverage change requires complete
source measurements and an explicit validated rebuild or a new campaign.

Primary-only scalar acquisition uses the primary SEM. Weighted-sum and
weighted-Tchebycheff acquisition use evaluator-supplied `scalarized_sem`; supplying
component SEMs in those modes requires that score SEM too. The adapter does not
derive score errors using independence or covariance assumptions. Primary-only
and Pareto acquisition reject `scalarized_sem`. Unmodeled secondary objectives
and extra measurements remain validated and preserved without becoming model
noise inputs. A terminal replay that changes any SEM is a conflict; an identical
replay preserves canonical state.

CSV export from format-2 campaigns declares `ax_csv_version=2` and stores the
whole typed parameter dictionary in `ax_params_json`. This preserves `1`, `1.0`,
`"1"`, empty strings and omitted inactive fields. Measurement maps use
`ax_objective_sems_json`, `ax_measurements_json`, `ax_measurement_sems_json`;
the score SEM uses `ax_scalarized_sem`. Mixing typed JSON parameters with populated
legacy `param_*` columns is rejected. Unambiguous legacy CSV and compatible
`0.3.x` JSON payloads can still be read where all required measurements exist.
JSONL, manifests, reports, tracker exports, service JSON and archives preserve
the same fields. These operations do not require importing Ax/Torch.

Imported points must satisfy the campaign's tightened bounds, linear inequalities
and forbidden combinations. Strict import rejects the entire batch before writing
campaign history; permissive import reports infeasible rows and allocates local
trial IDs only to accepted rows.

## Exact parameter subset

Contract 2 preserves arbitrary evaluator-facing parameter names behind safe
internal aliases and distinguishes heterogeneous categorical values by JSON type.
Finite conditional **trees** are supported: each dependent has one controlling
parent value, whose domain is Boolean, categorical or a bounded linear integer
range of at most 256 values. Nested fixed leaves are allowed; inactive fields
and the internal root never appear in public parameter dictionaries.
Multiparent conjunctions, shared multiple-parent-value branches, DAGs and float
controllers are rejected. Ax lexicographic acquisition remains unsupported.

Raw linear inequalities support unconditional numeric parameters with linear
scales, including integer terms and fixed-value contributions. Rules involving
nonfixed log-scale terms, conditional/inactive terms or enumerated tree
controllers cannot be translated exactly and are rejected. Canonical bound
tightening and forbidden equality combinations use the same raw typed rules as
other controllers. Ax proposals are checked against those rules; rejected arms
are abandoned inside the bounded worker. No clipping or repair is performed.

A public batch is allocated only after every candidate passes. Failure or retry
exhaustion consumes no public trial IDs or evaluation slots. Finite feasible
capacity accounts for active fields, constraints, pending work and distinct
completed points. `allow_completed_repeats` permits completed repeats without
forcing the strategy to propose them; pending duplicates are always excluded.

Eligible forbidden finite choices are removed from the Ax generation space when
the choice's activation ancestors prove every other term of the forbidden rule.
For example, if `flag` is active only under integer `kind=1`, forbidding
`{kind: 1, flag: false}` removes `false` from that branch. This preserves the
public parameter codec, typed token positions and every feasible point. Values
that own dependent children, exclusions that empty a choice domain, range values,
and rules requiring sibling conditions retain bounded post-filtering. Every
decoded proposal still passes the canonical feasibility checks.

The compiled generation space is included in the configuration fingerprint and
snapshot. Existing affected campaigns require an explicit validated rebuild with
no outstanding work, or a new campaign; their old snapshots are not silently
continued under the changed generation space.

Remaining forbidden rules use bounded post-filtering. Rejected arms supply no
objective measurements, so Ax can keep proposing a forbidden branch even when
feasible points remain. In that case generation stops at the configured attempt
limit and publishes no partial batch. The [original capability run](../benchmarks/ax_capabilities/readout.md)
records this limit before eligible finite-choice pruning was implemented;
extra campaign time alone did not resolve it. After that repair, the
[separate full matrix](../benchmarks/ax_capabilities/repaired/readout.md) completed
all 40 campaigns and 960 evaluations, including the originally blocked typed-space
case. Remaining post-filtered rules still have the bounded-generation limit.

## Measured feasibility and Pareto acquisition

Outcome constraints use declared extra metrics, finite absolute bounds and
inclusive `<=`/`>=` comparisons on observed raw values. Objective names cannot
also be outcome constraints: Ax interprets those bounds as objective thresholds.
Contradictory same-metric bounds fail validation. A successful infeasible trial
remains completed model data. Missing/failed outcomes are unknown, never feasible.

Set `optimizer.ax.acquisition` to `pareto`, declare at least two objectives and
provide an explicit `pareto_reference` value for every objective in original
units. For example, add:

```json
{
  "secondary_objectives": [{"name": "gain", "direction": "maximize"}],
  "pareto_reference": {"loss": 1, "gain": -0.1}
}
```

The worker configures Ax's vector objective with each direction and separate
reference thresholds. It does not optimize a scalar score in Pareto mode.
Scalar `best` and existing observed `pareto_front` retain their old ranking
meaning. New `best_feasible`, `outcome_constraint_status`,
`outcome_feasibility_counts`, `feasible_pareto_front` and `feasible_hypervolume`
describe observed feasibility. Scalar summaries are labeled `summary_only`
when acquisition is Pareto. No feasible observation means `best_feasible: null`.

Hypervolume uses reference-anchored boxes after transforming directions into one
maximize orientation. Only feasible observed nondominated points that dominate
the reference contribute; worse-than-reference regions contribute zero, never
an absolute area. A reference may also be supplied in scalar mode solely for
observed reporting. It is distinct from a scalarization `reference_point`.

## State, rebuild and rollback

| Campaign | State | Optimizer/snapshot format | Evaluator payload |
| --- | --- | --- | --- |
| Legacy/default | `0.3.x` | Existing behavior | `0.3.x` |
| Ax contract 1 | `0.4.x` | 1 | `0.3.x` |
| Ax contract 2 | `0.5.x` (new `0.5.0`) | 2 | New `0.4.0`; compatible `0.3.x` accepted |

Reading a contract-1 campaign does not upgrade it or change its fingerprint.
Opting existing Ax history into contract 2 requires no outstanding work and
`rebuild-optimizer --reason "explicit contract upgrade"`. The old scalar/space
configuration must still match the source fingerprint. Required historical
measurements cannot be fabricated; incompatible history requires a new campaign.

Contract, codec, objective/measurement definitions, measured bounds, acquisition,
reference and seed are fingerprinted. A contract-2 semantic change requires an
explicit validated rebuild with no outstanding work, or a new campaign. Rebuild
preserves exact prior state/snapshot bytes, records source configuration and
environment, and creates a new lineage without allocating work. An invalid
source snapshot cannot authorize a simultaneous unverified configuration change.
Same-configuration lost-cache rebuilds retain the existing recovery behavior.

Keep the original code, full configuration and environment with the backup.
Rollback restores that matched set; never strip new fields or lower a schema
version. Old controllers reject new campaign state; old binaries do not provide
an independent guarantee that a new payload sent to an old campaign is rejected.
Keep evaluator payloads with their matched campaign lineage.

Generation verifies immutable snapshot integrity and the six-version runtime
guard. Terminal results remain deliverable when a derived snapshot is lost.
After public Ax JSON restoration, exact successful canonical data is reattached
through public `Client.attach_data` before fitting, avoiding JSON precision loss
without changing tolerances or mutating private Ax attributes.

See the [walkthroughs](../examples/ax_capabilities/README.md),
[bounded evidence protocol](../benchmarks/ax_capabilities/README.md) and
[verification matrix](ax-support-matrix.md). Local evidence does not substitute
for the required four OS/Python CI lanes on the exact owner-committed revision.
