# Coordination Preview Example Pack

Generated reference artifacts for the preview-only SQLite coordination layer in
`service/`.

This pack is intentionally narrow: it shows the controller-lease surface that
wraps preview mutating routes, not a new optimizer-state format.

Included artifacts:

- `bo_config.json`: campaign-side feature-flag example enabling service preview
  plus multi-controller preview
- `service_env.example`: local service startup env example for
  `sqlite_lease` mode
- `parallel_suggest_results.json`: aggregate capture from three concurrent
  preview `suggest` requests against one coordinated campaign root
- `status_after_parallel_suggest.json`: resulting `GET .../status` payload
  after those coordinated suggests land as pending trials
- `coordination_unavailable_response.json`: representative `409` payload when
  a live controller lease blocks a fail-fast mutating request
- `reclaimed_suggest_response.json`: representative successful `suggest`
  payload after an expired controller lease is reclaimed

Interpretation notes:

- `parallel_suggest_results.json` is an aggregate documentation artifact, not a
  single API response
- controller coordination leases are distinct from per-trial worker
  `lease_token` values
- runtime state is still authoritative in the campaign root; the SQLite file
  under `service_state/` is preview coordination metadata only

These files are documentation examples, not API stability guarantees.
