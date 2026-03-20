from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
RUN_ONE_EVAL = REPO_ROOT / "client_harness_template" / "run_one_eval.py"


def _run_cmd(
    *args: str, expect_ok: bool = True, env: dict[str, str] | None = None
) -> subprocess.CompletedProcess[str]:
    run_env = dict(os.environ)
    if env:
        run_env.update(env)
    out = subprocess.run(
        [sys.executable, str(RUN_ONE_EVAL), *args],
        capture_output=True,
        text=True,
        env=run_env,
    )
    if expect_ok and out.returncode != 0:
        raise AssertionError(
            f"Command failed: {' '.join(args)}\nSTDOUT:\n{out.stdout}\nSTDERR:\n{out.stderr}"
        )
    return out


def _write_suggestion(path: Path) -> None:
    payload = {
        "trial_id": 1,
        "params": {"x1": 0.2, "x2": 0.7},
        "suggested_at": 1738886400.0,
    }
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def _write_raising_objective(path: Path) -> None:
    path.write_text(
        "def evaluate(params):\n    raise RuntimeError('synthetic failure')\n",
        encoding="utf-8",
    )


def _write_ok_objective(path: Path) -> None:
    path.write_text(
        "def evaluate(params):\n    return 0.123\n",
        encoding="utf-8",
    )


def _write_trial_id_objective(path: Path) -> None:
    path.write_text(
        "import os\ndef evaluate(params):\n    return float(os.environ['LOOPTIMUM_TRIAL_ID'])\n",
        encoding="utf-8",
    )


def _write_non_ok_with_failure_reason_objective(path: Path) -> None:
    path.write_text(
        "def evaluate(params):\n"
        "    return {\n"
        "        'status': 'failed',\n"
        "        'objective': None,\n"
        "        'failure_reason': 'solver diverged',\n"
        "    }\n",
        encoding="utf-8",
    )


def _write_non_ok_without_reason_objective(path: Path) -> None:
    path.write_text(
        "def evaluate(params):\n"
        "    return {\n"
        "        'status': 'timeout',\n"
        "        'objective': None,\n"
        "        'penalty_objective': 321.0,\n"
        "    }\n",
        encoding="utf-8",
    )


def _write_objective_schema(path: Path, *, name: str, direction: str) -> None:
    payload = {
        "primary_objective": {
            "name": name,
            "direction": direction,
            "tolerance": 0.0,
            "failure_handling": "record_and_continue",
        },
        "secondary_objectives": [],
    }
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def _write_aws_config(path: Path) -> None:
    payload = {
        "region": "us-east-1",
        "profile": None,
        "batch": {
            "job_queue": "looptimum-evals",
            "job_definition": "looptimum-evaluator:1",
            "job_name_prefix": "looptimum-trial",
        },
        "s3": {
            "bucket": "client-looptimum-runs",
            "input_prefix": "inputs/",
            "output_prefix": "outputs/",
        },
        "timeouts": {
            "poll_interval_seconds": 1,
            "max_wait_seconds": 300,
        },
        "local": {
            "recovery_dir": "aws_recovery",
        },
    }
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def _write_fake_boto3_module(path: Path) -> None:
    path.write_text(
        "import io\n"
        "import json\n"
        "_STORE = {}\n"
        "def _parse_s3_uri(uri):\n"
        "    without_scheme = uri[len('s3://'):]\n"
        "    bucket, _, key = without_scheme.partition('/')\n"
        "    return bucket, key\n"
        "class Session:\n"
        "    def __init__(self, profile_name=None, region_name=None):\n"
        "        self.profile_name = profile_name\n"
        "        self.region_name = region_name\n"
        "    def client(self, service_name):\n"
        "        if service_name == 's3':\n"
        "            return _S3Client()\n"
        "        if service_name == 'batch':\n"
        "            return _BatchClient()\n"
        "        raise ValueError(service_name)\n"
        "class _S3Client:\n"
        "    def put_object(self, *, Bucket, Key, Body, ContentType):\n"
        "        if isinstance(Body, bytes):\n"
        "            Body = Body.decode('utf-8')\n"
        "        _STORE[(Bucket, Key)] = Body\n"
        "        return {}\n"
        "    def get_object(self, *, Bucket, Key):\n"
        "        return {'Body': io.BytesIO(_STORE[(Bucket, Key)].encode('utf-8'))}\n"
        "class _BatchClient:\n"
        "    def submit_job(self, *, jobName, jobQueue, jobDefinition, containerOverrides):\n"
        "        env = {entry['name']: entry['value'] for entry in containerOverrides['environment']}\n"
        "        bucket, key = _parse_s3_uri(env['LOOPTIMUM_OUTPUT_S3_URI'])\n"
        "        _STORE[(bucket, key)] = json.dumps({'status': 'ok', 'objective': 0.456})\n"
        "        return {'jobId': 'job-123', 'jobName': jobName}\n"
        "    def describe_jobs(self, *, jobs):\n"
        "        return {'jobs': [{'jobId': jobs[0], 'status': 'SUCCEEDED'}]}\n",
        encoding="utf-8",
    )


