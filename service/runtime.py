from __future__ import annotations

import importlib.util
import inspect
import io
import json
import sys
import tempfile
from contextlib import contextmanager, redirect_stderr, redirect_stdout
from functools import lru_cache
from pathlib import Path
from types import ModuleType, SimpleNamespace
from typing import Any, Iterator, cast

from service.models import CampaignDetailResponse, CampaignRecord
from service.registry import InvalidCampaignRootError, ServiceRegistryError, validate_campaign_root

JSONDict = dict[str, Any]


class ReportNotGeneratedError(ServiceRegistryError):
    pass


class RuntimeArtifactError(ServiceRegistryError):
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


@contextmanager
def _prepend_sys_path(path: Path) -> Iterator[None]:
    inserted = False
    path_text = str(path)
    if path_text not in sys.path:
        sys.path.insert(0, path_text)
        inserted = True
    try:
        yield
    finally:
        if inserted:
            try:
                sys.path.remove(path_text)
            except ValueError:
                pass


@lru_cache(maxsize=32)
def _load_runtime_module(run_bo_path: str) -> ModuleType:
    module_path = Path(run_bo_path).resolve()
    spec = importlib.util.spec_from_file_location(
        f"looptimum_service_runtime_{abs(hash(module_path))}",
        module_path,
    )
    if spec is None or spec.loader is None:
        raise RuntimeArtifactError(f"unable to load runtime entrypoint: {module_path}")
    module = importlib.util.module_from_spec(spec)
    with _prepend_sys_path(module_path.parent):
        spec.loader.exec_module(module)
    return module


def _load_campaign_runtime(root: Path) -> tuple[Path, ModuleType]:
    validated_root = validate_campaign_root(root)
    run_bo_path = validated_root / "run_bo.py"
    if not run_bo_path.exists():
        raise InvalidCampaignRootError("campaign root missing required files: run_bo.py")
    return validated_root, _load_runtime_module(str(run_bo_path))


def _load_runtime_cfg(root: Path, runtime_module: ModuleType) -> tuple[JSONDict, dict[str, Path]]:
    runtime_any = cast(Any, runtime_module)
    cfg_doc, _ = runtime_any.load_contract_document(root, "bo_config")
    if not isinstance(cfg_doc, dict):
        raise InvalidCampaignRootError("bo_config must be an object")
    paths = runtime_any._runtime_paths(root, cfg_doc)
    return cast(JSONDict, cfg_doc), cast(dict[str, Path], paths)


def build_status_payload(root: Path) -> JSONDict:
    validated_root, runtime_module = _load_campaign_runtime(root)
    runtime_any = cast(Any, runtime_module)
    cfg, paths = _load_runtime_cfg(validated_root, runtime_module)
    state = cast(JSONDict, runtime_any.load_state(paths["state_file"]))
    max_pending_age = runtime_any.resolve_max_pending_age_seconds(cfg)
    worker_leases_enabled = runtime_any.resolve_worker_leases_enabled(cfg)
    status_payload_fn = runtime_any._status_payload
    signature = inspect.signature(status_payload_fn)
    if "botorch_feature_flag" in signature.parameters:
        botorch_feature_flag = runtime_any.use_botorch_backend(
            SimpleNamespace(enable_botorch_gp=False),
            cfg,
        )
        return cast(
            JSONDict,
            status_payload_fn(
                validated_root,
                state,
                paths,
                max_pending_age,
                botorch_feature_flag=botorch_feature_flag,
                worker_leases_enabled=worker_leases_enabled,
            ),
        )
    return cast(
        JSONDict,
        status_payload_fn(
            validated_root,
            state,
            paths,
            max_pending_age,
            worker_leases_enabled,
        ),
    )


