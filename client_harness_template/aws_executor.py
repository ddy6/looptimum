from __future__ import annotations

import importlib
import json
import math
import re
import time
from pathlib import Path
from typing import Any, cast

from aws_models import (
    AWSBatchConfig,
    AWSRecoveryRecord,
    CanonicalEvalRequest,
    CanonicalEvalResult,
    CanonicalStatus,
)

_RESULT_KEYS = {"status", "objective", "penalty_objective", "terminal_reason"}
_CANONICAL_STATUSES = {"ok", "failed", "killed", "timeout"}
_TERMINAL_RECORD_STATUSES = {"succeeded", "failed", "killed", "timeout"}
_RUNNING_AWS_STATUSES = {"SUBMITTED", "PENDING", "RUNNABLE", "STARTING", "RUNNING"}
_JOB_NAME_CHARS = re.compile(r"[^A-Za-z0-9_-]+")


def build_aws_session(profile: str | None, region: str | None) -> Any:
    try:
        boto3 = importlib.import_module("boto3")
    except ModuleNotFoundError as exc:
        raise ModuleNotFoundError(
            'AWS executor requires boto3. Install with `pip install ".[aws]"` or '
            '`pip install "looptimum[aws]"`.'
        ) from exc

    kwargs: dict[str, Any] = {}
    if profile is not None:
        kwargs["profile_name"] = profile
    if region is not None:
        kwargs["region_name"] = region
    return boto3.Session(**kwargs)


def _trial_dir(config: AWSBatchConfig, trial_id: int) -> Path:
    return config.recovery_dir / f"trial_{int(trial_id)}"


def _request_sidecar_path(config: AWSBatchConfig, trial_id: int) -> Path:
    return _trial_dir(config, trial_id) / "input_request.json"


def _remote_result_sidecar_path(config: AWSBatchConfig, trial_id: int) -> Path:
    return _trial_dir(config, trial_id) / "remote_result.json"


def _recovery_record_path(config: AWSBatchConfig, trial_id: int) -> Path:
    return _trial_dir(config, trial_id) / "recovery_record.json"


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.tmp-{time.time_ns()}")
    tmp.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    tmp.replace(path)


def _load_json_dict(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"Expected JSON object in {path}")
    return data


def _save_recovery_record(config: AWSBatchConfig, record: AWSRecoveryRecord) -> None:
    _write_json(_recovery_record_path(config, record.trial_id), record.to_payload())


def _load_recovery_record(config: AWSBatchConfig, trial_id: int) -> AWSRecoveryRecord | None:
    path = _recovery_record_path(config, trial_id)
    if not path.exists():
        return None
    return AWSRecoveryRecord.from_payload(_load_json_dict(path))


def _s3_uri(bucket: str, key: str) -> str:
    return f"s3://{bucket}/{key}"


def _parse_s3_uri(uri: str) -> tuple[str, str]:
    if not uri.startswith("s3://"):
        raise ValueError(f"Expected s3:// URI, got: {uri!r}")
    without_scheme = uri[len("s3://") :]
    bucket, sep, key = without_scheme.partition("/")
    if not bucket or not sep or not key:
        raise ValueError(f"Expected bucket and key in S3 URI: {uri!r}")
    return bucket, key


