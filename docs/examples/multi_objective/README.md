# Multi-Objective Example Pack

Generated reference artifacts for a small multi-objective run captured from
`templates/bo_client_demo`.

This pack shows the current public multi-objective contract surface:

- `objective_schema.json`: weighted-sum example with `primary_objective`,
  `secondary_objectives`, and `scalarization`
- `objective_schema_lexicographic.json`: alternative lexicographic objective
  contract using the same raw objective names
- `suggestion_1.json` / `suggestion_2.json`: canonical suggestion payloads
- `result_1.json` / `result_2.json`: ingest payloads with complete
  `objectives` maps
- `status_after_ingest.json`: `best` with scalarized ranking metadata and raw
  `objective_vector`
- `state/report.json` / `state/report.md`: report outputs with
  `objective_config`, scalarized ranking data, and `pareto_front`
- `state/trials/trial_<id>/manifest.json`: trial manifests with
  `objective_vector` and `scalarization_policy`

The weighted-sum capture uses:

- primary objective: `loss` (`minimize`)
- secondary objective: `throughput` (`maximize`)
- scalarization policy: `weighted_sum`

The generated `report.json` shows both observed trials on the Pareto front, and
`status_after_ingest.json` shows `best.objective_name = "scalarized"` with the
raw objective vector preserved.

These files are documentation examples, not benchmark claims.
