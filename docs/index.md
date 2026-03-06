# Looptimum Docs

Use this page as the launch point for integration, contract semantics, and
pilot planning.

## Quick Start

Run a local demo from repo root:

```bash
python3 templates/bo_client_demo/run_bo.py demo \
  --project-root templates/bo_client_demo \
  --steps 5
```

For full command sequences and resume behavior:

- [Integration Guide](./integration-guide.md)
- [Operational Semantics](./operational-semantics.md)
- [Recovery Playbook](./recovery-playbook.md)

## Core Documentation

- [Integration Guide](./integration-guide.md)
- [Operational Semantics](./operational-semantics.md)
- [Recovery Playbook](./recovery-playbook.md)
- [How It Works](./how-it-works.md)
- [Stability Guarantees](./stability-guarantees.md)
- [Migrations](./migrations/README.md)
- [Feedback Loop](./feedback-loop.md)
- [Search Space Contract](./search-space.md)
- [Decision Trace](./decision-trace.md)
- [Pilot Checklist](./pilot-checklist.md)
- [FAQ](./faq.md)
- [Security and Data Handling](./security-data-handling.md)
- [Use Cases and Fit](./use-cases.md)
- [Pricing Tiers](./pricing-tiers.md)

## Integration Assets

- [Docs Examples](./examples/README.md)
- [State Snapshot References](./examples/state_snapshots/README.md)
- [Decision-Trace References](./examples/decision_trace/README.md)
- Tiny end-to-end loop:
  `examples/toy_objectives/03_tiny_quadratic_loop/run_tiny_loop.py`

Repository paths used during integration:

- `quickstart/README.md`
- `client_harness_template/README.md`
- `client_harness_template/README_INTEGRATION.md`
- `examples/README.md`

## Scope and Operating Model

The optimization loop is local-first and file-backed (`suggest -> evaluate -> ingest`),
with lifecycle/ops controls for pending management and diagnostics.
It does not require hosted orchestration and works in restricted/offline environments.

Integration note:

- examples are wiring references for contract implementation, not benchmark
  performance claims.

## Next Action

If you are evaluating fit for a pilot, start with:

1. Intake checklist (`intake.md`)
2. [Pilot Checklist](./pilot-checklist.md)
3. [Integration Guide](./integration-guide.md)
4. [Operational Semantics](./operational-semantics.md)
