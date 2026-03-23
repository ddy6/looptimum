from __future__ import annotations

import importlib.util
import inspect
import io
import json
import sys
import tempfile
import time
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


def _load_campaign_context(
    root: Path,
) -> tuple[Path, ModuleType, Any, JSONDict, dict[str, Path], JSONDict, JSONDict]:
    validated_root, runtime_module = _load_campaign_runtime(root)
    runtime_any = cast(Any, runtime_module)
    cfg, paths = _load_runtime_cfg(validated_root, runtime_module)
    state = cast(JSONDict, runtime_any.load_state(paths["state_file"]))
    objective_cfg = cast(JSONDict, runtime_any._load_objective_config(validated_root, cfg))
    return validated_root, runtime_module, runtime_any, cfg, paths, state, objective_cfg


def _load_jsonl_rows(path: Path) -> list[JSONDict]:
    if not path.exists():
        return []
    rows: list[JSONDict] = []
    for line_number, raw_line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not raw_line.strip():
            continue
        try:
            payload = json.loads(raw_line)
        except json.JSONDecodeError as exc:
            raise RuntimeArtifactError(f"invalid JSONL in {path}:{line_number}") from exc
        if not isinstance(payload, dict):
            raise RuntimeArtifactError(
                f"expected JSON object in {path}:{line_number}, got {type(payload).__name__}"
            )
        rows.append(cast(JSONDict, payload))
    return rows


def _relative_path(runtime_any: Any, root: Path, path: Path) -> str:
    return cast(str, runtime_any._relative_path(root, path))


def _trial_ids(paths: dict[str, Path], state: JSONDict) -> list[int]:
    ids = {
        int(row["trial_id"])
        for row in state.get("observations", [])
        if isinstance(row, dict) and isinstance(row.get("trial_id"), int)
    }
    ids.update(
        int(row["trial_id"])
        for row in state.get("pending", [])
        if isinstance(row, dict) and isinstance(row.get("trial_id"), int)
    )
    trials_root = paths["trials_dir"]
    if trials_root.exists():
        for child in trials_root.iterdir():
            if not child.is_dir() or not child.name.startswith("trial_"):
                continue
            try:
                ids.add(int(child.name.split("_", 1)[1]))
            except ValueError:
                continue
    return sorted(ids)


def _trial_sources(state: JSONDict) -> tuple[dict[int, JSONDict], dict[int, JSONDict]]:
    observations = {
        int(row["trial_id"]): cast(JSONDict, row)
        for row in state.get("observations", [])
        if isinstance(row, dict) and isinstance(row.get("trial_id"), int)
    }
    pending = {
        int(row["trial_id"]): cast(JSONDict, row)
        for row in state.get("pending", [])
        if isinstance(row, dict) and isinstance(row.get("trial_id"), int)
    }
    return observations, pending


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


def _build_trial_record(
    *,
    trial_id: int,
    runtime_any: Any,
    root: Path,
    paths: dict[str, Path],
    observations: dict[int, JSONDict],
    pending: dict[int, JSONDict],
    objective_cfg: JSONDict,
    now: float,
) -> JSONDict:
    manifest = cast(JSONDict, runtime_any.load_trial_manifest(paths["trials_dir"], trial_id))
    observation = observations.get(trial_id)
    pending_entry = pending.get(trial_id)
    source = observation or pending_entry
    if source is None and not manifest:
        raise TrialNotFoundError(f"trial not found: {trial_id}")

    raw_objectives = None
    if observation is not None:
        raw_objectives = observation.get("objectives")
    elif isinstance(manifest.get("objective_vector"), dict):
        raw_objectives = manifest.get("objective_vector")

    metadata = cast(JSONDict, runtime_any.build_objective_metadata(raw_objectives, objective_cfg))
    manifest_path = runtime_any.trial_dir(paths["trials_dir"], trial_id) / "manifest.json"
    record: JSONDict = {
        "trial_id": trial_id,
        "status": manifest.get("status", source.get("status") if source else None),
        "terminal_reason": manifest.get(
            "terminal_reason",
            source.get("terminal_reason") if source else None,
        ),
        "params": manifest.get("params", source.get("params") if source else None),
        "objective_name": manifest.get("objective_name", metadata["objective_name"]),
        "objective_value": manifest.get("objective_value", metadata["objective_value"]),
        "objective_vector": manifest.get("objective_vector", metadata["objective_vector"]),
        "scalarized_objective": manifest.get(
            "scalarized_objective",
            metadata["scalarized_objective"],
        ),
        "penalty_objective": manifest.get(
            "penalty_objective",
            source.get("penalty_objective") if source else None,
        ),
        "suggested_at": manifest.get(
            "suggested_at",
            source.get("suggested_at") if source else None,
        ),
        "completed_at": manifest.get(
            "completed_at",
            source.get("completed_at") if source else None,
        ),
        "last_heartbeat_at": manifest.get(
            "last_heartbeat_at",
            source.get("last_heartbeat_at") if source else None,
        ),
        "heartbeat_count": int(
            manifest.get("heartbeat_count", source.get("heartbeat_count", 0) if source else 0) or 0
        ),
        "lease_token": manifest.get("lease_token", source.get("lease_token") if source else None),
        "artifact_path": manifest.get(
            "artifact_path",
            source.get("artifact_path") if source else None,
        ),
        "artifacts": manifest.get("artifacts", {}),
        "created_at": manifest.get("created_at"),
        "updated_at": manifest.get("updated_at"),
        "manifest_path": _relative_path(runtime_any, root, manifest_path)
        if manifest_path.exists()
        else None,
        "has_manifest": manifest_path.exists(),
        "is_pending": pending_entry is not None,
        "is_terminal": pending_entry is None,
        "pending_age_seconds": None,
    }
    if "scalarization_policy" in manifest:
        record["scalarization_policy"] = manifest["scalarization_policy"]
    elif "scalarization_policy" in metadata:
        record["scalarization_policy"] = metadata["scalarization_policy"]

    for key in (
        "heartbeat_note",
        "heartbeat_meta",
        "source_trial_id",
        "import_source",
        "import_format",
        "imported_at",
    ):
        if key in manifest:
            record[key] = manifest[key]
        elif source is not None and key in source:
            record[key] = source[key]

    if pending_entry is not None:
        record["pending_age_seconds"] = float(
            runtime_any.pending_age_seconds(pending_entry, now=now)
        )
    return record