def _require_finite_number(value: Any, *, field_name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{field_name} must be a finite number")
    normalized = float(value)
    if not math.isfinite(normalized):
        raise ValueError(f"{field_name} must be a finite number")
    return normalized


def _normalize_canonical_status(raw_status: Any) -> CanonicalStatus:
    if not isinstance(raw_status, str):
        raise ValueError("status must be a string")
    status = raw_status.strip().lower()
    if status not in _CANONICAL_STATUSES:
        raise ValueError(f"status must be one of {sorted(_CANONICAL_STATUSES)}")
    return cast(CanonicalStatus, status)


def _normalize_remote_result(payload: dict[str, Any]) -> CanonicalEvalResult:
    extras = sorted(set(payload.keys()) - _RESULT_KEYS)
    if extras:
        raise ValueError(f"Unexpected keys in remote result payload: {extras}")

    status = _normalize_canonical_status(payload.get("status", "ok"))

    raw_terminal_reason = payload.get("terminal_reason")
    terminal_reason: str | None = None
    if raw_terminal_reason is not None:
        if not isinstance(raw_terminal_reason, str):
            raise ValueError("terminal_reason must be a string when provided")
        terminal_reason = raw_terminal_reason.strip() or None

    result: CanonicalEvalResult = {"status": status}
    if status == "ok":
        if payload.get("penalty_objective") is not None:
            raise ValueError("penalty_objective is only valid for non-ok statuses")
        result["objective"] = _require_finite_number(
            payload.get("objective"), field_name="objective"
        )
        return result

    if payload.get("objective") is not None:
        raise ValueError("objective must be null/omitted for non-ok statuses")
    result["objective"] = None
    if payload.get("penalty_objective") is not None:
        result["penalty_objective"] = _require_finite_number(
            payload.get("penalty_objective"),
            field_name="penalty_objective",
        )
    if terminal_reason is not None:
        result["terminal_reason"] = terminal_reason
    return result


def _job_name(prefix: str, trial_id: int) -> str:
    sanitized_prefix = _JOB_NAME_CHARS.sub("-", prefix).strip("-") or "looptimum-trial"
    candidate = f"{sanitized_prefix}-trial-{int(trial_id)}"
    return candidate[:128]


def upload_trial_input(
    s3_client: Any, request: CanonicalEvalRequest, config: AWSBatchConfig
) -> str:
    payload = request.to_payload()
    _write_json(_request_sidecar_path(config, request.trial_id), payload)
    key = config.input_key(request.trial_id)
    s3_client.put_object(
        Bucket=config.bucket,
        Key=key,
        Body=(json.dumps(payload, indent=2, sort_keys=True) + "\n").encode("utf-8"),
        ContentType="application/json",
    )
    return _s3_uri(config.bucket, key)


def submit_batch_job(
    batch_client: Any,
    request: CanonicalEvalRequest,
    config: AWSBatchConfig,
    *,
    input_s3_uri: str,
    output_s3_uri: str,
) -> tuple[str, str]:
    environment = [
        {"name": "LOOPTIMUM_TRIAL_ID", "value": str(int(request.trial_id))},
        {"name": "LOOPTIMUM_INPUT_S3_URI", "value": input_s3_uri},
        {"name": "LOOPTIMUM_OUTPUT_S3_URI", "value": output_s3_uri},
    ]
    if request.schema_version is not None:
        environment.append({"name": "LOOPTIMUM_SCHEMA_VERSION", "value": request.schema_version})
    if request.objective_name is not None:
        environment.append({"name": "LOOPTIMUM_OBJECTIVE_NAME", "value": request.objective_name})
    if request.objective_direction is not None:
        environment.append(
            {"name": "LOOPTIMUM_OBJECTIVE_DIRECTION", "value": request.objective_direction}
        )

    job_name = _job_name(config.job_name_prefix, request.trial_id)
    response = batch_client.submit_job(
        jobName=job_name,
        jobQueue=config.job_queue,
        jobDefinition=config.job_definition,
        containerOverrides={"environment": environment},
    )
    raw_job_id = response.get("jobId")
    if not isinstance(raw_job_id, str) or not raw_job_id.strip():
        raise ValueError("AWS Batch submit_job response missing jobId")
    return raw_job_id, job_name


def _terminal_result(status: CanonicalStatus, reason: str) -> CanonicalEvalResult:
    return {
        "status": status,
        "objective": None,
        "terminal_reason": reason,
    }


def _finalize_record(
    config: AWSBatchConfig,
    record: AWSRecoveryRecord,
    *,
    status: str,
    aws_status: str | None,
    canonical_result: CanonicalEvalResult,
    terminal_reason: str | None,
) -> CanonicalEvalResult:
    record.status = status
    record.aws_status = aws_status
    record.completed_at = time.time()
    record.terminal_reason = terminal_reason
    record.canonical_result = canonical_result
    _save_recovery_record(config, record)
    return canonical_result


def _describe_job(batch_client: Any, job_id: str) -> dict[str, Any]:
    response = batch_client.describe_jobs(jobs=[job_id])
    jobs = response.get("jobs")
    if not isinstance(jobs, list) or not jobs:
        raise ValueError(f"AWS Batch describe_jobs returned no record for job_id={job_id}")
    job = jobs[0]
    if not isinstance(job, dict):
        raise ValueError(
            f"AWS Batch describe_jobs returned invalid job payload for job_id={job_id}"
        )
    return job


def _map_failed_job(job: dict[str, Any]) -> CanonicalEvalResult:
    reason = str(job.get("statusReason") or job.get("reason") or "AWS Batch job failed").strip()
    lowered = reason.lower()
    status: CanonicalStatus = (
        "killed" if "cancel" in lowered or "terminated by the user" in lowered else "failed"
    )
    return _terminal_result(status, f"AWS Batch failure: {reason}")


def wait_for_batch_job(
    batch_client: Any, record: AWSRecoveryRecord, config: AWSBatchConfig
) -> tuple[dict[str, Any] | None, CanonicalEvalResult | None]:
    while True:
        now = time.time()
        record.last_checked_at = now
        if now - record.submitted_at > config.max_wait_seconds:
            timeout_result = _terminal_result(
                "timeout",
                f"AWS Batch polling exceeded max_wait_seconds={config.max_wait_seconds:g}",
            )
            _finalize_record(
                config,
                record,
                status="timeout",
                aws_status=record.aws_status,
                canonical_result=timeout_result,
                terminal_reason=timeout_result["terminal_reason"],
            )
            return None, timeout_result

        job = _describe_job(batch_client, record.batch_job_id)
        aws_status = str(job.get("status", "")).upper()
        record.aws_status = aws_status

        if aws_status == "SUCCEEDED":
            record.status = "succeeded"
            _save_recovery_record(config, record)
            return job, None
        if aws_status == "FAILED":
            failed_result = _map_failed_job(job)
            _finalize_record(
                config,
                record,
                status=failed_result["status"],
                aws_status=aws_status,
                canonical_result=failed_result,
                terminal_reason=failed_result["terminal_reason"],
            )
            return None, failed_result

        if aws_status not in _RUNNING_AWS_STATUSES:
            unexpected = _terminal_result(
                "failed", f"Unexpected AWS Batch status: {aws_status or '<missing>'}"
            )
            _finalize_record(
                config,
                record,
                status="failed",
                aws_status=aws_status or None,
                canonical_result=unexpected,
                terminal_reason=unexpected["terminal_reason"],
            )
            return None, unexpected

        record.status = "running"
        _save_recovery_record(config, record)
        time.sleep(config.poll_interval_seconds)


def download_trial_result(
    s3_client: Any, *, output_s3_uri: str, local_sidecar_path: Path
) -> CanonicalEvalResult:
    bucket, key = _parse_s3_uri(output_s3_uri)
    response = s3_client.get_object(Bucket=bucket, Key=key)
    body = response.get("Body")
    if body is None or not hasattr(body, "read"):
        raise ValueError(f"S3 get_object missing readable Body for {output_s3_uri}")
    raw = body.read()
    if isinstance(raw, bytes):
        text = raw.decode("utf-8")
    elif isinstance(raw, str):
        text = raw
    else:
        raise ValueError(f"Unexpected S3 body type for {output_s3_uri}: {type(raw).__name__}")

    payload = json.loads(text)
    if not isinstance(payload, dict):
        raise ValueError(f"Remote result at {output_s3_uri} must be a JSON object")
    _write_json(local_sidecar_path, payload)
    return _normalize_remote_result(payload)


def evaluate_via_batch(
    request: CanonicalEvalRequest, *, config: AWSBatchConfig
) -> CanonicalEvalResult:
    existing = _load_recovery_record(config, request.trial_id)
    if existing is not None and existing.canonical_result is not None:
        return cast(CanonicalEvalResult, dict(existing.canonical_result))

    session = build_aws_session(config.profile, config.region)
    s3_client = session.client("s3")
    batch_client = session.client("batch")

    output_s3_uri = _s3_uri(config.bucket, config.output_key(request.trial_id))

    if existing is None:
        input_s3_uri = upload_trial_input(s3_client, request, config)
        batch_job_id, job_name = submit_batch_job(
            batch_client,
            request,
            config,
            input_s3_uri=input_s3_uri,
            output_s3_uri=output_s3_uri,
        )
        record = AWSRecoveryRecord(
            trial_id=request.trial_id,
            executor="aws-batch",
            batch_job_id=batch_job_id,
            job_name=job_name,
            submitted_at=time.time(),
            status="submitted",
            input_s3_uri=input_s3_uri,
            output_s3_uri=output_s3_uri,
        )
        _save_recovery_record(config, record)
    else:
        record = existing
        if record.status in _TERMINAL_RECORD_STATUSES and record.canonical_result is not None:
            return cast(CanonicalEvalResult, dict(record.canonical_result))

    if record.status == "succeeded":
        try:
            result = download_trial_result(
                s3_client,
                output_s3_uri=record.output_s3_uri,
                local_sidecar_path=_remote_result_sidecar_path(config, request.trial_id),
            )
        except Exception as exc:
            failed_result = _terminal_result(
                "failed",
                f"Failed to load remote result from {record.output_s3_uri}: {exc}",
            )
            return _finalize_record(
                config,
                record,
                status="failed",
                aws_status=record.aws_status,
                canonical_result=failed_result,
                terminal_reason=failed_result["terminal_reason"],
            )
        return _finalize_record(
            config,
            record,
            status="succeeded",
            aws_status=record.aws_status,
            canonical_result=result,
            terminal_reason=result.get("terminal_reason"),
        )

    _, terminal_result = wait_for_batch_job(batch_client, record, config)
    if terminal_result is not None:
        return terminal_result

    try:
        result = download_trial_result(
            s3_client,
            output_s3_uri=record.output_s3_uri,
            local_sidecar_path=_remote_result_sidecar_path(config, request.trial_id),
        )
    except Exception as exc:
        failed_result = _terminal_result(
            "failed",
            f"Failed to load remote result from {record.output_s3_uri}: {exc}",
        )
        return _finalize_record(
            config,
            record,
            status="failed",
            aws_status=record.aws_status,
            canonical_result=failed_result,
            terminal_reason=failed_result["terminal_reason"],
        )

    return _finalize_record(
        config,
        record,
        status="succeeded",
        aws_status=record.aws_status,
        canonical_result=result,
        terminal_reason=result.get("terminal_reason"),
    )
