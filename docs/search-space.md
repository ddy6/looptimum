# Search Space Contract

This document defines the current search-space support in public templates.

## Current Support

All public templates currently support:

- `float` parameters with numeric bounds
- `int` parameters with numeric bounds
- `bool` parameters
- `categorical` parameters with explicit `choices`
- numeric `scale` values of `linear` or `log`
- optional conditional activation via `when`

The canonical contract file is `parameter_space.json`.

These are the general template capabilities. Native Ax contract 1 accepts flat
mixed-type spaces and rejects conditional `when` parameters. Explicit
[Ax contract 2](./ax-contract2.md#exact-parameter-subset) adds typed heterogeneous
choices and a finite single-parent conditional-tree subset. Check the
[Ax support matrix](./ax-support-matrix.md) for backend-specific limits.

## Choose a useful parameter space

Start with a small set of settings your evaluator can actually control, and
record the units and meaning of each setting. Put optimization targets in
`objective_schema.json`; contract-2 constraint-only observations belong in
[`measurement_metrics`](./ax-contract2.md#measurements-and-standard-errors),
separately from objectives. Bounds should describe safe, meaningful experiments
rather than the widest range the software accepts.

Use linear scale for additive changes and log scale for positive values spanning
orders of magnitude. Use bool for a switch and categorical choices for distinct
options; do not imply an ordering by encoding unrelated categories as integers.
Express genuinely conditional settings with `when` only on a supporting backend.
Keep invalid combinations in bounds or supported hard constraints.

Freeze names, units and the space for a comparison. Expand it after proving one
end-to-end evaluation and understanding the measurement's noise. Define the
[objective and acceptance policy](./integration-guide.md#choose-parameters-and-define-the-measurement)
alongside the space, rather than tuning the score definition during a campaign.

## Parameter Shapes

### Numeric

```json
{
  "name": "lr",
  "type": "float",
  "bounds": [0.0001, 0.1],
  "scale": "log"
}
```

Numeric notes:

- `float` and `int` require `bounds`
- `scale` defaults to `linear`
- `scale: "log"` requires strictly positive bounds

### Boolean

```json
{
  "name": "use_bn",
  "type": "bool"
}
```

### Categorical

```json
{
  "name": "optimizer",
  "type": "categorical",
  "choices": ["adam", "sgd", "rmsprop"]
}
```

### Conditional

```json
{
  "name": "momentum",
  "type": "float",
  "bounds": [0.0, 0.99],
  "when": {
    "optimizer": "sgd"
  }
}
```

Conditional notes:

- inactive params are omitted from suggestion payloads and persisted state
- `when` matches raw controller values, not encoded model vectors
- current controllers for `when` should be `bool`, `int`, or `categorical`

## Sampling Semantics

### `float`

- `linear`: uniform over the declared bounds
- `log`: log-uniform over strictly positive bounds

### `int`

- `linear`: inclusive integer sampling
- `log`: log-scaled sampling followed by integer projection

### `bool`

- sampled as `true` / `false`

### `categorical`

- sampled from the declared `choices`

### `when`

- inactive dependent params are not emitted in `suggest`
- ingest canonicalization ignores inactive known fields for duplicate/pending
  matching

## Modeling Representation

User-facing and state-authoritative artifacts keep raw parameter values.

Internal model-facing representation:

- numeric params use scalar encoding
- bool params use binary numeric encoding
- categorical params use one-hot encoding
- inactive conditional branches contribute zeroed encoded segments

This keeps logs, state, CSVs, and evaluator payloads readable while preserving
a stable numeric representation for proxy, GP, and BoTorch paths.

## Constraints and Invalid Regions

Base parameter bounds are still the first line of defense.

Optional hard constraints are defined in a separate `constraints.json`
contract:

- `bound_tightening`
- `linear_inequalities`
- `forbidden_combinations`

Legacy proxy/direct-GP hard-constraint behavior:

- enforced during warmup and surrogate candidate-pool generation
- can reduce the feasible pool with a warning
- can hard-fail `suggest` if all sampled attempts are infeasible

Soft-constraint behavior is not built into acquisition scoring today.

For soft preferences or tradeoff pressure:

- shape the scalar objective directly
- use explicit penalties in evaluator output
- reserve `constraints.json` for true feasibility rules

Native Ax uses its own generation strategy and supported constraint translation;
legacy candidate-pool controls do not affect it. See the
[constraints guide](./constraints.md) for rule details and backend boundaries.

## Multi-Objective Handling

Current public templates support multi-objective authoring through
`objective_schema.json`.

Details:

- `objective_schema.json` can declare a primary objective, optional secondary
  objectives, and optional scalarization policy
- legacy optimizer-facing ranking stays scalar or ordered internally; Ax
  contract 1 supports its documented scalar modes and rejects lexicographic ordering
- status, manifests, and reports preserve raw `objective_vector` values and
  report a Pareto summary when multiple objectives are present

Explicit [Ax contract-2 Pareto acquisition](./ax-contract2.md#measured-feasibility-and-pareto-acquisition)
uses a genuine vector objective with configured directions and reference thresholds.
Its scalar `best` remains a reporting summary. Observed Pareto reporting alone
does not select this acquisition mode.

See the [scalar/ordered example pack](./examples/multi_objective/README.md) and
[contract-2 walkthroughs](../examples/ax_capabilities/README.md).

## Reproducibility Guidance

To keep optimization traces reproducible:

- keep parameter names stable within a campaign
- keep bounds, choices, `scale`, and `when` logic stable within a campaign
- version control all search-space and constraint changes
- avoid changing units or semantic meaning mid-campaign

## Practical Pilot Pattern

For an initial campaign:

1. Start with 2-20 high-leverage parameters.
2. Keep hard feasibility in bounds + `constraints.json`.
3. Keep soft preferences in the objective, not in the constraint contract.
4. Add conditional branches only when they reflect real evaluator structure.
5. Expand complexity only after one stable end-to-end loop.

## Related Docs

- `docs/constraints.md`
- `docs/how-it-works.md`
- `docs/operational-semantics.md`
- `docs/decision-trace.md`
