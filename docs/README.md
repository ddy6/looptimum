# Docs

Public-facing documentation for integration, FAQ, security/data handling,
use-case fit, and service packaging.

These pages document Looptimum operating patterns and rollout materials.

Included files:

- `integration-guide.md`: end-to-end `suggest -> evaluate -> ingest` integration
  workflow plus lifecycle/ops command usage
- `operational-semantics.md`: idempotency, pending semantics, lifecycle
  controls, locking, resume behavior, and crash recovery expectations
- `recovery-playbook.md`: prescriptive interruption/recovery runbook and
  operator decision tree for CI/local incident handling
- `how-it-works.md`: conceptual optimizer behavior, backend model by template,
  exploration/exploitation policy, constraints posture, and determinism boundaries
- `stability-guarantees.md`: public compatibility guarantees, deprecation
  policy, and breaking-change rules for `v0.2.x` (current patch:
  `v0.2.5`)
- `migrations/README.md`: migration policy, fixture authority, and support window
- `migrations/template.md`: required migration spec checklist template
- `migrations/v0.2.x-to-v0.3.0.md`: concrete state-schema migration spec
- `feedback-loop.md`: post-release feedback intake, issue-triage workflow,
  and backlog synchronization rules
- `search-space.md`: supported parameter types, constraints framing, and
  multi-objective boundaries
- `decision-trace.md`: acquisition log schema and decision metadata guidance
- `pilot-checklist.md`: intake-to-execution checklist and responsibility
  alignment for pilot runs
- `faq.md`: common technical and operational questions
- `security-data-handling.md`: detailed local/offline and data-minimization guidance
- `pricing-tiers.md`: placeholder in this release; full tier/pricing detail
  will return in the next update
- `use-cases.md`: fit guidance for engineering/simulation, biotech/lab
  pipelines, and ML HPO teams

Reference artifacts:

- `examples/README.md`
- `examples/state_snapshots/README.md`
- `examples/decision_trace/README.md`
- `../examples/toy_objectives/03_tiny_quadratic_loop/README.md`

Examples positioning:

- examples are integration pattern references (wiring + payload flow), not
  benchmark or performance leaderboards.
