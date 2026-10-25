# Mixed pipeline tuning with Ax

This example runs a complete portable Looptimum campaign around an external
pipeline evaluator. It varies integer batch size and worker count, Boolean
caching, categorical compression, and a logarithmic buffer-size control.
The objective is **simulated latency**, not a measurement of a real ETL
system or compression library. The synthetic optimum is 10 ms at batch 64,
four workers, caching enabled, `lz4`, and a 64 MiB buffer.

From the repository root with the Ax extra installed:

```bash
python examples/ax_pipeline_tuning/run_pipeline_loop.py \
  --destination /tmp/looptimum-pipeline-example --steps 8 --initialization 3
```

Choose a new or empty destination. The first three evaluations initialize
Ax; later evaluations use model-guided generation. The directory contains
the portable controller, a standalone `evaluate_pipeline.py`, ordinary
suggestion/result JSON, worker leases, snapshots, decision logs, and reports.
The evaluator and ingest commands run with Python `-S`: only suggestion
generation needs the optional optimizer environment.

To adapt this to a real pipeline, replace the body of `evaluate()` in the
copied evaluator with the actual workload and return its measured latency.
Keep units, input types, and the objective contract consistent. Preserve
the suggestion's trial ID and lease token through external job submission;
deliver the result with `ingest --lease-token TOKEN`. The evaluator should
report failures explicitly rather than substitute an invented latency.

For interruptions, inspect `status` before dispatching more work. The
[Ax recovery contract](../../docs/ax-backend.md#state-and-recovery-boundaries)
covers incomplete publication, snapshot backups, and explicit rebuilds.
This small demonstration does not establish optimization efficiency. The
[separate comparison protocol](../../benchmarks/backend_comparison/README.md)
uses the same pipeline simulation to compare backends under fixed budgets.
