# Docs

Public-facing documentation for integration, FAQ, security/data handling,
use-case fit, and service packaging.

These pages document Looptimum operating patterns and rollout materials.

Included files:

- `integration-guide.md`: end-to-end `suggest -> evaluate -> ingest` integration workflow
- `operational-semantics.md`: idempotency, pending semantics, resume behavior,
  and crash recovery expectations
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

Examples positioning:

- examples are integration pattern references (wiring + payload flow), not
  benchmark or performance leaderboards.