def load_report_payload(root: Path) -> JSONDict:
    validated_root, runtime_module = _load_campaign_runtime(root)
    _cfg, paths = _load_runtime_cfg(validated_root, runtime_module)
    report_path = paths["report_json_file"]
    if not report_path.exists():
        raise ReportNotGeneratedError(
            f"report.json has not been generated for campaign root: {validated_root}"
        )
    try:
        payload = json.loads(report_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise RuntimeArtifactError(f"report.json must contain valid JSON: {report_path}") from exc
    if not isinstance(payload, dict):
        raise RuntimeArtifactError(f"report.json must contain a JSON object: {report_path}")
    return cast(JSONDict, payload)


def build_campaign_detail(record: CampaignRecord) -> CampaignDetailResponse:
    validated_root, runtime_module = _load_campaign_runtime(Path(record.root_path))
    _cfg, paths = _load_runtime_cfg(validated_root, runtime_module)
    runtime_any = cast(Any, runtime_module)
    relative_path = runtime_any._relative_path
    return CampaignDetailResponse(
        campaign=record,
        status=build_status_payload(validated_root),
        paths={
            "state_file": relative_path(validated_root, paths["state_file"]),
            "observations_csv": relative_path(validated_root, paths["observations_csv"]),
            "acquisition_log_file": relative_path(validated_root, paths["acquisition_log_file"]),
            "event_log_file": relative_path(validated_root, paths["event_log_file"]),
            "trials_dir": relative_path(validated_root, paths["trials_dir"]),
            "report_json_file": relative_path(validated_root, paths["report_json_file"]),
            "report_md_file": relative_path(validated_root, paths["report_md_file"]),
        },
        artifacts={
            "state_file_exists": paths["state_file"].exists(),
            "report_json_exists": paths["report_json_file"].exists(),
            "report_md_exists": paths["report_md_file"].exists(),
        },
    )


def _classify_command_error(
    command: str,
    exc: Exception,
    *,
    stdout: str,
    stderr: str,
) -> RuntimeCommandError:
    message = str(exc)
    if isinstance(exc, TimeoutError):
        return RuntimeCommandError(
            code="lock_unavailable",
            message=message,
            status_code=409,
            stdout=stdout,
            stderr=stderr,
        )
    if "requires --lease-token" in message:
        return RuntimeCommandError(
            code="lease_token_required",
            message=message,
            status_code=409,
            stdout=stdout,
            stderr=stderr,
        )
    if "lease token mismatch" in message:
        return RuntimeCommandError(
            code="lease_token_mismatch",
            message=message,
            status_code=409,
            stdout=stdout,
            stderr=stderr,
        )
    if "re-run with --yes for non-interactive use" in message:
        return RuntimeCommandError(
            code="confirmation_required",
            message=message,
            status_code=400,
            stdout=stdout,
            stderr=stderr,
        )
    if "is not pending" in message:
        return RuntimeCommandError(
            code="trial_not_pending",
            message=message,
            status_code=409,
            stdout=stdout,
            stderr=stderr,
        )
    if "ingest payload params mismatch" in message:
        return RuntimeCommandError(
            code="ingest_params_mismatch",
            message=message,
            status_code=409,
            stdout=stdout,
            stderr=stderr,
        )
    return RuntimeCommandError(
        code=f"{command}_command_error",
        message=message,
        status_code=400,
        stdout=stdout,
        stderr=stderr,
    )


def _run_command(
    root: Path,
    command: str,
    *,
    count: int | None = None,
    json_only: bool = False,
    jsonl: bool = False,
    results_file: str | None = None,
    lease_token: str | None = None,
    yes: bool = False,
    archive: bool | None = None,
    archive_id: str | None = None,
    lock_timeout_seconds: float | None = None,
    fail_fast: bool = False,
) -> tuple[str, str]:
    validated_root, runtime_module = _load_campaign_runtime(root)
    runtime_any = cast(Any, runtime_module)
    command_name = command.replace("-", "_")
    command_fn = getattr(runtime_any, f"cmd_{command_name}", None)
    if command_fn is None:
        raise RuntimeArtifactError(f"runtime does not expose command handler for {command}")

    args = SimpleNamespace(
        project_root=str(validated_root),
        count=count,
        json_only=json_only,
        jsonl=jsonl,
        results_file=results_file,
        lease_token=lease_token,
        yes=yes,
        archive=archive,
        archive_id=archive_id,
        lock_timeout_seconds=lock_timeout_seconds,
        fail_fast=fail_fast,
        enable_botorch_gp=False,
    )

    stdout_buffer = io.StringIO()
    stderr_buffer = io.StringIO()
    with redirect_stdout(stdout_buffer), redirect_stderr(stderr_buffer):
        try:
            command_fn(args)
        except Exception as exc:
            raise _classify_command_error(
                command,
                exc,
                stdout=stdout_buffer.getvalue(),
                stderr=stderr_buffer.getvalue(),
            ) from exc
    return stdout_buffer.getvalue(), stderr_buffer.getvalue()


def suggest_via_runtime(
    root: Path,
    *,
    count: int | None,
    output_mode: str,
    lock_timeout_seconds: float | None,
    fail_fast: bool,
) -> tuple[JSONDict | None, str | None]:
    stdout, _stderr = _run_command(
        root,
        "suggest",
        count=count,
        json_only=(output_mode == "json"),
        jsonl=(output_mode == "jsonl"),
        lock_timeout_seconds=lock_timeout_seconds,
        fail_fast=fail_fast,
    )
    if output_mode == "jsonl":
        return None, stdout
    stripped = stdout.strip()
    if not stripped:
        return {"suggested": False, "message": ""}, None
    try:
        return cast(JSONDict, json.loads(stripped)), None
    except json.JSONDecodeError:
        return {"suggested": False, "message": stripped}, None


def ingest_via_runtime(
    root: Path,
    *,
    payload: JSONDict,
    lease_token: str | None,
    lock_timeout_seconds: float | None,
    fail_fast: bool,
) -> JSONDict:
    temp_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            "w",
            encoding="utf-8",
            suffix=".json",
            delete=False,
        ) as handle:
            json.dump(payload, handle, indent=2)
            temp_path = Path(handle.name)
        stdout, stderr = _run_command(
            root,
            "ingest",
            results_file=str(temp_path),
            lease_token=lease_token,
            lock_timeout_seconds=lock_timeout_seconds,
            fail_fast=fail_fast,
        )
    finally:
        if temp_path is not None:
            temp_path.unlink(missing_ok=True)

    message = stdout.strip()
    response: JSONDict = {
        "message": message,
        "noop": message.startswith("No-op:"),
    }
    stderr_text = stderr.strip()
    if stderr_text:
        response["stderr"] = stderr_text
    return response


