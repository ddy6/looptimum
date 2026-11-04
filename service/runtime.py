"""Process-isolated adapter for editable campaign controllers.

Every operation that imports campaign code executes in a fresh worker process.
The service process never redirects global streams or imports campaign modules.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any, cast

from service.models import CampaignDetailResponse, CampaignRecord
from service.registry import InvalidCampaignRootError, ServiceRegistryError, validate_campaign_root

JSONDict = dict[str, Any]


class ReportNotGeneratedError(ServiceRegistryError):
    pass


class DecisionTraceNotGeneratedError(ServiceRegistryError):
    pass


class RuntimeArtifactError(ServiceRegistryError):
    pass


class TrialNotFoundError(ServiceRegistryError):
    pass


class RuntimeCommandError(ServiceRegistryError):
    def __init__(
        self,
        *,
        code: str,
        message: str,
        status_code: int,
        stdout: str = "",
        stderr: str = "",
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code
        self.stdout = stdout
        self.stderr = stderr


def _invoke(root: Path, operation: str, **kwargs: Any) -> Any:
    validated_root = validate_campaign_root(root)
    request = json.dumps(
        {"operation": operation, "root": str(validated_root), "kwargs": kwargs}, allow_nan=False
    )
    try:
        completed = subprocess.run(
            [sys.executable, "-m", "service._runtime_worker"],
            input=request,
            capture_output=True,
            text=True,
            cwd=Path(__file__).resolve().parents[1],
            check=False,
        )
    except OSError as exc:
        raise RuntimeArtifactError(f"unable to start campaign worker: {exc}") from exc
    if completed.returncode != 0:
        raise RuntimeArtifactError(
            f"campaign worker failed (exit {completed.returncode}): {completed.stderr.strip()}"
        )
    try:
        envelope = json.loads(completed.stdout)
        if not isinstance(envelope, dict) or not isinstance(envelope.get("ok"), bool):
            raise ValueError("missing worker result")
        if envelope["ok"]:
            return envelope["value"]
        error = envelope["error"]
        kind, message = error["type"], error["message"]
        if not isinstance(kind, str) or not isinstance(message, str):
            raise ValueError("invalid worker error")
        if kind == "RuntimeCommandError":
            if not all(isinstance(error[key], str) for key in ("code", "stdout", "stderr")):
                raise ValueError("invalid worker command error text")
            if type(error["status_code"]) is not int or not 400 <= error["status_code"] <= 599:
                raise ValueError("invalid worker command error status")
    except (ValueError, TypeError, KeyError) as exc:
        raise RuntimeArtifactError("campaign worker returned an invalid response") from exc
    if kind == "RuntimeCommandError":
        raise RuntimeCommandError(
            code=error["code"],
            message=message,
            status_code=error["status_code"],
            stdout=error["stdout"],
            stderr=error["stderr"],
        )
    error_types: dict[str, type[Exception]] = {
        "InvalidCampaignRootError": InvalidCampaignRootError,
        "ReportNotGeneratedError": ReportNotGeneratedError,
        "DecisionTraceNotGeneratedError": DecisionTraceNotGeneratedError,
        "RuntimeArtifactError": RuntimeArtifactError,
        "TrialNotFoundError": TrialNotFoundError,
        "ValueError": ValueError,
    }
    raise error_types.get(kind, RuntimeArtifactError)(message)


def resolve_runtime_lock_timeout_seconds(root: Path, cli_override: float | None = None) -> float:
    return float(_invoke(root, "resolve_runtime_lock_timeout_seconds", cli_override=cli_override))


def build_status_payload(root: Path) -> JSONDict:
    return cast(JSONDict, _invoke(root, "build_status_payload"))


def load_report_payload(root: Path) -> JSONDict:
    return cast(JSONDict, _invoke(root, "load_report_payload"))


def build_campaign_detail(record: CampaignRecord) -> CampaignDetailResponse:
    return CampaignDetailResponse.model_validate(
        _invoke(
            Path(record.root_path), "build_campaign_detail", record=record.model_dump(mode="json")
        )
    )


def build_trial_summaries(root: Path) -> JSONDict:
    return cast(JSONDict, _invoke(root, "build_trial_summaries"))


def load_trial_detail(root: Path, trial_id: int) -> JSONDict:
    return cast(JSONDict, _invoke(root, "load_trial_detail", trial_id=trial_id))


def build_best_timeseries(root: Path) -> JSONDict:
    return cast(JSONDict, _invoke(root, "build_best_timeseries"))


def build_alert_payload(root: Path) -> JSONDict:
    return cast(JSONDict, _invoke(root, "build_alert_payload"))


def load_decision_trace_payload(root: Path) -> JSONDict:
    return cast(JSONDict, _invoke(root, "load_decision_trace_payload"))


def load_report_markdown_text(root: Path) -> tuple[str, str]:
    return cast(tuple[str, str], tuple(_invoke(root, "load_report_markdown_text")))


def load_decision_trace_text(root: Path) -> tuple[str, str]:
    return cast(tuple[str, str], tuple(_invoke(root, "load_decision_trace_text")))


def suggest_via_runtime(
    root: Path,
    *,
    count: int | None,
    output_mode: str,
    lock_timeout_seconds: float | None,
    fail_fast: bool,
) -> tuple[JSONDict | None, str | None]:
    return cast(
        tuple[JSONDict | None, str | None],
        tuple(
            _invoke(
                root,
                "suggest_via_runtime",
                count=count,
                output_mode=output_mode,
                lock_timeout_seconds=lock_timeout_seconds,
                fail_fast=fail_fast,
            )
        ),
    )


def ingest_via_runtime(
    root: Path,
    *,
    payload: JSONDict,
    lease_token: str | None,
    lock_timeout_seconds: float | None,
    fail_fast: bool,
) -> JSONDict:
    return cast(
        JSONDict,
        _invoke(
            root,
            "ingest_via_runtime",
            payload=payload,
            lease_token=lease_token,
            lock_timeout_seconds=lock_timeout_seconds,
            fail_fast=fail_fast,
        ),
    )


def reset_via_runtime(
    root: Path,
    *,
    yes: bool,
    archive: bool | None,
    lock_timeout_seconds: float | None,
    fail_fast: bool,
) -> JSONDict:
    return cast(
        JSONDict,
        _invoke(
            root,
            "reset_via_runtime",
            yes=yes,
            archive=archive,
            lock_timeout_seconds=lock_timeout_seconds,
            fail_fast=fail_fast,
        ),
    )


def restore_via_runtime(
    root: Path, *, archive_id: str, yes: bool, lock_timeout_seconds: float | None, fail_fast: bool
) -> JSONDict:
    return cast(
        JSONDict,
        _invoke(
            root,
            "restore_via_runtime",
            archive_id=archive_id,
            yes=yes,
            lock_timeout_seconds=lock_timeout_seconds,
            fail_fast=fail_fast,
        ),
    )
