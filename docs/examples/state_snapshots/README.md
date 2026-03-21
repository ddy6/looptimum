# State Snapshot Examples

These files are generated reference artifacts showing a minimal run lifecycle for `templates/bo_client_demo`:

1. `status_empty.json` (no state file yet)
2. `suggestion_1.json` + `bo_state_after_suggest.json` + acquisition log with
   current decision metadata shape
3. `result_1_generated.json` + `bo_state_after_ingest.json` + `observations_after_ingest.csv`
4. `result_1_timeout_generated.json` + `bo_state_after_timeout_ingest.json` + `observations_after_timeout_ingest.csv`
5. `status_after_ingest.json` and `status_after_timeout_ingest.json` for
   success vs non-`ok` ingest outcomes

The timeout snapshot includes `terminal_reason` (`status=timeout`) and
`penalty_objective` to show canonical non-`ok` payload normalization in `v0.3.x`.

The acquisition-log snapshots are unconstrained examples, so their
`constraint_status.enabled` field is `false`.

They are for documentation examples, not replay into an active run.

Integration pattern note:

- these snapshots demonstrate artifact wiring and state transitions
- they are not benchmark or optimization performance claims
