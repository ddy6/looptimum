# Ax contract-2 walkthroughs (v1.1.0)

These synthetic walkthroughs create fresh portable campaigns and require the
[pinned CPU controller environment](../../docs/ax-installation.md). They use no
external data. Each runs four evaluation slots in each of two paired arms,
including two initialization slots, then checks modeled generation and a seeded
restore. Destinations must be fresh. Run from the repository root:

```bash
python examples/ax_capabilities/run_walkthrough.py --destination /tmp/ax-noise \
  --workload noisy_scalar
python examples/ax_capabilities/run_walkthrough.py --destination /tmp/ax-tree \
  --workload typed_conditional
python examples/ax_capabilities/run_walkthrough.py --destination /tmp/ax-measured \
  --workload measured_scalar
python examples/ax_capabilities/run_walkthrough.py --destination /tmp/ax-pareto \
  --workload pareto_tradeoff
```

The noise example compares known versus unknown SEM; it pairs standardized
noise draws and retains simulator truth outside model inputs. The tree example
preserves categorical JSON types, omits inactive leaves, and enforces raw
integer/float linear rules plus a forbidden pair.

The measured example keeps evaluator success separate from resource feasibility:
an infeasible successful result remains model data. The Pareto example configures
actual vector acquisition with minimize/maximize directions and a fixed reference,
while preserving the legacy scalar best as a labeled summary. Inspect generated
`controller/objective_schema.json`, `state/bo_state.json`, acquisition logs and
the benchmark's raw measurement/restore receipts.

See [contract semantics](../../docs/ax-contract2.md) and the
[bounded benchmark protocol](../../benchmarks/ax_capabilities/README.md).
These short walkthroughs establish correctness behavior; they do not establish
superiority or replace the full 40-campaign/960-slot evidence matrix.
