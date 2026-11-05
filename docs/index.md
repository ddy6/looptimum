# Documentation map

Choose the task you need now. Start with a portable campaign, then follow the
integration and recovery references as your evaluator becomes more demanding.

## Run

- [Portable quickstart](../quickstart/README.md): one fresh ordinary proxy campaign.
- [Template choices](../templates/README.md) and [installation routes](./packages.md#installation-routes).
- [ETL/pipeline walkthrough](../quickstart/etl-pipeline-knob-tuning.md) for a worked application.
- [Use cases and fit](./use-cases.md), [FAQ](./faq.md), and [pilot checklist](./pilot-checklist.md).

## Integrate

- [Integration guide](./integration-guide.md): evaluator boundary, measurement and result policy.
- [Harness file map](../client_harness_template/README.md) and [adapter implementation](../client_harness_template/README_INTEGRATION.md).
- [Quick reference](./quick-reference.md): CLI and payload contracts.
- [Batch/async workers](./examples/batch_async/README.md), [starter kit](./integration-starter-kit.md), and [AWS Batch](./aws-batch-integration.md).
- [Warm-start import/export](./examples/warm_start/README.md) and [multi-objective examples](./examples/multi_objective/README.md).
- [Security and data handling](./security-data-handling.md).

## Configure

- [Search space](./search-space.md): parameter selection, types, bounds and conditional settings.
- [Constraints](./constraints.md) and [objective design](./integration-guide.md#choose-parameters-and-define-the-measurement).
- [How it works](./how-it-works.md): backends and effective versus ignored configuration.
- [Ax contract 2](./ax-contract2.md) in v1.1.0: measurement errors, exact typed conditional spaces, measured constraints and true Pareto acquisition.
- Native Ax: [backend semantics](./ax-backend.md), [CPU/offline installation](./ax-installation.md), [support matrix](./ax-support-matrix.md).
- Preview surfaces: [service API](./service-api-preview.md), [dashboard](./dashboard-preview.md), [auth](./auth-preview.md), [coordination](./coordination-preview.md).
- [CI knob tuning](./ci-knob-tuning.md): persistence, safe concurrency and repeat policy.

## Recover

- [Recovery playbook](./recovery-playbook.md): operator decisions after interruption.
- [Operational semantics](./operational-semantics.md): canonical state, locking and replay.
- [GP fit recovery](./gp-fit-recovery.md) and [Ax snapshot recovery/rebuild](./ax-backend.md#state-and-recovery-boundaries).
- [Stability guarantees](./stability-guarantees.md) and [v1 migration](./migration-v1.md).

## Inspect evidence

- [Decision trace](./decision-trace.md) and [trace reference artifacts](./examples/decision_trace/README.md).
- [Benchmark index](../benchmarks/README.md) and [backend comparison](../benchmarks/backend_comparison/README.md).
- Case studies: [engineering mesh](./examples/snappyhexmesh_campaign/README.md), [GPT training](./examples/gpt_training_campaign/README.md).
- [Example index](./examples/README.md): specialist packs, state snapshots and preview references.
- [Runnable examples](../examples/README.md).
- [Historical reports](../reports/README.md): retained context, not current onboarding instructions.

Case studies retain their evaluation conditions and limitations. Integration
examples demonstrate wiring; they do not establish performance on your workload.

## Maintain

- [Contributing](../CONTRIBUTING.md) and [type safety](./type-safety.md).
- [Release procedure](./release-guide.md) and [v1.1.0 release notes](./releases/v1.1.0.md).
- [Feedback loop](./feedback-loop.md).
- [Site maintenance](../site/README.md): email intake and Git-based publishing.
- [Pilot overview](../PILOT.md), [intake](../intake.md), and [working with Looptimum](./packages.md).
