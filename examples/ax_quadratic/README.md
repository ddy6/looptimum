# Native Ax quadratic loop

This runnable example creates a portable controller in a new or empty
directory and evaluates a two-variable quadratic. Two initialization trials
are followed by real Ax/BoTorch model-guided suggestions. It is a lifecycle
demonstration, not comparative performance evidence.

From the repository root, with the Ax extra installed:

```bash
python -m pip install '.[ax]'
python examples/ax_quadratic/run_ax_loop.py --destination /tmp/looptimum-ax-example --steps 5
```

Choose a fresh destination for each run. The campaign directory contains
ordinary results, reports, decision logs, and the optimizer snapshots. To
inspect it without the Ax dependencies, use its `run_bo.py status`, `report`,
or `validate` command. Set a larger `max_trials` before requesting more trials;
the example sets the evaluation budget to `--steps`.

If exact snapshot restoration is unavailable, its controller also supports
`rebuild-optimizer --reason "Original optimizer snapshot unavailable"`.
Run it from the campaign directory with Ax installed. It preserves trial
records and pending leases, allocates no evaluations, saves recovery evidence,
and starts a new optimizer lineage. It does not reproduce the lost optimizer's
future suggestions. See the recovery contract below before using it.

See [Ax backend configuration and recovery boundaries](../../docs/ax-backend.md).
