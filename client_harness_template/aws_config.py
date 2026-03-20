from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from aws_models import AWSBatchConfig

AWS_CONFIG_ENV = "LOOPTIMUM_AWS_CONFIG"
DEFAULT_JOB_NAME_PREFIX = "looptimum-trial"
DEFAULT_POLL_INTERVAL_SECONDS = 20.0
DEFAULT_MAX_WAIT_SECONDS = 86400.0
DEFAULT_RECOVERY_DIR = "aws_recovery"


def _require_object(value: Any, *, field_name: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError(f"{field_name} must be an object")
    return value


def _require_non_empty_string(value: Any, *, field_name: str) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{field_name} must be a string")
    normalized = value.strip()
    if not normalized:
        raise ValueError(f"{field_name} must be non-empty")
    return normalized


def _optional_string(value: Any, *, field_name: str) -> str | None:
    if value is None:
        return None
    return _require_non_empty_string(value, field_name=field_name)


def _positive_float(value: Any, *, field_name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{field_name} must be numeric")
    normalized = float(value)
    if normalized <= 0.0:
        raise ValueError(f"{field_name} must be > 0")
    return normalized


def _normalize_s3_prefix(value: Any, *, field_name: str) -> str:
    raw = _require_non_empty_string(value, field_name=field_name)
    normalized = raw.strip("/")
    if not normalized:
        raise ValueError(f"{field_name} must contain at least one path segment")
    return f"{normalized}/"


def resolve_aws_config_path(path: str | Path | None = None) -> Path:
    raw = str(path) if path is not None else os.environ.get(AWS_CONFIG_ENV)
    if raw is None or not raw.strip():
        raise ValueError(
            f"AWS executor requires a config path. Provide --aws-config or set {AWS_CONFIG_ENV}."
        )
    resolved = Path(raw).expanduser().resolve()
    if not resolved.exists():
        raise ValueError(f"AWS config file not found: {resolved}")
    return resolved


def load_aws_batch_config(path: str | Path | None = None) -> AWSBatchConfig:
    config_path = resolve_aws_config_path(path)
    payload = json.loads(config_path.read_text(encoding="utf-8"))
    data = _require_object(payload, field_name="AWS config")

    batch = _require_object(data.get("batch"), field_name="batch")
    s3 = _require_object(data.get("s3"), field_name="s3")
    timeouts = _require_object(data.get("timeouts", {}), field_name="timeouts")
    local = _require_object(data.get("local", {}), field_name="local")

    recovery_dir_raw = local.get("recovery_dir", DEFAULT_RECOVERY_DIR)
    recovery_dir = Path(
        _require_non_empty_string(recovery_dir_raw, field_name="local.recovery_dir")
    )
    if not recovery_dir.is_absolute():
        recovery_dir = (config_path.parent / recovery_dir).resolve()

    return AWSBatchConfig(
        profile=_optional_string(data.get("profile"), field_name="profile"),
        region=_optional_string(data.get("region"), field_name="region"),
        job_queue=_require_non_empty_string(batch.get("job_queue"), field_name="batch.job_queue"),
        job_definition=_require_non_empty_string(
            batch.get("job_definition"), field_name="batch.job_definition"
        ),
        job_name_prefix=_require_non_empty_string(
            batch.get("job_name_prefix", DEFAULT_JOB_NAME_PREFIX),
            field_name="batch.job_name_prefix",
        ),
        bucket=_require_non_empty_string(s3.get("bucket"), field_name="s3.bucket"),
        input_prefix=_normalize_s3_prefix(s3.get("input_prefix"), field_name="s3.input_prefix"),
        output_prefix=_normalize_s3_prefix(s3.get("output_prefix"), field_name="s3.output_prefix"),
        poll_interval_seconds=_positive_float(
            timeouts.get("poll_interval_seconds", DEFAULT_POLL_INTERVAL_SECONDS),
            field_name="timeouts.poll_interval_seconds",
        ),
        max_wait_seconds=_positive_float(
            timeouts.get("max_wait_seconds", DEFAULT_MAX_WAIT_SECONDS),
            field_name="timeouts.max_wait_seconds",
        ),
        recovery_dir=recovery_dir,
    )
