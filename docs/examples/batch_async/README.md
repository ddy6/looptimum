# Batch + Async Worker Example Pack

Generated reference artifacts for a clean batch run captured from
`templates/bo_client_demo`.

This pack shows the current batch/async surface:

- `bo_config.json`: example config with `batch_size = 2`,
  `max_pending_trials = 3`, and `worker_leases.enabled = true`
- `suggestion_bundle.json`: default count-2 `suggest` bundle output
- `suggestions.jsonl`: equivalent worker-handoff JSONL form of the same
  allocation
- `status_after_batch_suggest.json`: pending-state headline with
  `leased_pending = 2`
- `result_1.json` / `result_2.json`: canonical ingest payloads for the leased
  trials
- `status_after_ingest.json`: final run headline after both leased ingests
- `state/bo_state.json`: authoritative state after the batch completes
- `state/report.json` / `state/report.md`: explicit report outputs for the run
- `state/trials/trial_<id>/manifest.json`: per-trial manifests showing
  `lease_token`, heartbeat metadata, and artifact pointers

The captured flow is:

1. controller runs `suggest --count 2 --json-only`
2. workers receive either the bundle payload or the JSONL lines
3. worker 1 claims its trial with `heartbeat --lease-token <token>`
4. both results are ingested with matching `--lease-token`
5. `report` is generated from the finished state

Operational notes illustrated here:

- count-1 `suggest` stays backward compatible; batch output starts at count `> 1`
- `--jsonl` is the worker-oriented serialization for the same canonical
  suggestion objects
- `max_pending_trials` is a whole-batch guardrail, not a partial allocator
- lease tokens are CLI-side claim checks; they are not embedded into ingest
  payload JSON

These files are documentation examples, not benchmark claims.