def test_failed_payload_default_penalty_for_minimize(tmp_path: Path) -> None:
    suggestion = tmp_path / "suggestion.json"
    objective = tmp_path / "objective_raise.py"
    result = tmp_path / "result.json"
    _write_suggestion(suggestion)
    _write_raising_objective(objective)

    _run_cmd(str(suggestion), str(result), "--objective-module", str(objective))
    payload = json.loads(result.read_text(encoding="utf-8"))
    assert payload["status"] == "failed"
    assert payload["objectives"]["loss"] is None
    assert payload["penalty_objective"] == 1.0e12
    assert payload["terminal_reason"] == "RuntimeError: synthetic failure"


def test_failed_payload_default_penalty_for_maximize(tmp_path: Path) -> None:
    suggestion = tmp_path / "suggestion.json"
    objective = tmp_path / "objective_raise.py"
    result = tmp_path / "result.json"
    _write_suggestion(suggestion)
    _write_raising_objective(objective)

    _run_cmd(
        str(suggestion),
        str(result),
        "--objective-module",
        str(objective),
        "--objective-direction",
        "maximize",
    )
    payload = json.loads(result.read_text(encoding="utf-8"))
    assert payload["status"] == "failed"
    assert payload["objectives"]["loss"] is None
    assert payload["penalty_objective"] == -1.0e12
    assert payload["terminal_reason"] == "RuntimeError: synthetic failure"


def test_objective_schema_drives_name_and_direction_defaults(tmp_path: Path) -> None:
    suggestion = tmp_path / "suggestion.json"
    objective = tmp_path / "objective_raise.py"
    schema = tmp_path / "objective_schema.json"
    result = tmp_path / "result.json"
    _write_suggestion(suggestion)
    _write_raising_objective(objective)
    _write_objective_schema(schema, name="score", direction="maximize")

    _run_cmd(
        str(suggestion),
        str(result),
        "--objective-module",
        str(objective),
        "--objective-schema",
        str(schema),
    )
    payload = json.loads(result.read_text(encoding="utf-8"))
    assert payload["status"] == "failed"
    assert payload["objectives"]["score"] is None
    assert payload["penalty_objective"] == -1.0e12
    assert payload["terminal_reason"] == "RuntimeError: synthetic failure"


def test_explicit_failure_penalty_overrides_direction_default(tmp_path: Path) -> None:
    suggestion = tmp_path / "suggestion.json"
    objective = tmp_path / "objective_raise.py"
    result = tmp_path / "result.json"
    _write_suggestion(suggestion)
    _write_raising_objective(objective)

    _run_cmd(
        str(suggestion),
        str(result),
        "--objective-module",
        str(objective),
        "--objective-direction",
        "maximize",
        "--failure-penalty-objective",
        "-123.0",
    )
    payload = json.loads(result.read_text(encoding="utf-8"))
    assert payload["status"] == "failed"
    assert payload["objectives"]["loss"] is None
    assert payload["penalty_objective"] == -123.0
    assert payload["terminal_reason"] == "RuntimeError: synthetic failure"


def test_legacy_failure_sentinel_flag_still_works_with_warning(tmp_path: Path) -> None:
    suggestion = tmp_path / "suggestion.json"
    objective = tmp_path / "objective_raise.py"
    result = tmp_path / "result.json"
    _write_suggestion(suggestion)
    _write_raising_objective(objective)

    out = _run_cmd(
        str(suggestion),
        str(result),
        "--objective-module",
        str(objective),
        "--failure-sentinel",
        "777.0",
    )

    payload = json.loads(result.read_text(encoding="utf-8"))
    assert payload["status"] == "failed"
    assert payload["objectives"]["loss"] is None
    assert payload["penalty_objective"] == 777.0
    assert payload["terminal_reason"] == "RuntimeError: synthetic failure"
    assert "Deprecated flag '--failure-sentinel'" in out.stderr


def test_non_ok_output_maps_failure_reason_alias_to_terminal_reason(tmp_path: Path) -> None:
    suggestion = tmp_path / "suggestion.json"
    objective = tmp_path / "objective_failure_reason.py"
    result = tmp_path / "result.json"
    _write_suggestion(suggestion)
    _write_non_ok_with_failure_reason_objective(objective)

    out = _run_cmd(str(suggestion), str(result), "--objective-module", str(objective))
    payload = json.loads(result.read_text(encoding="utf-8"))
    assert payload["status"] == "failed"
    assert payload["objectives"]["loss"] is None
    assert payload["penalty_objective"] == 1.0e12
    assert payload["terminal_reason"] == "solver diverged"
    assert "failure_reason" not in payload
    assert "Deprecated objective output field 'failure_reason' used" in out.stderr