def build_trial_summaries(root: Path) -> JSONDict:
    (
        validated_root,
        _runtime_module,
        runtime_any,
        _cfg,
        paths,
        state,
        objective_cfg,
    ) = _load_campaign_context(root)
    observations, pending = _trial_sources(state)
    now = time.time()
    trials = [
        _build_trial_record(
            trial_id=trial_id,
            runtime_any=runtime_any,
            root=validated_root,
            paths=paths,
            observations=observations,
            pending=pending,
            objective_cfg=objective_cfg,
            now=now,
        )
        for trial_id in reversed(_trial_ids(paths, state))
    ]
    by_status: dict[str, int] = {}
    for row in trials:
        status = str(row.get("status", "unknown"))
        by_status[status] = by_status.get(status, 0) + 1
    return {
        "count": len(trials),
        "counts": {
            "total": len(trials),
            "pending": len(pending),
            "terminal": len(observations),
            "by_status": by_status,
        },
        "trials": trials,
    }


def load_trial_detail(root: Path, trial_id: int) -> JSONDict:
    (
        validated_root,
        _runtime_module,
        runtime_any,
        _cfg,
        paths,
        state,
        objective_cfg,
    ) = _load_campaign_context(root)
    observations, pending = _trial_sources(state)
    trial = _build_trial_record(
        trial_id=trial_id,
        runtime_any=runtime_any,
        root=validated_root,
        paths=paths,
        observations=observations,
        pending=pending,
        objective_cfg=objective_cfg,
        now=time.time(),
    )
    decision = next(
        (
            row
            for row in _load_jsonl_rows(paths["acquisition_log_file"])
            if int(row.get("trial_id", -1)) == trial_id
        ),
        None,
    )
    return {"trial": trial, "decision": decision}


