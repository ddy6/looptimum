# Looptimum

[![CI](https://github.com/ddy6/looptimum/actions/workflows/ci.yml/badge.svg)](https://github.com/ddy6/looptimum/actions/workflows/ci.yml)
[![Latest Release](https://img.shields.io/github/v/release/ddy6/looptimum?display_name=tag)](https://github.com/ddy6/looptimum/releases)

Looptimum selects experiment settings and records results in local files.
Your evaluator runs the simulation, training job, pipeline or lab workflow in
its own environment. Saved history supports inspection and restart between
expensive evaluations.

Version in this checkout: `v1.1.0`. See the
[published release](https://github.com/ddy6/looptimum/releases/tag/v1.1.0),
[release notes](docs/releases/v1.1.0.md) and
[migration guide](docs/migration-v1.md) for existing campaigns.

## Run a first campaign

Follow the **[portable quickstart](quickstart/README.md)** to create a fresh
ordinary controller, evaluate its actual suggestion and ingest the result.
Python 3.11+ is required; the default proxy path needs no numerical packages.

Controller users need the complete portable source bundle. The current wheel
packages the preview service and optional dependency extras; it does not install
controller templates or a controller CLI. See
[installation routes](docs/packages.md#installation-routes) before choosing a setup.

The loop is small:

1. **Suggest:** select a trial from your parameter space and previous observations.
2. **Evaluate:** run your own workload with those settings.
3. **Ingest:** record its score or failure, then inspect or continue the campaign.

Keep each campaign outside the reusable source templates. The quickstart
creates its own runtime, schemas, configuration and state directory.

## Connect your workload

You define parameter bounds, an objective and the evaluator boundary.
Looptimum allocates trial IDs, validates matching results and maintains local
observations and decision traces. It does not run your domain workload or decide
whether its outputs satisfy your project's acceptance policy.

The [integration guide](docs/integration-guide.md) covers evaluator wiring,
measurement design, failures and ingest retries. The
[client harness](client_harness_template/README.md) is an optional adapter;
its local objective is a stub until you supply an implementation.

Public templates support numeric, boolean and categorical parameters, with
conditional settings on supporting backends. Use the
[search-space contract](docs/search-space.md) for types and bounds and the
[constraints guide](docs/constraints.md) for feasible regions.

## Choose a backend

| Need | Starting point |
| --- | --- |
| Establish a lightweight, resumable loop | Ordinary `bo_client` with default `rbf_proxy` |
| Use a direct Gaussian-process surrogate | Ordinary optional `gp`, or full controller's optional `botorch_gp` |
| Use native Ax generation and optimizer snapshots | Optional `ax` in ordinary/full controllers |
| Run the smaller proxy demonstration | `bo_client_demo` |

Numerical backends add dependencies and have distinct capability and recovery
boundaries. Demo is proxy-only. See the [template map](templates/README.md),
[optimizer behavior](docs/how-it-works.md), [Ax support matrix](docs/ax-support-matrix.md)
and [Ax CPU installation guide](docs/ax-installation.md).

Backend selection does not establish an improvement for a particular workload.
Choose a bounded objective, fixed comparison budget and baseline before making
performance claims.

## Inspect the evidence

The retained examples show particular campaigns, not general guarantees:

- [Engineering mesh](docs/examples/snappyhexmesh_campaign/README.md): a selected
  smaller mesh was checked in a separate solver-validation pass; the case study
  records its flow/pressure acceptance conditions.
- [GPT training](docs/examples/gpt_training_campaign/README.md): the selected
  model is compared with a fixed baseline under one seed and a small budget.
  That observation does not establish statistical significance or global optimality.
- [Backend comparison](benchmarks/backend_comparison/README.md): the corrected
  reference covers 200 short synthetic campaigns with budget 12. Its declared
  gates and the original failed reference remain available.

Use the [benchmark index](benchmarks/README.md) for protocols, measured results
and reproducibility artifacts. Keep modeled cost estimates separate from
observed measurements. Wiring examples demonstrate interface use, not rankings
of optimizers or proof of gains on another workload.

## Find the next task

| Task | Reference |
| --- | --- |
| Navigate the documentation | [Task map](docs/index.md) |
| Look up commands and payloads | [Quick reference](docs/quick-reference.md) |
| Resume or recover interrupted work | [Recovery playbook](docs/recovery-playbook.md), [operational semantics](docs/operational-semantics.md) |
| Inspect suggestion decisions | [Decision trace](docs/decision-trace.md) |
| Run batch or scheduler integrations | [Batch/async examples](docs/examples/batch_async/README.md), [starter kit](docs/integration-starter-kit.md) |
| Work with a local service or dashboard | [Service API preview](docs/service-api-preview.md) |
| Check data handling and compatibility | [Data handling](docs/security-data-handling.md), [stability policy](docs/stability-guarantees.md) |
| Develop or prepare a release | [Contributing](CONTRIBUTING.md), [release procedure](docs/release-guide.md) |

The file-backed template contracts are the stable surface; service, dashboard,
auth and multi-controller coordination remain opt-in previews. Package, state,
payload and snapshot versions have separate meanings; consult the stability
and migration guides when upgrading.

## Discuss a pilot

For research or engineering integration questions, contact
[contact@looptimum.io](mailto:contact@looptimum.io). The
[pilot overview](PILOT.md), [intake](intake.md) and
[pilot checklist](docs/pilot-checklist.md) help define the objective, evaluator,
budget and operating constraints before a campaign begins.
