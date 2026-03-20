# AWS Batch Integration

This page documents the optional `boto3`-backed AWS Batch executor path for
`client_harness_template/`.

## Scope

This executor path keeps Looptimum core unchanged:

- `run_bo.py` remains the local controller and canonical state owner
- `suggest -> evaluate -> ingest` stays the public loop
- AWS support lives in the evaluator boundary only
- AWS metadata stays in local sidecar artifacts, not canonical state/report files

This path is intentionally narrow: synchronous submit + poll + canonical ingest
for short-to-moderate jobs.

## Architecture

1. `run_bo.py suggest` writes the local pending trial as usual.
2. `client_harness_template/run_one_eval.py --executor aws-batch` builds a
   canonical eval request from that suggestion.
3. `client_harness_template/aws_executor.py` uploads the request to S3,
   submits one AWS Batch job, and writes a local recovery record immediately.
4. The Batch job reads the request from S3 and writes one canonical result JSON
   back to S3.
5. The AWS executor polls Batch until terminal state, downloads the result, and
   returns only canonical Looptimum fields:
   `status`, `objective`, `penalty_objective`, `terminal_reason`.
6. `run_one_eval.py` writes the normal ingest payload.
7. `run_bo.py ingest` proceeds unchanged.

## Files

- `client_harness_template/aws_config.py`: JSON config loader and validator
- `client_harness_template/aws_executor.py`: S3 upload, Batch submit/poll, and
  result download
- `client_harness_template/aws_models.py`: typed request/config/recovery models
- `client_harness_template/objective_aws_batch_example.py`: optional example
  objective wrapper
- `client_harness_template/aws_batch_config.example.json`: committed example
  config shape

## Config

Use a committed example plus a real user-local config loaded with
`LOOPTIMUM_AWS_CONFIG` or `--aws-config`.

Example:

```json
{
  "region": "us-east-1",
  "profile": null,
  "batch": {
    "job_queue": "looptimum-evals",
    "job_definition": "looptimum-evaluator:1",
    "job_name_prefix": "looptimum-trial"
  },
  "s3": {
    "bucket": "client-looptimum-runs",
    "input_prefix": "inputs/",
    "output_prefix": "outputs/"
  },
  "timeouts": {
    "poll_interval_seconds": 20,
    "max_wait_seconds": 14400
  },
  "local": {
    "recovery_dir": "aws_recovery"
  }
}
```

Config notes:

- credentials should use normal AWS / `boto3` resolution
- `profile` and `region` are optional overrides
- relative `local.recovery_dir` is resolved relative to the config file
- the example file is safe to commit; the real config should stay local

## Remote Request Contract

The executor uploads one canonical request JSON to:

- `s3://<bucket>/<input_prefix>/trial_<id>/request.json`

Request shape:

```json
{
  "trial_id": 7,
  "params": {
    "x1": 0.2,
    "x2": 0.7
  },
  "schema_version": "0.3.0",
  "suggested_at": 1738886400.0,
  "objective_name": "loss",
  "objective_direction": "minimize"
}
```

The request is intentionally small and compatible with the existing local-first
contract.

## Remote Result Contract

The Batch job must write one canonical JSON result to:

- `s3://<bucket>/<output_prefix>/trial_<id>/result.json`

Allowed fields:

- `status`
- `objective`
- `penalty_objective`
- `terminal_reason`

Example success payload:

```json
{
  "status": "ok",
  "objective": 0.1182
}
```

Example timeout payload:

```json
{
  "status": "timeout",
  "objective": null,
  "terminal_reason": "worker timeout"
}
```

Do not include AWS-specific metadata in this result object.

## Recovery Sidecars

AWS metadata is stored only in local sidecars under `local.recovery_dir`, for
example:

- `aws_recovery/trial_7/recovery_record.json`
- `aws_recovery/trial_7/input_request.json`
- `aws_recovery/trial_7/remote_result.json`

The recovery record is written immediately after submit and includes:

- `trial_id`
- `executor`
- `batch_job_id`
- `submitted_at`
- current local status
- input/output S3 URIs
- final canonical result once available

This lets interrupted polling resume without adding AWS internals to
`state/bo_state.json` or report surfaces.

## Status Mapping

AWS Batch outcomes map back to canonical Looptimum statuses:

| AWS condition | Looptimum status |
|---|---|
| Batch job succeeded and result payload is valid | `ok` |
| Batch job failed | `failed` |
| Polling deadline exceeded | `timeout` |
| Explicit cancel/user termination signal in Batch reason | `killed` |
| Missing or malformed remote result | `failed` |

`penalty_objective` remains optional; if omitted for non-`ok` results,
`run_one_eval.py` applies the normal direction-aware default.

## Stale Pending Guidance

This path is synchronous, so stale-pending policy must still be planned
explicitly.

Recommended options:

- keep AWS mode for short-to-moderate jobs that complete well inside your stale
  threshold
- raise `max_pending_age_seconds` for campaigns using this executor
- disable/avoid auto-stale retirement if the Batch runtime can exceed the
  normal threshold

Looptimum core does not learn AWS job liveness in this mode.

## IAM and Runtime Requirements

Minimum client-side permissions:

- `batch:SubmitJob`
- `batch:DescribeJobs`
- `s3:PutObject`
- `s3:GetObject`

Optional additional permissions:

- CloudWatch Logs read permissions if you decide to add log retrieval helpers

## Commands

Executor-selection path:

```bash
export LOOPTIMUM_AWS_CONFIG=/path/to/aws_batch_config.json
python3 client_harness_template/run_one_eval.py \
  /tmp/suggestion.json \
  /tmp/result.json \
  --executor aws-batch \
  --objective-schema templates/bo_client/objective_schema.json
```

Example objective-module path:

```bash
export LOOPTIMUM_AWS_CONFIG=/path/to/aws_batch_config.json
python3 client_harness_template/run_one_eval.py \
  /tmp/suggestion.json \
  /tmp/result.json \
  --objective-module client_harness_template/objective_aws_batch_example.py \
  --objective-schema templates/bo_client/objective_schema.json
```

Use the first command as the default path. The example objective module is for
teams that still want a custom evaluator wrapper.