def build_best_timeseries(root: Path) -> JSONDict:
    (
        _validated_root,
        _runtime_module,
        runtime_any,
        _cfg,
        _paths,
        state,
        objective_cfg,
    ) = _load_campaign_context(root)
    observations = [
        cast(JSONDict, row)
        for row in state.get("observations", [])
        if isinstance(row, dict) and isinstance(row.get("trial_id"), int)
    ]
    observations.sort(
        key=lambda row: (
            float(row.get("completed_at", 0.0) or 0.0),
            int(row["trial_id"]),
        )
    )

    current_best_row: JSONDict | None = None
    current_best_key: tuple[Any, ...] | None = None
    points: list[JSONDict] = []
    ignored_trial_ids: list[int] = []
    for observation in observations:
        trial_id = int(observation["trial_id"])
        if str(observation.get("status", "")) != "ok":
            ignored_trial_ids.append(trial_id)
            continue
        try:
            metadata = cast(
                JSONDict,
                runtime_any.build_objective_metadata(observation.get("objectives"), objective_cfg),
            )
            rank_key = cast(
                tuple[Any, ...],
                runtime_any.best_rank_key(
                    observation.get("objectives"),
                    objective_cfg,
                    trial_id=trial_id,
                ),
            )
        except Exception:
            ignored_trial_ids.append(trial_id)
            continue

        is_improvement = current_best_key is None or rank_key < current_best_key
        if is_improvement or current_best_row is None:
            current_best_row = observation
            current_best_key = rank_key
        best_record = cast(
            JSONDict,
            runtime_any.build_best_record(
                current_best_row,
                objective_cfg,
                updated_at=float(observation.get("completed_at", time.time()) or time.time()),
            ),
        )
        point: JSONDict = {
            "trial_id": trial_id,
            "completed_at": observation.get("completed_at"),
            "objective_name": metadata["objective_name"],
            "objective_value": metadata["objective_value"],
            "objective_vector": metadata["objective_vector"],
            "scalarized_objective": metadata["scalarized_objective"],
            "is_improvement": is_improvement,
            "best_trial_id": best_record["trial_id"],
            "best_objective_name": best_record["objective_name"],
            "best_objective_value": best_record["objective_value"],
        }
        if "scalarization_policy" in metadata:
            point["scalarization_policy"] = metadata["scalarization_policy"]
        if "objective_vector" in best_record:
            point["best_objective_vector"] = best_record["objective_vector"]
        points.append(point)

    return {
        "objective_name": runtime_any.primary_objective_name(objective_cfg),
        "best_objective_name": runtime_any.best_objective_name(objective_cfg),
        "scalarization_policy": runtime_any.scalarization_policy(objective_cfg),
        "points": points,
        "ignored_trial_ids": ignored_trial_ids,
    }


def build_alert_payload(root: Path) -> JSONDict:
    (
        _validated_root,
        _runtime_module,
        runtime_any,
        cfg,
        paths,
        state,
        _objective_cfg,
    ) = _load_campaign_context(root)
    pending_rows = [
        cast(JSONDict, row)
        for row in state.get("pending", [])
        if isinstance(row, dict) and isinstance(row.get("trial_id"), int)
    ]
    now = time.time()
    max_pending_age = runtime_any.resolve_max_pending_age_seconds(cfg)
    stale_trial_ids: list[int] = []
    oldest_age: float | None = None
    for row in pending_rows:
        age = float(runtime_any.pending_age_seconds(row, now=now))
        if oldest_age is None or age > oldest_age:
            oldest_age = age
        if max_pending_age is not None and age > max_pending_age:
            stale_trial_ids.append(int(row["trial_id"]))

    leased_pending = sum(
        1
        for row in pending_rows
        if isinstance(row.get("lease_token"), str) and bool(row.get("lease_token"))
    )
    return {
        "pending_count": len(pending_rows),
        "pending_trial_ids": [int(row["trial_id"]) for row in pending_rows],
        "stale_pending_count": len(stale_trial_ids),
        "stale_pending_trial_ids": stale_trial_ids,
        "leased_pending_count": leased_pending,
        "oldest_pending_age_seconds": oldest_age,
        "max_pending_age_seconds": max_pending_age,
        "report_available": paths["report_json_file"].exists(),
        "decision_trace_available": paths["acquisition_log_file"].exists(),
    }


def load_decision_trace_payload(root: Path) -> JSONDict:
    (
        validated_root,
        _runtime_module,
        runtime_any,
        _cfg,
        paths,
        _state,
        _objective_cfg,
    ) = _load_campaign_context(root)
    entries = _load_jsonl_rows(paths["acquisition_log_file"])
    return {
        "available": paths["acquisition_log_file"].exists(),
        "count": len(entries),
        "path": _relative_path(runtime_any, validated_root, paths["acquisition_log_file"]),
        "entries": entries,
    }


def load_report_markdown_text(root: Path) -> tuple[str, str]:
    (
        validated_root,
        _runtime_module,
        runtime_any,
        _cfg,
        paths,
        _state,
        _objective_cfg,
    ) = _load_campaign_context(root)
    report_path = paths["report_md_file"]
    if not report_path.exists():
        raise ReportNotGeneratedError(
            f"report.md has not been generated for campaign root: {validated_root}"
        )
    return report_path.read_text(encoding="utf-8"), _relative_path(
        runtime_any, validated_root, report_path
    )


def load_decision_trace_text(root: Path) -> tuple[str, str]:
    (
        validated_root,
        _runtime_module,
        runtime_any,
        _cfg,
        paths,
        _state,
        _objective_cfg,
    ) = _load_campaign_context(root)
    decision_trace_path = paths["acquisition_log_file"]
    if not decision_trace_path.exists():
        raise DecisionTraceNotGeneratedError(
            f"acquisition_log.jsonl has not been generated for campaign root: {validated_root}"
        )
    return decision_trace_path.read_text(encoding="utf-8"), _relative_path(
        runtime_any,
        validated_root,
        decision_trace_path,
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
