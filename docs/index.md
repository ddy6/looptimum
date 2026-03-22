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
- [AWS Batch Integration](./aws-batch-integration.md)
- [Operational Semantics](./operational-semantics.md)
- [Recovery Playbook](./recovery-playbook.md)
- [ETL/Pipeline Knob-Tuning Quickstart](../quickstart/etl-pipeline-knob-tuning.md)

## Core Documentation

- [Quick Reference](./quick-reference.md)
- [Integration Guide](./integration-guide.md)
- [AWS Batch Integration](./aws-batch-integration.md)
- [Operational Semantics](./operational-semantics.md)
- [Recovery Playbook](./recovery-playbook.md)
- [How It Works](./how-it-works.md)
- [Type Safety](./type-safety.md)
- [CI Knob Tuning](./ci-knob-tuning.md)
- [Stability Guarantees](./stability-guarantees.md)
- [Feedback Loop](./feedback-loop.md)
- [Search Space Contract](./search-space.md)
- [Constraints Contract](./constraints.md)
- [Decision Trace](./decision-trace.md)
- [Pilot Checklist](./pilot-checklist.md)
- [FAQ](./faq.md)
- [Security and Data Handling](./security-data-handling.md)
- [Use Cases and Fit](./use-cases.md)
- [Pricing and Service Options](./pricing-tiers.md)

## Integration Assets

- [Docs Examples](./examples/README.md)
- [Batch + Async Worker Example Pack](./examples/batch_async/README.md)
- [Multi-Objective Example Pack](./examples/multi_objective/README.md)
- [Constraints Examples](./examples/constraints/README.md)
- [State Snapshot References](./examples/state_snapshots/README.md)
- [Decision-Trace References](./examples/decision_trace/README.md)
- [Benchmark Evidence Index](../benchmarks/README.md)
- Tiny end-to-end loop:
  `examples/toy_objectives/03_tiny_quadratic_loop/run_tiny_loop.py`

Repository paths used during integration:

- `quickstart/README.md`
- `docs/aws-batch-integration.md`
- `client_harness_template/README.md`
- `client_harness_template/README_INTEGRATION.md`
- `client_harness_template/objective_aws_batch_example.py`
- `client_harness_template/aws_batch_config.example.json`
- `examples/README.md`

## Scope and Operating Model

The optimization loop is local-first and file-backed (`suggest -> evaluate -> ingest`),
with lifecycle/ops controls for pending management and diagnostics.
It does not require hosted orchestration and works in restricted/offline environments.
This outer-loop pattern is especially useful for expensive evaluation campaigns,
including long-running training or evaluation jobs.

Integration note:

- examples are wiring references for contract implementation, not benchmark
  performance claims.

## Next Action

If you are evaluating fit for a pilot, start with:

1. [Pilot and Service Options](../PILOT.md)
2. Intake checklist (`intake.md`)
3. [Pilot Checklist](./pilot-checklist.md)
4. [Integration Guide](./integration-guide.md)
