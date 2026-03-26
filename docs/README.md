# Docs

Public-facing documentation for integration, FAQ, security/data handling,
use-case fit, and service packaging, including expensive training/evaluation
campaigns.

These pages document Looptimum operating patterns and rollout materials.

Included files:

- `quick-reference.md`: spec-style contract quick reference (inputs/outputs,
  failure semantics, state definitions, compatibility posture)
- `integration-guide.md`: end-to-end `suggest -> evaluate -> ingest` integration
  workflow plus lifecycle/ops command usage
- `service-api-preview.md`: preview-only local FastAPI wrapper over registered
  campaign roots, with startup steps, endpoint scope, and operational caveats
- `dashboard-preview.md`: preview-only read-only operator UI mounted from the
  local service stack, with route scope, flag posture, and operator workflow
- `auth-preview.md`: preview-only auth/RBAC/SSO posture for the local service
  and dashboard stack, including local-dev auth mode and OIDC caveats
- `coordination-preview.md`: preview-only multi-controller coordination posture
  for the local service stack, including SQLite lease startup, reclaim
  behavior, and controller-vs-worker lease boundaries
- `integration-starter-kit.md`: optional scheduler, webhook-sidecar, and
  tracker-adapter deployment guidance for the starter-kit helpers
- `aws-batch-integration.md`: optional AWS Batch evaluator path, config, sidecar
  recovery records, and scope boundaries
- `operational-semantics.md`: idempotency, pending semantics, lifecycle
  controls, locking, resume behavior, and crash recovery expectations
- `recovery-playbook.md`: prescriptive interruption/recovery runbook and
  operator decision tree for CI/local incident handling
- `how-it-works.md`: conceptual optimizer behavior, backend model by template,
  exploration/exploitation policy, constraints posture, and determinism boundaries
- `type-safety.md`: mypy gate scope, staged strictness policy, and `Any`/suppression rules
- `ci-knob-tuning.md`: platform-agnostic CI runbook (with GitHub examples) for
  state persistence, contamination controls, safe parallelism, and robust-best policy
- `stability-guarantees.md`: public compatibility guarantees, deprecation
  policy, and breaking-change rules for `v0.4.x` (current tag:
  `v0.4.0`)
- `feedback-loop.md`: post-release feedback intake, issue-triage workflow,
  and backlog synchronization rules
- `search-space.md`: supported parameter types, constraints framing, and
  multi-objective handling
- `constraints.md`: hard-constraint contract semantics, troubleshooting, and
  example authoring guidance
- `decision-trace.md`: acquisition log schema and decision metadata guidance
- `pilot-checklist.md`: intake-to-execution checklist and responsibility
  alignment for pilot runs
- `faq.md`: common technical and operational questions
- `security-data-handling.md`: detailed local/offline and data-minimization guidance
- `packages.md`: repo path, preview surfaces, and pilot-support entry points
- `use-cases.md`: fit guidance for engineering/simulation, biotech/lab
  pipelines, ML HPO teams, and large-model outer-loop tuning

Reference artifacts:

- `../PILOT.md`
- `examples/README.md`
- `examples/batch_async/README.md`
- `examples/service_api_preview/README.md`
- `examples/dashboard_preview/README.md`
- `examples/auth_preview/README.md`
- `examples/coordination_preview/README.md`
- `examples/multi_objective/README.md`
- `examples/warm_start/README.md`
- `examples/starterkit/README.md`
- `examples/state_snapshots/README.md`
- `examples/decision_trace/README.md`
- `examples/constraints/README.md`
- `../quickstart/etl-pipeline-knob-tuning.md`
- `../examples/toy_objectives/03_tiny_quadratic_loop/README.md`
- `../benchmarks/README.md`

Examples positioning:

- examples are integration pattern references (wiring + payload flow), not
  benchmark or performance leaderboards.
