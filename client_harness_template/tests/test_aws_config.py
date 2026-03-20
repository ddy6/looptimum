from __future__ import annotations

import importlib
import json
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
HARNESS_DIR = REPO_ROOT / "client_harness_template"
if str(HARNESS_DIR) not in sys.path:
    sys.path.insert(0, str(HARNESS_DIR))

aws_config = importlib.import_module("aws_config")


def _write_config(path: Path, *, include_job_queue: bool = True) -> None:
    payload = {
        "region": "us-east-1",
        "profile": None,
        "batch": {
            "job_definition": "looptimum-evaluator:1",
            "job_name_prefix": "looptimum-trial",
        },
        "s3": {
            "bucket": "client-looptimum-runs",
            "input_prefix": "inputs/",
            "output_prefix": "outputs/",
        },
        "timeouts": {
            "poll_interval_seconds": 5,
            "max_wait_seconds": 600,
        },
        "local": {
            "recovery_dir": "sidecars",
        },
    }
    if include_job_queue:
        payload["batch"]["job_queue"] = "looptimum-evals"
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def test_load_aws_batch_config_from_explicit_path(tmp_path: Path) -> None:
    config_path = tmp_path / "aws_config.json"
    _write_config(config_path)

    config = aws_config.load_aws_batch_config(config_path)

    assert config.region == "us-east-1"
    assert config.profile is None
    assert config.job_queue == "looptimum-evals"
    assert config.job_definition == "looptimum-evaluator:1"
    assert config.bucket == "client-looptimum-runs"
    assert config.input_prefix == "inputs/"
    assert config.output_prefix == "outputs/"
    assert config.poll_interval_seconds == 5.0
    assert config.max_wait_seconds == 600.0
    assert config.recovery_dir == (tmp_path / "sidecars").resolve()


def test_load_aws_batch_config_uses_env_path_when_arg_is_omitted(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config_path = tmp_path / "env_config.json"
    _write_config(config_path)
    monkeypatch.setenv(aws_config.AWS_CONFIG_ENV, str(config_path))

    resolved = aws_config.resolve_aws_config_path()
    config = aws_config.load_aws_batch_config()

    assert resolved == config_path.resolve()
    assert config.job_queue == "looptimum-evals"


def test_load_aws_batch_config_rejects_missing_required_fields(tmp_path: Path) -> None:
    config_path = tmp_path / "bad_config.json"
    _write_config(config_path, include_job_queue=False)

    with pytest.raises(ValueError, match="batch.job_queue"):
        aws_config.load_aws_batch_config(config_path)


def test_resolve_aws_config_path_requires_explicit_path_or_env(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv(aws_config.AWS_CONFIG_ENV, raising=False)

    with pytest.raises(ValueError, match="requires a config path"):
        aws_config.resolve_aws_config_path()
