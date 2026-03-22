# Warm-Start Import / Export Example Pack

Generated reference artifacts for a permissive warm-start capture from
`templates/bo_client_demo`.

This pack shows the current public warm-start surface:

- `bo_config.json`: unmodified demo config used for the capture
- `parameter_space.json`: conditional parameter space used to show inactive
  param canonicalization during import/export
- `seed_import.jsonl`: mixed historical rows used as warm-start input
- `status_after_import.json`: headline state after the permissive import
- `exported_observations.jsonl`: canonical JSONL export from authoritative
  state
- `exported_observations.csv`: flat CSV export with `param_*` /
  `objective_*` columns
- `state/import_reports/import-*.json`: machine-readable permissive import
  summary plus rejected-row detail
- `state/bo_state.json`: authoritative state after import
- `state/observations.csv`: flattened observation table regenerated from the
  imported authoritative state
- `state/event_log.jsonl`: event stream showing import and export provenance
- `state/report.json` / `state/report.md`: explicit report outputs generated
  after the import
- `state/trials/trial_<id>/manifest.json`: per-trial manifests showing fresh
  local `trial_id` values and preserved `source_trial_id` provenance

The captured flow is:

1. controller runs `import-observations --import-mode permissive`
2. invalid rows are rejected into `state/import_reports/import-*.json`
3. `status` confirms imported observations are now first-class runtime state
4. `report` is generated explicitly from the imported observations
5. `export-observations` writes both JSONL and CSV forms for future reuse

Operational notes illustrated here:

- imported rows always receive fresh local `trial_id` values from the target
  campaign
- `source_trial_id` is provenance only; it is preserved in state, manifests,
  exports, and permissive reject reports
- inactive conditional params are omitted from authoritative state and appear
  blank in flat CSV when another row activates the same param
- permissive import does not corrupt accepted rows when one or more rows fail
  validation
- export JSONL and export CSV are both suitable warm-start inputs for later
  campaigns

These files are documentation examples, not benchmark claims.
