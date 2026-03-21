# Constraints Examples

These example files show valid `constraints.json` shapes for the current
hard-constraint DSL.

Included files:

- `bound_tightening.json`: narrows numeric sampling bounds
- `linear_inequalities.json`: raw numeric inequality rules
- `forbidden_combinations.json`: explicit disallowed raw-value combinations
- `combined_campaign.json`: mixed example using all three rule families

Notes:

- examples are patterns, not universal defaults
- parameter names and value types must match your own `parameter_space.json`
- `constraints.json` is a hard feasibility filter, not a soft-scoring system

Operator guidance:

- if `suggest` warns that constraints reduced the feasible pool, inspect the
  latest acquisition-log line before tightening further
- if `suggest` fails with `constraints eliminated all ... attempts`, read
  `constraint_error_reason` and `constraint_status.reject_counts` in
  `state/acquisition_log.jsonl`

Related docs:

- `../../constraints.md`
- `../../decision-trace.md`
- `../../search-space.md`
