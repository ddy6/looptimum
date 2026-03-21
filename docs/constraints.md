# Constraints Contract

This page documents the current hard-constraint support for public templates.

## Current Support

Looptimum supports an optional top-level `constraints.json` contract alongside:

- `bo_config.json`
- `parameter_space.json`
- `objective_schema.json`

Current rule collections:

- `bound_tightening`: narrow numeric sampling bounds before candidate draws
- `linear_inequalities`: raw numeric linear constraints (`<=` or `>=`)
- `forbidden_combinations`: disallow specific raw parameter combinations

Constraints are enforced during `suggest`. They are not authoritative state and
they do not replace the base parameter bounds in `parameter_space.json`.

## Hard vs Soft Constraints

`constraints.json` is a hard filter only.

What it does:

- removes infeasible warmup candidates
- removes infeasible surrogate candidate-pool candidates
- logs feasibility metadata for audit/debugging
- hard-fails `suggest` if every sampled attempt is infeasible

What it does not do:

- add soft penalties to acquisition scoring
- express preference tradeoffs
- relax constraints automatically when the feasible region is sparse

For soft preferences, keep using scalar objective shaping or explicit
`status: "failed"` / `status: "timeout"` policies in your evaluator flow.

## Rule Semantics

### `bound_tightening`

Use this when the true feasible range is narrower than the base bounds for a
numeric parameter.

Rules:

- `param` must reference a raw `float` or `int` parameter
- `min` and `max` must stay within the parameter's declared bounds
- combined tightening must still leave a non-empty range

### `linear_inequalities`

Use this for raw numeric relationships between parameters.

Rules:

- terms are evaluated on raw numeric parameter values
- only raw `float` and `int` parameters are allowed
- `operator` must be `<=` or `>=`
- coefficients and `rhs` must be finite numbers

This does not operate on one-hot categorical encodings or boolean/categorical
model features.

### `forbidden_combinations`

Use this for explicit disallowed raw value combinations.

Rules:

- matches use raw parameter values, not encoded model vectors
- supports numeric, boolean, and categorical values
- each `when` object is an exact forbidden pattern

This is the right tool for categorical exclusions such as
`optimizer=sgd` with `use_bn=true`.

## Runtime Behavior

When `constraints.json` is present:

1. `validate` loads and semantically validates the contract.
2. `suggest` applies bound tightening before random sampling.
3. Warmup and surrogate candidate pools are filtered through the same
   feasibility evaluator.
4. Successful decisions record `constraint_status` in
   `state/acquisition_log.jsonl`.
5. If constraints reduce but do not eliminate the feasible pool, `suggest`
   still succeeds and prints a warning on `stderr`.
6. If constraints eliminate all sampled attempts, `suggest` exits nonzero,
   creates no new pending trial, and appends a failure decision with
   `constraint_error_reason` to `state/acquisition_log.jsonl`.

## Constraint Status in the Decision Trace

Successful and failed constrained `suggest` attempts record a nested
`constraint_status` object with:

- `enabled`
- `phase`
- `requested`
- `accepted`
- `attempted`
- `rejected`
- `feasible_ratio`
- `reject_counts`
- `warning`

Use the latest acquisition-log line to see which rule family dominated rejects
when a campaign becomes infeasible.

## Troubleshooting All-Infeasible Campaigns

If `suggest` fails with `constraints eliminated all ... attempts`:

1. Run `validate` first to confirm the contract is structurally and
   semantically valid.
2. Read the latest `state/acquisition_log.jsonl` line and inspect
   `decision.constraint_error_reason` plus `decision.constraint_status.reject_counts`.
3. Loosen the rule family that dominates rejects:
   - widen `bound_tightening`
   - relax the `rhs` of a linear inequality
   - remove or narrow an over-broad forbidden combination
4. Increase `candidate_pool_size` only when the feasible region is real but
   very sparse; it will not fix an impossible contract.
5. Move preference-style tradeoffs out of `constraints.json` and into the
   objective if the rule is actually soft.

## Shipped Examples

Reference examples live under `docs/examples/constraints/`:

- `bound_tightening.json`
- `linear_inequalities.json`
- `forbidden_combinations.json`
- `combined_campaign.json`

Treat those as patterns, not copy-paste defaults. Parameter names and value
types must match your own `parameter_space.json`.

## Related Docs

- `docs/search-space.md`
- `docs/how-it-works.md`
- `docs/decision-trace.md`
- `docs/operational-semantics.md`
