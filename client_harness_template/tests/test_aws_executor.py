from __future__ import annotations

import importlib
import io
import json
import sys
from pathlib import Path
from typing import Any

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
HARNESS_DIR = REPO_ROOT / "client_harness_template"
if str(HARNESS_DIR) not in sys.path:
    sys.path.insert(0, str(HARNESS_DIR))

aws_executor = importlib.import_module("aws_executor")
aws_models = importlib.import_module("aws_models")
AWSBatchConfig = aws_models.AWSBatchConfig
AWSRecoveryRecord = aws_models.AWSRecoveryRecord
CanonicalEvalRequest = aws_models.CanonicalEvalRequest


def _parse_s3_uri(uri: str) -> tuple[str, str]:
    without_scheme = uri[len("s3://") :]
    bucket, _, key = without_scheme.partition("/")
    return bucket, key


class FakeS3Client:
    def __init__(self, store: dict[tuple[str, str], str]) -> None:
        self.store = store
        self.put_calls: list[dict[str, Any]] = []
        self.get_calls: list[dict[str, Any]] = []

    def put_object(self, *, Bucket: str, Key: str, Body: bytes, ContentType: str) -> dict[str, Any]:
        self.store[(Bucket, Key)] = Body.decode("utf-8")
        self.put_calls.append(
            {
                "Bucket": Bucket,
                "Key": Key,
                "Body": self.store[(Bucket, Key)],
                "ContentType": ContentType,
            }
        )
        return {}

    def get_object(self, *, Bucket: str, Key: str) -> dict[str, Any]:
        self.get_calls.append({"Bucket": Bucket, "Key": Key})
        if (Bucket, Key) not in self.store:
            raise KeyError(f"missing S3 object: s3://{Bucket}/{Key}")
        return {"Body": io.BytesIO(self.store[(Bucket, Key)].encode("utf-8"))}


class FakeBatchClient:
    def __init__(
        self,
        store: dict[tuple[str, str], str],
        *,
        describe_jobs_sequence: list[dict[str, Any]],
        output_payload: str | None,
    ) -> None:
        self.store = store
        self.describe_jobs_sequence = list(describe_jobs_sequence)
        self.output_payload = output_payload
        self.submit_calls: list[dict[str, Any]] = []
        self.describe_calls = 0

    def submit_job(
        self,
        *,
        jobName: str,
        jobQueue: str,
        jobDefinition: str,
        containerOverrides: dict[str, Any],
    ) -> dict[str, Any]:
        self.submit_calls.append(
            {
                "jobName": jobName,
                "jobQueue": jobQueue,
                "jobDefinition": jobDefinition,
                "containerOverrides": containerOverrides,
            }
        )
        environment = {
            entry["name"]: entry["value"]
            for entry in containerOverrides.get("environment", [])
            if isinstance(entry, dict)
        }
        if self.output_payload is not None:
            bucket, key = _parse_s3_uri(environment["LOOPTIMUM_OUTPUT_S3_URI"])
            self.store[(bucket, key)] = self.output_payload
        return {"jobId": "job-123", "jobName": jobName}

    def describe_jobs(self, *, jobs: list[str]) -> dict[str, Any]:
        self.describe_calls += 1
        if not self.describe_jobs_sequence:
            return {"jobs": []}
        idx = min(self.describe_calls - 1, len(self.describe_jobs_sequence) - 1)
        payload = dict(self.describe_jobs_sequence[idx])
        payload["jobId"] = jobs[0]
        return {"jobs": [payload]}


class FakeSession:
    def __init__(self, s3_client: FakeS3Client, batch_client: FakeBatchClient) -> None:
        self._s3_client = s3_client
        self._batch_client = batch_client

    def client(self, service_name: str) -> Any:
        if service_name == "s3":
            return self._s3_client
        if service_name == "batch":
            return self._batch_client
        raise ValueError(service_name)


def _config(tmp_path: Path, *, max_wait_seconds: float = 120.0) -> AWSBatchConfig:
    return AWSBatchConfig(
        profile=None,
        region="us-east-1",
        job_queue="looptimum-evals",
        job_definition="looptimum-evaluator:1",
        job_name_prefix="looptimum-trial",
        bucket="client-looptimum-runs",
        input_prefix="inputs/",
        output_prefix="outputs/",
        poll_interval_seconds=0.01,
        max_wait_seconds=max_wait_seconds,
        recovery_dir=tmp_path / "aws_recovery",
    )


def _request(trial_id: int = 7) -> CanonicalEvalRequest:
    return CanonicalEvalRequest(trial_id=trial_id, params={"x1": 0.2, "x2": 0.7})


