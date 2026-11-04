# Integration Guide

Start with the [portable quickstart](../quickstart/README.md), then replace its
synthetic evaluator with your own workload. Looptimum selects settings and
records results; your function, executable, scheduler or lab process runs the
experiment in its own environment.

## The evaluator boundary

A campaign is a complete portable controller: configuration, parameter/objective
contracts, runtime modules, schemas and local state. Keep one controller per
campaign while establishing the integration. The
[template map](../templates/README.md) describes backend choices;
[installation routes](./packages.md#installation-routes) distinguish the portable
controller from the service wheel.

The loop has three responsibilities:

1. `suggest --json-only` allocates a trial and emits its JSON identity/parameters.
2. Your evaluator consumes that exact suggestion and produces a result file.
3. `ingest --results-file` validates and records the completed result.

For example, a suggestion may contain:

```json
{"schema_version": "0.3.0", "trial_id": 7, "params": {"x1": 0.2, "x2": 0.7}, "suggested_at": 1738886400.0}
```

Its successful result preserves the ID and parameters:

```json
{"trial_id": 7, "params": {"x1": 0.2, "x2": 0.7}, "objectives": {"loss": 0.03}, "status": "ok"}
```

These illustrate the shape, not a payload to ingest into another campaign.
Evaluate the actual suggestion. Do not round parameters or substitute an old
example result. Runtime payload versions are separate from the package version;
the ingest schema currently makes `schema_version` optional.

The [quick reference](./quick-reference.md) owns the full command and payload
summary. [Operational semantics](./operational-semantics.md) defines state,
locking, duplicate ingest and lifecycle behavior.

## Connect an evaluator

Use the [client harness implementation guide](../client_harness_template/README_INTEGRATION.md)
for `run_one_eval.py`, its local `evaluate(params)` interface, and failure
options. The harness [file map](../client_harness_template/README.md) identifies
optional scheduler, AWS and tracker helpers.

The supplied `objective.py` is an unimplemented stub. Provide your own module
before expecting successful evaluation. `run_one_eval.py` is a **single-objective**
starter; `--objective-schema` reads the JSON `objective_schema.json` contract.
For multiple objectives, construct a result containing the complete configured
`objectives` map before ingesting. The
[Python-function example](../examples/toy-objectives/01_python_function/README.md)
and [subprocess example](../examples/toy-objectives/02_subprocess_cli/README.md)
show alternative evaluator boundaries.

Keep campaign files outside the reusable source templates. An evaluator may
use its own dependencies or remote execution; the default proxy controller
needs only Python's standard library. Keep result files until ingest succeeds.

## Choose parameters and define the measurement

Choose a small set of controllable settings that can plausibly change the
measurement. Record units, safe bounds, categorical choices and conditional
relationships in the [search-space contract](./search-space.md). Measured outputs
belong in the objective, not among the proposed settings. General templates
support `float`, `int`, `bool` and `categorical`; consult the
[Ax support matrix](./ax-support-matrix.md) before selecting that backend.

For the objective, define before running a campaign:

- **Measurement:** the computation, evaluation coverage and units used for every
  trial. A successful process exit alone need not mean the measurement is valid.
- **Direction:** `minimize` or `maximize` in `objective_schema.json`. Return the
  raw score in that convention; do not silently negate it in the adapter.
- **Tradeoffs:** one primary objective, or explicit secondary objectives and a
  scalarization/ordering policy. Keep the policy fixed during a comparison.
  See the [multi-objective example](./examples/multi_objective/README.md) and
  backend-specific limits; Ax does not provide all legacy scalarization modes.
- **Feasibility:** distinguish forbidden parameter combinations from measured
  outcome acceptance. [Constraints](./constraints.md) filter candidate settings;
  they do not automatically enforce project-specific outcome or promotion gates.
- **Noise:** record seeds and repeat policy, distinguish failed evaluation from
  a valid poor score, and reserve enough evaluation budget for comparisons.
  Compare against a fixed baseline or random search under matched budgets.

A finite score describes the observation; it does not certify a good result.
The evaluator owns domain validity and acceptance. The
[pilot checklist](./pilot-checklist.md) helps freeze these decisions.

## Results and failure handling

Every result must keep the suggested `trial_id` and exact `params` and include
all configured objective keys. Current statuses are `ok`, `failed`, `killed`
and `timeout`; legacy `success` is normalized by ingest.

| Outcome | Objective values | Additional handling |
| --- | --- | --- |
| Valid completed evaluation | Finite numeric values for every configured objective | Use `ok`, including valid poor scores |
| Failed, killed or timed-out evaluation | `null` for every configured objective | Use the matching status and an optional concise `terminal_reason` |
| Optional failure penalty | Finite `penalty_objective` on non-`ok` results only | Used for failure reporting; does not make failures eligible for `best` |

`best` is ranked from successful observations under the configured objective
policy. Do not encode infrastructure failures as apparently valid scores merely
to keep the loop moving. Distinguish retrying an evaluator from retrying ingest.

The generic harness preserves supplied parameters and supported reason text;
its default exception handling can include the exception class/message in the
result and stderr. Controller artifacts can retain supported metadata such as
artifact paths and heartbeat information. Normalization is not a project-specific
data filter. Construct your approved boundary explicitly and inspect both
returned payloads and persisted artifacts; see
[security and data handling](./security-data-handling.md).

## Retry and resume

If ingest fails, retain the completed result and compare it with the pending
trial and contract. Correct a malformed payload without rerunning a completed
expensive evaluation. Identical duplicate ingestion succeeds as a no-op;
conflicting replay or mismatched parameters is rejected.

After a restart, inspect `status` and pending work before allocating again.
Use [operational semantics](./operational-semantics.md) for exact state rules and
[the recovery playbook](./recovery-playbook.md) for interrupted or stale work.
With optional worker leases enabled, supply the matching CLI lease token;
see [batch/async examples](./examples/batch_async/README.md).

## Expand only when the basic loop works

| Need | Existing guide |
| --- | --- |
| Batched suggestions and worker handoff | [Batch/async](./examples/batch_async/README.md) |
| Queue, Slurm, Airflow, webhook or tracker sidecars | [Integration starter kit](./integration-starter-kit.md) |
| AWS Batch evaluator | [AWS Batch integration](./aws-batch-integration.md) |
| Local API/dashboard with optional auth and coordination | [Service API preview](./service-api-preview.md) |
| Import/export existing observations | [Warm-start examples](./examples/warm_start/README.md) |
| Native Ax installation and exact recovery/rebuild | [Ax installation](./ax-installation.md), [Ax backend](./ax-backend.md) |
| Inspect why a suggestion was selected | [Decision trace](./decision-trace.md) |
| CI persistence, repeat policy and safe concurrency | [CI knob tuning](./ci-knob-tuning.md) |

Keep canonical campaign mutation in the controller. Sidecars should consume the
appropriate outputs rather than inventing a second state writer. See the
[task map](./index.md) for specialist references and retained evidence.
