# ETL Pipeline Knob-Tuning Quickstart

This scenario is the recommended mainstream starting path for Looptimum:
optimize ETL throughput/cost tradeoffs under noisy runtime behavior.

Use this when each batch run is expensive enough that you want better
sample-efficiency than manual parameter sweeps.

## Scenario Goal

Tune a small set of ETL runtime knobs:

- `batch_size`
- `worker_count`
- `retry_backoff_seconds`

Optimize one scalar objective (minimize):

`objective = cost_per_gb + latency_penalty + failure_penalty`

Where:

- `cost_per_gb`: cloud/runtime cost normalized per GB processed
- `latency_penalty`: penalty for missing throughput/SLA targets
- `failure_penalty`: large penalty for timeout/failed runs

## Why This Maps Well

- expensive black-box evaluations (real pipeline runs)
- noisy measurements across runner/network conditions
- clear objective scalarization and failure semantics
- strong operational need for resumability and traceability
- same outer-loop shape used in long-running training/evaluation jobs

## Run Sequence (Canonical)

From repository root:

```bash
python3 templates/bo_client/run_bo.py suggest --project-root templates/bo_client --json-only > /tmp/suggestion.json
python3 client_harness_template/run_one_eval.py \
  /tmp/suggestion.json \
  /tmp/result.json \
  --objective-module client_harness_template/objective.py \
  --objective-name loss
python3 templates/bo_client/run_bo.py ingest --project-root templates/bo_client --results-file /tmp/result.json
python3 templates/bo_client/run_bo.py status --project-root templates/bo_client --json
```

Repeat until trial budget is reached.

## Evaluator Mapping Template

Your evaluator should:

1. read `params` from suggestion (`batch_size`, `worker_count`,
   `retry_backoff_seconds`)
2. execute one ETL run with those settings
3. compute scalar objective from measured metrics
4. emit non-`ok` statuses (`failed`/`timeout`/`killed`) with
   `objective: null` and optional `penalty_objective`

Contract details:

- [`docs/quick-reference.md`](../docs/quick-reference.md)
- [`docs/integration-guide.md`](../docs/integration-guide.md)

## Noise and Robustness Defaults

Recommended for ETL-like noisy metrics:

- keep cold-run measurement as default mode
- aggregate repeated top candidates with median-of-repeats
- preserve one controller/writer per `state/` path in CI

Operational policy references:

- [`docs/ci-knob-tuning.md`](../docs/ci-knob-tuning.md)
- [`docs/recovery-playbook.md`](../docs/recovery-playbook.md)

## Evidence and Audit Trail

For trust and postmortem readiness, rely on:

- `state/bo_state.json` (authoritative run state)
- `state/observations.csv` (result history)
- `state/acquisition_log.jsonl` (suggestion decision trace)
- `state/event_log.jsonl` (ops/lifecycle trace)
- `state/trials/trial_<id>/manifest.json` (per-trial artifact/metadata)

## Next References

- general quickstart commands: [`quickstart/README.md`](./README.md)
- algorithm behavior and failure modes:
  [`docs/how-it-works.md`](../docs/how-it-works.md)
- stability and compatibility policy:
  [`docs/stability-guarantees.md`](../docs/stability-guarantees.md)
