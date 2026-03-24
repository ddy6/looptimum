# Docs Examples

Reference artifacts used by docs pages.

Integration pattern note:

- these examples are wiring references for `suggest -> evaluate -> ingest`
  contract behavior
- they are not benchmark tasks and are not performance claims

Included:

- `batch_async/`: generated bundle JSON, JSONL handoff, lease-token, and
  state/report examples for batch suggest flows
- `service_api_preview/`: sample request/response payloads for the preview-only
  local FastAPI wrapper over registered campaign roots
- `dashboard_preview/`: captured preview dashboard HTML plus the JSON read
  models used for progress, alerts, drilldown, and export actions
- `auth_preview/`: local-dev auth config, authorization failure payloads,
  OIDC config reference, and service-owned auth audit-log examples for the
  preview service/dashboard stack
- `coordination_preview/`: SQLite coordination startup config, concurrent
  preview suggest outcomes, held-lease failure payloads, and reclaim examples
  for the preview service coordination layer
- `multi_objective/`: generated weighted-sum / lexicographic example pack with
  `status`, `report`, and trial-manifest outputs
- `warm_start/`: permissive warm-start import report plus JSONL/CSV observation
  export examples captured from a temp campaign
- `starterkit/`: webhook config/payload examples, rendered Airflow/Slurm
  assets, queue-worker plan output, and tracker payload snapshots for the
  optional starter-kit helpers
- `state_snapshots/`: sample state/log/CSV snapshots captured from a temp run
  of `templates/bo_client_demo`
- snapshots include both `status: "ok"` and non-`ok` ingest examples
- `decision_trace/`: deterministic acquisition-log sample, annotations, and CLI
  transcript
- `constraints/`: valid `constraints.json` examples for each hard-constraint
  rule family plus a combined sample contract
- `snappyhexmesh_campaign/`: sanitized domain-specific case study with
  archived BO state, validation summaries, and derived plots
- `../../examples/toy_objectives/03_tiny_quadratic_loop/`: dedicated tiny
  end-to-end objective loop used to generate the golden decision trace