def _parse_archive_output(stdout: str) -> tuple[str | None, str | None]:
    archive_path: str | None = None
    for line in stdout.splitlines():
        if line.startswith("Archive: "):
            raw_value = line[len("Archive: ") :].strip()
            archive_path = None if raw_value == "disabled" else raw_value
            break
    archive_id = Path(archive_path).name if archive_path else None
    return archive_path, archive_id


def reset_via_runtime(
    root: Path,
    *,
    yes: bool,
    archive: bool | None,
    lock_timeout_seconds: float | None,
    fail_fast: bool,
) -> JSONDict:
    stdout, stderr = _run_command(
        root,
        "reset",
        yes=yes,
        archive=archive,
        lock_timeout_seconds=lock_timeout_seconds,
        fail_fast=fail_fast,
    )
    message = next((line for line in stdout.splitlines() if line.strip()), "")
    archive_path, archive_id = _parse_archive_output(stdout)
    response: JSONDict = {
        "message": message,
        "archive_path": archive_path,
        "archive_id": archive_id,
        "archive_enabled": archive_path is not None,
        "stdout": stdout,
    }
    stderr_text = stderr.strip()
    if stderr_text:
        response["stderr"] = stderr_text
    return response


def restore_via_runtime(
    root: Path,
    *,
    archive_id: str,
    yes: bool,
    lock_timeout_seconds: float | None,
    fail_fast: bool,
) -> JSONDict:
    stdout, stderr = _run_command(
        root,
        "restore",
        archive_id=archive_id,
        yes=yes,
        lock_timeout_seconds=lock_timeout_seconds,
        fail_fast=fail_fast,
    )
    message = next((line for line in stdout.splitlines() if line.strip()), "")
    archive_path, parsed_archive_id = _parse_archive_output(stdout)
    response: JSONDict = {
        "message": message,
        "archive_path": archive_path,
        "archive_id": parsed_archive_id or archive_id,
        "legacy_archive": any(
            line.strip() == "Archive kind: legacy" for line in stdout.splitlines()
        ),
        "stdout": stdout,
    }
    stderr_text = stderr.strip()
    if stderr_text:
        response["stderr"] = stderr_text
    return response
