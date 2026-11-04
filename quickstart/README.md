# Quickstart

Run one trial with a fresh portable controller and a synthetic evaluator.
You need Python **3.11 or newer**, a shell with `mktemp`, and a Looptimum source
checkout. The default proxy backend uses the Python standard library; no
numerical packages or service installation are required.

The published wheel packages the preview service, not the controller templates
or a controller CLI. Use the complete portable source copy below. See
[installation routes](../docs/packages.md#installation-routes) for alternatives.

## Create and run a portable campaign

Start at the **repository root**, using the stock `templates/bo_client` template
and its default relative artifact paths. The first commands create an empty
temporary directory and copy the runtime, configuration, schemas and license.
The remaining commands run **inside that portable campaign**.

<!-- portable-quickstart:start -->
```bash
set -eu
LOOPTIMUM_CAMPAIGN="$(mktemp -d "${TMPDIR:-/tmp}/looptimum-quickstart.XXXXXX")"
python3 templates/_shared/vendor_copy.py templates/bo_client "$LOOPTIMUM_CAMPAIGN"
cp LICENSE "$LOOPTIMUM_CAMPAIGN/LICENSE"
cd "$LOOPTIMUM_CAMPAIGN"
python3 run_bo.py validate --project-root .
python3 run_bo.py status --project-root .
python3 run_bo.py suggest --project-root . --json-only > suggestion.json
python3 scripts/synthetic_experiment.py suggestion.json result.json
python3 run_bo.py ingest --project-root . --results-file result.json
python3 run_bo.py status --project-root .
```
<!-- portable-quickstart:end -->

The initial status has zero observations and zero pending trials. `suggest`
allocates a pending trial and writes its actual `trial_id` and `params` to
`suggestion.json`. The synthetic helper evaluates those settings and writes
the matching result to `result.json`; it does not reuse a bundled sample result.

Inspect the two files to see the boundary: the result keeps the same ID and
parameters and supplies a finite `loss` with `status: "ok"`. After ingest,
status reports one observation, zero pending trials, an advanced next trial ID,
and that successful trial as `best`. This proves the wiring, not an optimization
benefit on your workload. Coordinates and timestamps are not fixed expectations.

Keep the directory path to resume this campaign. For persistent work, use an
empty directory in your own project instead of temporary storage. Copying
`run_bo.py` alone, or pointing `--project-root` at an empty directory without
the rest of the bundle, does not create a usable campaign.

## Connect your evaluator

Replace the synthetic evaluation step with your own function, command or job.
Keep the suggested `trial_id` and `params` unchanged; return your configured
objective names and direction. The [integration guide](../docs/integration-guide.md)
explains the result contract, adapter and failure policy.

Public parameter types are `float`, `int`, `bool` and `categorical`. Conditional
parameters and backend-specific limits are explained in the
[search-space contract](../docs/search-space.md) and
[Ax support matrix](../docs/ax-support-matrix.md).

## Resume and inspect

Campaign history lives under the copied controller's `state/` directory.
For customized templates, the copy tool also omits configured runtime paths
and reset archives. Fresh copies require relative artifact paths contained
within the campaign and reject source symlinks or paths overlapping controller
code. Use archive restore to resume history; a fresh copy starts empty.
If ingest is interrupted, retain the completed result and retry ingestion;
identical replay is a no-op, while conflicting replay is rejected. Do not
rerun a completed evaluation just because its ingest needs retrying.
For a new trial, generate a new suggestion before evaluating again.

Use the [recovery playbook](../docs/recovery-playbook.md) for interruptions,
the [operational semantics](../docs/operational-semantics.md) for locking and
lifecycle rules, and the [quick reference](../docs/quick-reference.md) for
commands and artifact definitions. The generator omits named default histories;
it does not sanitize arbitrary customized campaign paths.

## Other paths

| Task | Guide |
| --- | --- |
| Compare templates or run the demo variant | [Templates](../templates/README.md) |
| Install optional native Ax | [Ax CPU installation](../docs/ax-installation.md), [backend semantics](../docs/ax-backend.md) |
| Tune a pipeline | [ETL walkthrough](./etl-pipeline-knob-tuning.md) |
| Use a local service | [Service API preview](../docs/service-api-preview.md) |
| Run batch or cluster evaluations | [Batch examples](../docs/examples/batch_async/README.md), [starter kit](../docs/integration-starter-kit.md) |
| Find another task | [Documentation map](../docs/index.md) |

Maintainer tests and release smoke procedures live in
[CONTRIBUTING](../CONTRIBUTING.md) and the [release guide](../docs/release-guide.md).
