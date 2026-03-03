# Looptimum

Looping refinement toward an optimum parameter set.

Use this site as the quick launch point for setup, integration, and pilot planning.

## Quick Start

Run a local demo from repo root:

```bash
python3 templates/bo_client_demo/run_bo.py demo \
  --project-root templates/bo_client_demo \
  --steps 5
```

For full command sequences and resume behavior:

- [FAQ](./faq.md)

## Core Documentation

- [Integration Guide](./integration-guide.md)
- [FAQ](./faq.md)
- [Security and Data Handling](./security-data-handling.md)
- [Use Cases and Fit](./use-cases.md)
- [Pricing Tiers](./pricing-tiers.md)

## Integration Assets

- [Docs Examples](./examples/README.md)
- [State Snapshot References](./examples/state_snapshots/README.md)

Repository paths used during integration:

- `quickstart/README.md`
- `client_harness_template/README.md`
- `client_harness_template/README_INTEGRATION.md`
- `examples/README.md`

## Scope and Operating Model

The optimization loop is local-first and file-backed (`suggest -> evaluate -> ingest`).
It does not require hosted orchestration and works in restricted/offline environments.

## Next Action

If you are evaluating fit for a pilot, start with:

1. Intake checklist (`intake.md`)
2. [Integration Guide](./integration-guide.md)
3. FAQ + security docs on this site
