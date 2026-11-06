# Examples

Runnable integration examples and pointers to retained case studies.

Purpose:

- show how to connect external evaluators to the optimization templates
- demonstrate common integration patterns (Python function, CLI/subprocess, etc.)
- provide small runnable references before moving to domain-specific examples

## Lightweight evaluator wiring

- [Python and subprocess adapters](toy-objectives/README.md): two toy examples
  covering different integration patterns
- [Tiny quadratic loop](toy_objectives/03_tiny_quadratic_loop/README.md): end-to-end
  example (`suggest -> evaluate -> ingest -> status` in under one minute)

## Optional native Ax

Use the [pinned CPU environment](../docs/ax-installation.md) for these examples:

- [Quadratic loop](ax_quadratic/README.md): initialization, model-guided
  generation and optimizer snapshots
- [Mixed pipeline tuning](ax_pipeline_tuning/README.md): an external evaluator,
  mixed parameters, leases and dependency-light result delivery
- [Contract-2 walkthroughs](ax_capabilities/README.md): measurement errors,
  typed conditional trees, measured constraints and vector Pareto acquisition

## Case studies and reference artifacts

- [Mesh-control example](snappyhexmesh_campaign/README.md) and its
  [retained validation evidence](../docs/examples/snappyhexmesh_campaign/README.md)
- [GPT training case study](../docs/examples/gpt_training_campaign/README.md)
- [Documentation examples](../docs/examples/README.md): sample payloads,
  state snapshots, batch/async, warm-start and preview artifacts

Wiring examples demonstrate interface use. Case studies and
[benchmarks](../benchmarks/README.md) retain their own conditions, measurements
and limitations; none establishes performance on another workload.