def test_non_ok_output_without_reason_uses_status_fallback(tmp_path: Path) -> None:
    suggestion = tmp_path / "suggestion.json"
    objective = tmp_path / "objective_non_ok_no_reason.py"
    result = tmp_path / "result.json"
    _write_suggestion(suggestion)
    _write_non_ok_without_reason_objective(objective)

    _run_cmd(str(suggestion), str(result), "--objective-module", str(objective))
    payload = json.loads(result.read_text(encoding="utf-8"))
    assert payload["status"] == "timeout"
    assert payload["objectives"]["loss"] is None
    assert payload["penalty_objective"] == 321.0
    assert payload["terminal_reason"] == "status=timeout"


def test_objective_schema_name_applies_on_successful_eval(tmp_path: Path) -> None:
    suggestion = tmp_path / "suggestion.json"
    objective = tmp_path / "objective_ok.py"
    schema = tmp_path / "objective_schema.json"
    result = tmp_path / "result.json"
    _write_suggestion(suggestion)
    _write_ok_objective(objective)
    _write_objective_schema(schema, name="score", direction="maximize")

    _run_cmd(
        str(suggestion),
        str(result),
        "--objective-module",
        str(objective),
        "--objective-schema",
        str(schema),
    )
    payload = json.loads(result.read_text(encoding="utf-8"))
    assert payload["status"] == "ok"
    assert payload["objectives"] == {"score": 0.123}


def test_trial_id_is_exported_to_objective_environment(tmp_path: Path) -> None:
    suggestion = tmp_path / "suggestion.json"
    objective = tmp_path / "objective_trial_id.py"
    result = tmp_path / "result.json"
    _write_suggestion(suggestion)
    _write_trial_id_objective(objective)

    _run_cmd(str(suggestion), str(result), "--objective-module", str(objective))
    payload = json.loads(result.read_text(encoding="utf-8"))
    assert payload["status"] == "ok"
    assert payload["objectives"] == {"loss": 1.0}


def test_yaml_objective_schema_requires_compat_mode(tmp_path: Path) -> None:
    suggestion = tmp_path / "suggestion.json"
    objective = tmp_path / "objective_ok.py"
    schema = tmp_path / "objective_schema.yaml"
    result = tmp_path / "result.json"
    _write_suggestion(suggestion)
    _write_ok_objective(objective)
    _write_objective_schema(schema, name="score", direction="maximize")

    out = _run_cmd(
        str(suggestion),
        str(result),
        "--objective-module",
        str(objective),
        "--objective-schema",
        str(schema),
        expect_ok=False,
    )
    assert out.returncode != 0
    assert "YAML compatibility mode is disabled" in out.stderr


def test_legacy_yaml_objective_schema_is_supported_with_deprecation(tmp_path: Path) -> None:
    suggestion = tmp_path / "suggestion.json"
    objective = tmp_path / "objective_ok.py"
    schema = tmp_path / "objective_schema.yaml"
    result = tmp_path / "result.json"
    _write_suggestion(suggestion)
    _write_ok_objective(objective)
    _write_objective_schema(schema, name="score", direction="maximize")

    out = _run_cmd(
        str(suggestion),
        str(result),
        "--objective-module",
        str(objective),
        "--objective-schema",
        str(schema),
        env={"LOOPTIMUM_YAML_COMPAT_MODE": "1"},
    )
    payload = json.loads(result.read_text(encoding="utf-8"))
    assert payload["status"] == "ok"
    assert payload["objectives"] == {"score": 0.123}
    assert "YAML compatibility mode used for objective_schema.yaml" in out.stderr


def test_executor_aws_batch_writes_canonical_ingest_payload(tmp_path: Path) -> None:
    suggestion = tmp_path / "suggestion.json"
    config = tmp_path / "aws_config.json"
    fake_boto3 = tmp_path / "boto3.py"
    result = tmp_path / "result.json"
    _write_suggestion(suggestion)
    _write_aws_config(config)
    _write_fake_boto3_module(fake_boto3)

    existing_pythonpath = os.environ.get("PYTHONPATH")
    pythonpath = str(tmp_path)
    if existing_pythonpath:
        pythonpath = f"{pythonpath}{os.pathsep}{existing_pythonpath}"

    _run_cmd(
        str(suggestion),
        str(result),
        "--executor",
        "aws-batch",
        "--aws-config",
        str(config),
        env={"PYTHONPATH": pythonpath},
    )

    payload = json.loads(result.read_text(encoding="utf-8"))
    assert payload["status"] == "ok"
    assert payload["objectives"] == {"loss": 0.456}
    assert (tmp_path / "aws_recovery" / "trial_1" / "recovery_record.json").exists()
