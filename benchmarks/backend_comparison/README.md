# Optional backend comparison protocol

This evidence is separate from the existing golden `benchmarks/summary.json`
and `benchmarks/case_study.md`. Those assets and their original objective are
unchanged. The protocol below is declared before collecting reference data.
The runner never overwrites those golden outputs.

The first reference's [readout](readout.md), [generated table](report.md), and
[per-seed summary](summary.json) retain one failed direct-GP pipeline case.
That original reference's acceptance gate remains unmet; its failure is not
silently removed. The subsequent [GP-fix reference](gp_fix/readout.md)
completed all 200 campaigns and passed every gate. It validates the
[direct-GP fit recovery](../../docs/gp-fit-recovery.md), with recovery counts
recorded. The original failed summary/report are retained rather than patched
into a successful run.

## Reference design

- Five policies: random search, RBF proxy, direct BoTorch GP, Ax Sobol-only,
  and Ax with the `fast` model-guided strategy.
- Four synthetic workloads: smooth quadratic, multimodal Rastrigin, a mixed
  pipeline-latency simulation, and a genuinely noisy quadratic.
- Twelve sequential evaluations per campaign, four initialization trials,
  ten seeds: `17,29,41,53,67,79,97,113,131,149`.
- Two concurrent independent campaigns, one numerical thread per controller.
- Every policy uses a portable ordinary `bo_client` and actual
  `suggest -> evaluate -> ingest` commands, including worker leases.
  Each controller command starts a fresh process. OS caches are shared.
  All policies run in the same Python environment with the optional stack
  installed; lightweight policies still avoid importing that stack.
- Random search keeps the legacy controller in random warmup for the full
  budget. Proxy and GP share its first four random points. The direct GP is
  the seeded ordinary `surrogate.type: gp` path. Its candidate pool is 256,
  with the template's EI settings and Matérn-2.5 kernel.
- Ax Sobol-only sets its initialization budget to the full evaluation budget;
  it shares the first four Sobol points with model-guided Ax. These are
  comparisons of complete policies, including different initialization and
  acquisition choices. The experiment does not isolate a surrogate's causal
  effect. The runtime defaults are not changed.
- Record actual generation nodes/backends; unexpected fallbacks fail a case.
  No unsupported parameter constraints, outcome constraints, or SEM inputs
  are introduced for this experiment.

## Workloads and scoring

The smooth quadratic has minimum zero at `(0.32, 0.74)` on the unit square.
The multimodal function is Rastrigin on `[-5, 5]^2`, divided by 40, with
minimum zero at unit coordinates `(0.5, 0.5)`. The pipeline simulation varies
integer batch size/workers, Boolean caching, categorical compression, and
logarithmic buffer size; its known minimum is 10 simulated milliseconds.
See the [mixed pipeline example](../../examples/ax_pipeline_tuning/README.md).
None is production workload evidence.

The noisy quadratic adds independent Gaussian observation errors with
standard deviation `0.02 + 0.06*x1`. Draws depend on seed and evaluation
ordinal, not parameter values. Repeated evaluations receive fresh draws.
Backends share standardized draws at the same seed/ordinal (common random
numbers); restarting preserves them. Ax infers noise without supplied SEM.

**Primary quality metric:** latent regret of the configuration selected by
the lowest observed score at the fixed budget. The report also retains the
best observed score and best latent value encountered. The latter is an
oracle diagnostic, not the selection rule. This separates lucky negative
measurement errors from the underlying quality of the chosen configuration.
Report per-seed values, medians, Q25/Q75/IQR, and paired differences against
random search. Ten seeds give descriptive evidence; they do not establish
statistical significance or universal superiority.

Every allocated repeat or failed evaluation consumes an evaluation slot.
Operational command failures are retained as failed campaigns; failed cases
are never selectively retried or dropped. A cell missing any declared seed
has no aggregate quality result. These workloads do not inject evaluator
failures; failure/recovery correctness is additionally covered by tests.

## Resources and gates

Before collection, acceptance limits are:

- every declared case finishes exactly its evaluation budget;
- zero invalid committed suggestions and correct backend/phase identity;
- identical warmup configurations and observations within each paired policy
  family at each seed;
- each campaign's p95 suggestion wall time is at most 60 seconds;
- OS-reported peak process RSS is at most 4096 MiB;
- controller wall time is at most 10% of modeled campaign time when each
  evaluation costs 3600 seconds. This is an explicit expensive-evaluator
  cost model; the benchmark does not sleep or actually run one-hour jobs.

These gates check operational viability, not a required optimization win.
Report problem-dependent quality results and their uncertainty. Asynchronous
duplicate prevention is tested separately; this sequential benchmark cannot
establish it.

A fresh measurement supervisor runs each command and records wall time,
descendant CPU time, and `RUSAGE_CHILDREN` high-water RSS. On macOS RSS bytes
are converted to MiB; on Linux KiB are converted to MiB. The RSS statistic is
an OS largest-process high-water measure, **not the simultaneous sum of the
controller and worker**, and excludes the benchmark supervisor itself. It
does not establish aggregate host or GPU memory requirements. Timeouts kill
the command's process group. Raw command output and measurements are retained.

## Run and resume

Install the compatible Ax stack in the controller environment, then run from
the repository root:

```bash
python -m benchmarks.backend_comparison.run \
  --output-dir benchmarks/artifacts/backend_reference \
  --write-summary benchmarks/backend_comparison/summary.json \
  --write-report benchmarks/backend_comparison/report.md
```

This launches 200 campaigns and 2400 evaluations. It is a manual evidence run,
not a routine CI task. After an interruption, stop any remaining original
commands before resuming with the exact same command and `--resume`.
The runner locks its output directory and rejects source, environment, or
protocol changes. Finished campaigns and original command measurements are
reused. Pending evaluations retain their original draw and public trial ID.
If an interrupted command committed without its timing receipt, cost evidence
cannot be reconstructed from a replay: preserve it and use a fresh output
root. Failed campaign results remain recorded; changes require a new run.

For a small custom smoke test (explicitly labeled as non-reference evidence):

```bash
python -m benchmarks.backend_comparison.run \
  --output-dir /tmp/looptimum-backend-smoke \
  --budget 4 --initialization 2 --seeds 17 \
  --workloads smooth_quadratic --backends random,proxy --workers 1
```

To rebuild reports from finished case receipts without running optimization:

```bash
python -m benchmarks.backend_comparison.run \
  --output-dir benchmarks/artifacts/backend_reference --summarize-only \
  --write-summary benchmarks/backend_comparison/summary.json \
  --write-report benchmarks/backend_comparison/report.md
```

Compact summary/report artifacts can be committed. Raw portable campaigns,
command logs, checkpoints, and timings stay in the ignored artifacts directory.
The manifest records source hashes, environment versions, and the initial
Git commit; hashes identify working-tree code when evidence precedes its
engineering-slice commit. Never interpret an incomplete or custom smoke
report as the declared reference run.
The compact synthetic GP failure fixture is an explicit diagnostic exception
to the raw-trace exclusion policy. Published errors replace local path
prefixes; complete command diagnostics remain in raw receipts. Report-only
rerendering records its analysis source hashes separately from the original
execution protocol hashes and does not rerun evaluations.