def _recovery_record_path(config: AWSBatchConfig, trial_id: int) -> Path:
    return config.recovery_dir / f"trial_{trial_id}" / "recovery_record.json"


def test_build_aws_session_requires_boto3(monkeypatch: pytest.MonkeyPatch) -> None:
    def _raise_missing(module_name: str) -> Any:
        raise ModuleNotFoundError(module_name)

    monkeypatch.setattr(aws_executor.importlib, "import_module", _raise_missing)

    with pytest.raises(ModuleNotFoundError, match="requires boto3"):
        aws_executor.build_aws_session(profile=None, region=None)


def test_build_aws_session_returns_real_boto3_session_when_installed() -> None:
    boto3 = pytest.importorskip("boto3")

    session = aws_executor.build_aws_session(profile=None, region="us-east-1")

    assert isinstance(session, boto3.session.Session)
    assert session.region_name == "us-east-1"


def test_evaluate_via_batch_success_writes_recovery_sidecars(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = _config(tmp_path)
    store: dict[tuple[str, str], str] = {}
    s3_client = FakeS3Client(store)
    batch_client = FakeBatchClient(
        store,
        describe_jobs_sequence=[{"status": "SUCCEEDED"}],
        output_payload=json.dumps({"status": "ok", "objective": 0.25}),
    )
    monkeypatch.setattr(
        aws_executor,
        "build_aws_session",
        lambda profile, region: FakeSession(s3_client, batch_client),
    )

    result = aws_executor.evaluate_via_batch(_request(), config=config)

    assert result == {"status": "ok", "objective": 0.25}
    assert len(batch_client.submit_calls) == 1
    assert (config.recovery_dir / "trial_7" / "input_request.json").exists()
    assert (config.recovery_dir / "trial_7" / "remote_result.json").exists()
    record = json.loads(_recovery_record_path(config, 7).read_text(encoding="utf-8"))
    assert record["status"] == "succeeded"
    assert record["batch_job_id"] == "job-123"
    assert record["canonical_result"]["objective"] == 0.25


def test_evaluate_via_batch_smoke_with_real_boto3_session(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    pytest.importorskip("boto3")
    monkeypatch.setenv("AWS_EC2_METADATA_DISABLED", "true")
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "test")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "test")
    monkeypatch.setenv("AWS_SESSION_TOKEN", "test")

    config = _config(tmp_path)
    store: dict[tuple[str, str], str] = {}
    session = aws_executor.build_aws_session(profile=None, region="us-east-1")
    s3_client = session.client("s3")
    batch_client = session.client("batch")

    def _put_object(*, Bucket: str, Key: str, Body: bytes, ContentType: str) -> dict[str, Any]:
        if isinstance(Body, bytes):
            store[(Bucket, Key)] = Body.decode("utf-8")
        else:
            store[(Bucket, Key)] = Body
        return {}

    def _get_object(*, Bucket: str, Key: str) -> dict[str, Any]:
        return {"Body": io.BytesIO(store[(Bucket, Key)].encode("utf-8"))}

    def _submit_job(
        *,
        jobName: str,
        jobQueue: str,
        jobDefinition: str,
        containerOverrides: dict[str, Any],
    ) -> dict[str, Any]:
        env = {
            entry["name"]: entry["value"]
            for entry in containerOverrides["environment"]
            if isinstance(entry, dict)
        }
        bucket, key = _parse_s3_uri(env["LOOPTIMUM_OUTPUT_S3_URI"])
        store[(bucket, key)] = json.dumps({"status": "ok", "objective": 0.789})
        return {"jobId": "job-real-123", "jobName": jobName}

    def _describe_jobs(*, jobs: list[str]) -> dict[str, Any]:
        return {"jobs": [{"jobId": jobs[0], "status": "SUCCEEDED"}]}

    monkeypatch.setattr(s3_client, "put_object", _put_object)
    monkeypatch.setattr(s3_client, "get_object", _get_object)
    monkeypatch.setattr(batch_client, "submit_job", _submit_job)
    monkeypatch.setattr(batch_client, "describe_jobs", _describe_jobs)

    class _SessionWrapper:
        def client(self, service_name: str) -> Any:
            if service_name == "s3":
                return s3_client
            if service_name == "batch":
                return batch_client
            raise ValueError(service_name)

    monkeypatch.setattr(
        aws_executor,
        "build_aws_session",
        lambda profile, region: _SessionWrapper(),
    )

    result = aws_executor.evaluate_via_batch(_request(), config=config)

    assert result == {"status": "ok", "objective": 0.789}
    assert json.loads((config.recovery_dir / "trial_7" / "remote_result.json").read_text()) == {
        "status": "ok",
        "objective": 0.789,
    }


