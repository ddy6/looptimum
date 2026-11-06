# Implement the evaluator adapter

First run the [portable quickstart](../quickstart/README.md) and define your
[evaluator/result boundary](../docs/integration-guide.md). This page explains
`run_one_eval.py`; the [harness README](./README.md) maps its companion files.

## Local objective module

Create an `objective.py` in your portable campaign, or use an existing module
with `evaluate(params)`. The repository's default `objective.py` deliberately
raises until implemented. A small working example for the stock `x1`/`x2`
space is:

```python
def evaluate(params):
    x1, x2 = float(params["x1"]), float(params["x2"])
    return (x1 - 0.25) ** 2 + (x2 - 0.75) ** 2
```

Replace the calculation with your real evaluation. The function may return a
finite number or `{"objective": 0.123, "status": "ok"}`. For failure, return a
mapping such as `{"status": "failed", "objective": None,
"terminal_reason": "evaluation incomplete"}`. Use Python `None` in code and
JSON `null` in serialized payloads.

Scalar callbacks populate only the primary objective. For a multi-objective
campaign, return a dictionary with the complete configured `objectives` map;
the adapter preserves it in the result. Any `objective` alias must match the
primary map entry. Non-`ok` results must set every objective to null.

`--objective-schema` reads the primary name/direction; the controller validates
the complete configured metric set at ingest. Contract-2 callbacks can also
provide measurements and SEMs; see [extended results](./README.md#extended-ax-results-v110)
and [Ax contract 2](../docs/ax-contract2.md). The
[multi-objective example](../docs/examples/multi_objective/README.md) covers
objective authoring and scalarization.

## Run one evaluation

Start at the repository root and set `LOOPTIMUM_CAMPAIGN` to the existing
portable directory from the quickstart. Create your module there first.
The following commands allocate a **new trial** in that campaign:

```bash
LOOPTIMUM_REPO="$(pwd)"
LOOPTIMUM_CAMPAIGN=/path/to/your/portable-campaign
python3 "$LOOPTIMUM_CAMPAIGN/run_bo.py" suggest \
  --project-root "$LOOPTIMUM_CAMPAIGN" --json-only > "$LOOPTIMUM_CAMPAIGN/suggestion.json"
python3 "$LOOPTIMUM_REPO/client_harness_template/run_one_eval.py" \
  "$LOOPTIMUM_CAMPAIGN/suggestion.json" "$LOOPTIMUM_CAMPAIGN/result.json" \
  --objective-module "$LOOPTIMUM_CAMPAIGN/objective.py" \
  --objective-schema "$LOOPTIMUM_CAMPAIGN/objective_schema.json"
python3 "$LOOPTIMUM_CAMPAIGN/run_bo.py" ingest \
  --project-root "$LOOPTIMUM_CAMPAIGN" --results-file "$LOOPTIMUM_CAMPAIGN/result.json"
python3 "$LOOPTIMUM_CAMPAIGN/run_bo.py" status --project-root "$LOOPTIMUM_CAMPAIGN"
```

The input is the actual suggestion JSON. The adapter also accepts legacy raw
`suggest` stdout with trailing text, but `--json-only` avoids that ambiguity.
Trial ID and parameter values pass through unchanged. Do not reuse a bundled
result from another trial.

## Objective and executor options

| Option | Meaning |
| --- | --- |
| `--objective-module PATH` | Python module exposing `evaluate(params)`; defaults to this directory's unimplemented stub |
| `--objective-schema PATH` | JSON `objective_schema.json`; reads primary name/direction |
| `--objective-name NAME`, `--objective-direction minimize` or `maximize` | Explicit objective selection when not reading its schema |
| `--executor local` | Default; call the objective module |
| `--executor aws-batch` | Use the AWS executor instead of the local module |
| `--aws-config PATH` | AWS JSON configuration; alternatively `LOOPTIMUM_AWS_CONFIG` |
| `--print-result` | Also print the serialized result |

Return raw scores in the configured direction: lower loss for `minimize`, higher
score for `maximize`. Do not silently invert values. For AWS configuration,
recovery sidecars and dependencies, follow
[AWS Batch integration](../docs/aws-batch-integration.md). No AWS setup is needed
for a local objective.

## Failures and data handling

Current statuses are `ok`, `failed`, `killed` and `timeout`. Successful objective
values must be finite; non-`ok` objective values must be null. An optional finite
`penalty_objective` may accompany a non-`ok` result, but failures are excluded
from best-trial ranking.

By default, `--on-exception failed` turns a raised exception into a failed result
and writes its class/message as `terminal_reason`, also printing it to stderr.
Use `--on-exception raise` to propagate exceptions instead. Default failure
penalties are `+1e12` for minimize and `-1e12` for maximize; override with
`--failure-penalty-objective`. The legacy `--failure-sentinel` alias remains
accepted with a deprecation warning.

The adapter validates result shape; it does not remove sensitive parameter
values or sanitize supplied failure reasons. Define your own approved payload
boundary and inspect saved JSON/logs before sharing them. See
[security and data handling](../docs/security-data-handling.md).

## Ingest retries and recovery

Keep completed result files until ingestion succeeds. Identical replay is a
no-op; conflicting replay or parameter mismatch is rejected. Retry ingest
using the same completed result rather than rerunning the evaluator. Check
pending work before new allocation after interruption.

Use the [quick reference](../docs/quick-reference.md) for the full payload/CLI
contract, [operational semantics](../docs/operational-semantics.md) for replay
and locking, and [recovery playbook](../docs/recovery-playbook.md) for incidents.
