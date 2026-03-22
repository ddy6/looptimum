# Docs Examples

Reference artifacts used by docs pages.

Integration pattern note:

- these examples are wiring references for `suggest -> evaluate -> ingest`
  contract behavior
- they are not benchmark tasks and are not performance claims

Included:

- `batch_async/`: generated bundle JSON, JSONL handoff, lease-token, and
  state/report examples for batch suggest flows
- `multi_objective/`: generated weighted-sum / lexicographic example pack with
  `status`, `report`, and trial-manifest outputs
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