def test_evaluate_via_batch_timeout_returns_timeout_and_persists_record(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = _config(tmp_path, max_wait_seconds=10.0)
    store: dict[tuple[str, str], str] = {}
    s3_client = FakeS3Client(store)
    batch_client = FakeBatchClient(store, describe_jobs_sequence=[], output_payload=None)
    monkeypatch.setattr(
        aws_executor,
        "build_aws_session",
        lambda profile, region: FakeSession(s3_client, batch_client),
    )
    timeline = iter([100.0, 120.5, 121.0])
    monkeypatch.setattr(aws_executor.time, "time", lambda: next(timeline))
    monkeypatch.setattr(aws_executor.time, "sleep", lambda _: None)

    result = aws_executor.evaluate_via_batch(_request(), config=config)

    assert result["status"] == "timeout"
    assert "max_wait_seconds=10" in result["terminal_reason"]
    assert batch_client.describe_calls == 0
    record = json.loads(_recovery_record_path(config, 7).read_text(encoding="utf-8"))
    assert record["status"] == "timeout"
    assert record["canonical_result"]["status"] == "timeout"


def test_evaluate_via_batch_failed_job_maps_to_failed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = _config(tmp_path)
    store: dict[tuple[str, str], str] = {}
    s3_client = FakeS3Client(store)
    batch_client = FakeBatchClient(
        store,
        describe_jobs_sequence=[{"status": "FAILED", "statusReason": "container exit code 1"}],
        output_payload=None,
    )
    monkeypatch.setattr(
        aws_executor,
        "build_aws_session",
        lambda profile, region: FakeSession(s3_client, batch_client),
    )

    result = aws_executor.evaluate_via_batch(_request(), config=config)

    assert result["status"] == "failed"
    assert "container exit code 1" in result["terminal_reason"]


def test_evaluate_via_batch_missing_result_artifact_maps_to_failed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = _config(tmp_path)
    store: dict[tuple[str, str], str] = {}
    s3_client = FakeS3Client(store)
    batch_client = FakeBatchClient(
        store,
        describe_jobs_sequence=[{"status": "SUCCEEDED"}],
        output_payload=None,
    )
    monkeypatch.setattr(
        aws_executor,
        "build_aws_session",
        lambda profile, region: FakeSession(s3_client, batch_client),
    )

    result = aws_executor.evaluate_via_batch(_request(), config=config)

    assert result["status"] == "failed"
    assert "Failed to load remote result" in result["terminal_reason"]


def test_evaluate_via_batch_malformed_remote_result_maps_to_failed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = _config(tmp_path)
    store: dict[tuple[str, str], str] = {}
    s3_client = FakeS3Client(store)
    batch_client = FakeBatchClient(
        store,
        describe_jobs_sequence=[{"status": "SUCCEEDED"}],
        output_payload="{not-json",
    )
    monkeypatch.setattr(
        aws_executor,
        "build_aws_session",
        lambda profile, region: FakeSession(s3_client, batch_client),
    )

    result = aws_executor.evaluate_via_batch(_request(), config=config)

    assert result["status"] == "failed"
    assert "Failed to load remote result" in result["terminal_reason"]


def test_evaluate_via_batch_resumes_from_existing_recovery_record_without_resubmit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = _config(tmp_path)
    store: dict[tuple[str, str], str] = {}
    output_s3_uri = "s3://client-looptimum-runs/outputs/trial_7/result.json"
    bucket, key = _parse_s3_uri(output_s3_uri)
    store[(bucket, key)] = json.dumps({"status": "ok", "objective": 1.5})

    record = AWSRecoveryRecord(
        trial_id=7,
        executor="aws-batch",
        batch_job_id="job-777",
        job_name="looptimum-trial-trial-7",
        submitted_at=1_000.0,
        status="submitted",
        input_s3_uri="s3://client-looptimum-runs/inputs/trial_7/request.json",
        output_s3_uri=output_s3_uri,
    )
    record_path = _recovery_record_path(config, 7)
    record_path.parent.mkdir(parents=True, exist_ok=True)
    record_path.write_text(json.dumps(record.to_payload(), indent=2), encoding="utf-8")

    s3_client = FakeS3Client(store)
    batch_client = FakeBatchClient(
        store,
        describe_jobs_sequence=[{"status": "SUCCEEDED"}],
        output_payload=None,
    )
    monkeypatch.setattr(
        aws_executor,
        "build_aws_session",
        lambda profile, region: FakeSession(s3_client, batch_client),
    )
    monkeypatch.setattr(aws_executor.time, "time", lambda: 1_010.0)

    result = aws_executor.evaluate_via_batch(_request(), config=config)

    assert result == {"status": "ok", "objective": 1.5}
    assert batch_client.submit_calls == []
