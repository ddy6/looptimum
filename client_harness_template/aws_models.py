from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal, TypedDict, cast

CanonicalStatus = Literal["ok", "failed", "killed", "timeout"]
ObjectiveDirection = Literal["minimize", "maximize"]


class CanonicalEvalResult(TypedDict, total=False):
    status: CanonicalStatus
    objective: float | None
    penalty_objective: float
    terminal_reason: str


@dataclass(frozen=True)
class CanonicalEvalRequest:
    trial_id: int
    params: dict[str, Any]
    schema_version: str | None = None
    suggested_at: float | None = None
    objective_name: str | None = None
    objective_direction: ObjectiveDirection | None = None

    def to_payload(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "trial_id": int(self.trial_id),
            "params": dict(self.params),
        }
        if self.schema_version is not None:
            payload["schema_version"] = self.schema_version
        if self.suggested_at is not None:
            payload["suggested_at"] = float(self.suggested_at)
        if self.objective_name is not None:
            payload["objective_name"] = self.objective_name
        if self.objective_direction is not None:
            payload["objective_direction"] = self.objective_direction
        return payload


@dataclass(frozen=True)
class AWSBatchConfig:
    profile: str | None
    region: str | None
    job_queue: str
    job_definition: str
    job_name_prefix: str
    bucket: str
    input_prefix: str
    output_prefix: str
    poll_interval_seconds: float
    max_wait_seconds: float
    recovery_dir: Path

    def input_key(self, trial_id: int) -> str:
        return f"{self.input_prefix}trial_{int(trial_id)}/request.json"

    def output_key(self, trial_id: int) -> str:
        return f"{self.output_prefix}trial_{int(trial_id)}/result.json"


@dataclass
class AWSRecoveryRecord:
    trial_id: int
    executor: str
    batch_job_id: str
    job_name: str
    submitted_at: float
    status: str
    input_s3_uri: str
    output_s3_uri: str
    aws_status: str | None = None
    last_checked_at: float | None = None
    completed_at: float | None = None
    terminal_reason: str | None = None
    canonical_result: CanonicalEvalResult | None = None

    def to_payload(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "trial_id": int(self.trial_id),
            "executor": self.executor,
            "batch_job_id": self.batch_job_id,
            "job_name": self.job_name,
            "submitted_at": float(self.submitted_at),
            "status": self.status,
            "input_s3_uri": self.input_s3_uri,
            "output_s3_uri": self.output_s3_uri,
        }
        if self.aws_status is not None:
            payload["aws_status"] = self.aws_status
        if self.last_checked_at is not None:
            payload["last_checked_at"] = float(self.last_checked_at)
        if self.completed_at is not None:
            payload["completed_at"] = float(self.completed_at)
        if self.terminal_reason is not None:
            payload["terminal_reason"] = self.terminal_reason
        if self.canonical_result is not None:
            payload["canonical_result"] = dict(self.canonical_result)
        return payload

    @classmethod
    def from_payload(cls, payload: dict[str, Any]) -> AWSRecoveryRecord:
        raw_result = payload.get("canonical_result")
        canonical_result: CanonicalEvalResult | None = None
        if isinstance(raw_result, dict):
            canonical_result = cast(CanonicalEvalResult, dict(raw_result))

        return cls(
            trial_id=int(payload["trial_id"]),
            executor=str(payload["executor"]),
            batch_job_id=str(payload["batch_job_id"]),
            job_name=str(payload["job_name"]),
            submitted_at=float(payload["submitted_at"]),
            status=str(payload["status"]),
            input_s3_uri=str(payload["input_s3_uri"]),
            output_s3_uri=str(payload["output_s3_uri"]),
            aws_status=(
                str(payload["aws_status"]) if payload.get("aws_status") is not None else None
            ),
            last_checked_at=(
                float(payload["last_checked_at"])
                if payload.get("last_checked_at") is not None
                else None
            ),
            completed_at=(
                float(payload["completed_at"]) if payload.get("completed_at") is not None else None
            ),
            terminal_reason=(
                str(payload["terminal_reason"])
                if payload.get("terminal_reason") is not None
                else None
            ),
            canonical_result=canonical_result,
        )
