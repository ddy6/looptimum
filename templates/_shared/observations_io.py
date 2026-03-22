from __future__ import annotations

import importlib.util
import json
import math
from pathlib import Path
from types import ModuleType
from typing import Any, cast

JSONDict = dict[str, Any]

_SUPPORTED_FORMATS = {"csv", "jsonl"}
_TERMINAL_STATUSES = {"ok", "failed", "killed", "timeout"}
_CSV_HEARTBEAT_META_FIELD = "heartbeat_meta_json"
_KNOWN_ROW_FIELDS = {
    "trial_id",
    "source_trial_id",
    "status",
    "suggested_at",
    "completed_at",
    "runtime_seconds",
    "terminal_reason",
    "penalty_objective",
    "artifact_path",
    "last_heartbeat_at",
    "heartbeat_count",
    "heartbeat_note",
    "lease_token",
    "heartbeat_meta",
    _CSV_HEARTBEAT_META_FIELD,
}
_EXPORT_FIELD_ORDER = [
    "trial_id",
    "params",
    "objectives",
    "status",
    "suggested_at",
    "completed_at",
    "runtime_seconds",
    "terminal_reason",
    "penalty_objective",
    "artifact_path",
    "last_heartbeat_at",
    "heartbeat_count",
    "heartbeat_note",
    "heartbeat_meta",
    "lease_token",
]


def _load_shared_module(module_name: str, filename: str) -> ModuleType:
    module_path = Path(__file__).resolve().with_name(filename)
    spec = importlib.util.spec_from_file_location(module_name, module_path)
    if spec is None or spec.loader is None:
        raise ImportError(f"Unable to load shared module from {module_path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


_OBJECTIVES = _load_shared_module("looptimum_shared_objectives_import", "objectives.py")
_SEARCH_SPACE = _load_shared_module("looptimum_shared_search_space_import", "search_space.py")

active_parameters = _SEARCH_SPACE.active_parameters
canonicalize_conditional_params = _SEARCH_SPACE.canonicalize_conditional_params
canonical_objective_vector = _OBJECTIVES.canonical_objective_vector
nullable_objective_vector = _OBJECTIVES.nullable_objective_vector
objective_names = _OBJECTIVES.objective_names


def _is_finite_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def _require_object(value: Any, *, field_name: str) -> JSONDict:
    if not isinstance(value, dict):
        raise ValueError(f"{field_name} must be an object")
    return cast(JSONDict, value)


def _require_supported_format(row_format: str) -> str:
    normalized = str(row_format).strip().lower()
    if normalized not in _SUPPORTED_FORMATS:
        raise ValueError(f"row_format must be one of {sorted(_SUPPORTED_FORMATS)}")
    return normalized


def _require_trial_id(value: Any, *, field_name: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool):
        raise ValueError(f"{field_name} must be an integer")
    if value < 1:
        raise ValueError(f"{field_name} must be >= 1")
    return int(value)


def _normalize_status(value: Any, *, field_name: str) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{field_name} must be a string")
    status = value.strip().lower()
    if status not in _TERMINAL_STATUSES:
        raise ValueError(f"{field_name} must be one of {sorted(_TERMINAL_STATUSES)}")
    return status


def _normalize_optional_string(
    value: Any,
    *,
    field_name: str,
    treat_blank_as_none: bool = True,
) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError(f"{field_name} must be a string or null")
    out = value.strip()
    if not out and treat_blank_as_none:
        return None
    if not out:
        raise ValueError(f"{field_name} must not be empty")
    return out


def _normalize_optional_float(value: Any, *, field_name: str) -> float | None:
    if value is None:
        return None
    if isinstance(value, str):
        stripped = value.strip()
        if not stripped:
            return None
        try:
            value = float(stripped)
        except ValueError as exc:
            raise ValueError(f"{field_name} must be a finite number or null") from exc
    if not _is_finite_number(value):
        raise ValueError(f"{field_name} must be a finite number or null")
    return float(value)


def _normalize_optional_int(value: Any, *, field_name: str) -> int | None:
    if value is None:
        return None
    if isinstance(value, str):
        stripped = value.strip()
        if not stripped:
            return None
        try:
            value = int(stripped)
        except ValueError as exc:
            raise ValueError(f"{field_name} must be an integer or null") from exc
    if not isinstance(value, int) or isinstance(value, bool):
        raise ValueError(f"{field_name} must be an integer or null")
    return int(value)


def _normalize_optional_nonnegative_int(value: Any, *, field_name: str) -> int | None:
    out = _normalize_optional_int(value, field_name=field_name)
    if out is not None and out < 0:
        raise ValueError(f"{field_name} must be >= 0")
    return out


def _parse_bool_value(value: Any, *, field_name: str) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        stripped = value.strip().lower()
        if stripped in {"true", "1", "yes"}:
            return True
        if stripped in {"false", "0", "no"}:
            return False
    raise ValueError(f"{field_name} must be a boolean value")


def _normalize_numeric_param_value(value: Any, param: JSONDict, *, field_name: str) -> int | float:
    param_type = str(param["type"])
    if isinstance(value, str):
        stripped = value.strip()
        if not stripped:
            raise ValueError(f"{field_name} must not be blank")
        try:
            value = int(stripped) if param_type == "int" else float(stripped)
        except ValueError as exc:
            raise ValueError(f"{field_name} must be a valid {param_type} value") from exc

    if param_type == "int":
        if (
            isinstance(value, bool)
            or not isinstance(value, (int, float))
            or not float(value).is_integer()
        ):
            raise ValueError(f"{field_name} must be an integer value")
        return int(value)

    if not _is_finite_number(value):
        raise ValueError(f"{field_name} must be a finite number")
    return float(value)


def _normalize_categorical_param_value(
    value: Any, param: JSONDict, *, field_name: str
) -> str | int | float:
    choices = list(param["choices"])
    if value in choices:
        return cast(str | int | float, value)

    if isinstance(value, str):
        stripped = value.strip()
        if not stripped:
            raise ValueError(f"{field_name} must not be blank")
        for choice in choices:
            if isinstance(choice, str) and choice == stripped:
                return cast(str | int | float, choice)
        for choice in choices:
            if isinstance(choice, bool) or isinstance(choice, str):
                continue
            try:
                numeric = int(stripped) if isinstance(choice, int) else float(stripped)
            except ValueError:
                continue
            if numeric == choice:
                return cast(str | int | float, choice)

    raise ValueError(f"{field_name} must match one of the configured categorical choices {choices}")


def _normalize_param_value(value: Any, param: JSONDict, *, field_name: str) -> Any:
    if value is None:
        return None
    if isinstance(value, str) and not value.strip():
        return None

    param_type = str(param["type"])
    if param_type == "bool":
        return _parse_bool_value(value, field_name=field_name)
    if param_type in {"float", "int"}:
        return _normalize_numeric_param_value(value, param, field_name=field_name)
    if param_type == "categorical":
        return _normalize_categorical_param_value(value, param, field_name=field_name)
    raise ValueError(f"Unsupported parameter type '{param_type}'")


def _normalize_param_payload(raw: Any, params: list[JSONDict], *, field_name: str) -> JSONDict:
    payload = _require_object(raw, field_name=field_name)
    known_names = {str(param["name"]) for param in params}
    extras = sorted(set(payload) - known_names)
    if extras:
        raise ValueError(f"{field_name} includes unknown params {extras}")

    parsed: JSONDict = {}
    for param in params:
        name = str(param["name"])
        if name not in payload:
            continue
        value = _normalize_param_value(payload[name], param, field_name=f"{field_name}.{name}")
        if value is not None:
            parsed[name] = value

    canonical = cast(JSONDict, canonicalize_conditional_params(parsed, params))
    missing = [
        str(param["name"])
        for param in active_parameters(params, canonical)
        if str(param["name"]) not in canonical
    ]
    if missing:
        raise ValueError(f"{field_name} missing required active params {missing}")
    return canonical


def _normalize_csv_param_payload(row: JSONDict, params: list[JSONDict]) -> JSONDict:
    known_columns = {f"param_{param['name']}" for param in params}
    for key, value in row.items():
        if key in _KNOWN_ROW_FIELDS or key in known_columns or key.startswith("objective_"):
            continue
        if value is None or (isinstance(value, str) and not value.strip()):
            continue
        raise ValueError(f"csv row contains unknown column '{key}'")

    payload: JSONDict = {}
    for param in params:
        column = f"param_{param['name']}"
        if column not in row:
            continue
        value = _normalize_param_value(
            row[column],
            param,
            field_name=f"csv.{column}",
        )
        if value is not None:
            payload[str(param["name"])] = value

    canonical = cast(JSONDict, canonicalize_conditional_params(payload, params))
    missing = [
        str(param["name"])
        for param in active_parameters(params, canonical)
        if str(param["name"]) not in canonical
    ]
    if missing:
        raise ValueError(f"csv row missing required active params {missing}")
    return canonical


def _normalize_objective_payload(
    raw: Any,
    *,
    objective_cfg: JSONDict,
    status: str,
    field_name: str,
) -> JSONDict:
    objectives = nullable_objective_vector(raw, objective_cfg)
    if status == "ok":
        return cast(JSONDict, canonical_objective_vector(objectives, objective_cfg))
    violations = [name for name, value in objectives.items() if value is not None]
    if violations:
        raise ValueError(
            f"{field_name} must be null for all configured objectives when status={status}"
        )
    return cast(JSONDict, objectives)


def _normalize_csv_objective_payload(
    row: JSONDict, *, objective_cfg: JSONDict, status: str
) -> JSONDict:
    payload = {
        name: _normalize_optional_float(
            row.get(f"objective_{name}"),
            field_name=f"csv.objective_{name}",
        )
        for name in objective_names(objective_cfg)
    }
    return _normalize_objective_payload(
        payload,
        objective_cfg=objective_cfg,
        status=status,
        field_name="csv objectives",
    )


def _normalize_source_trial_id(value: Any) -> int | str | None:
    if value is None:
        return None
    if isinstance(value, bool):
        raise ValueError("source trial id must not be boolean")
    if isinstance(value, int):
        return int(value)
    if isinstance(value, float):
        if not math.isfinite(value) or not float(value).is_integer():
            raise ValueError("source trial id must be integer-like when numeric")
        return int(value)
    if isinstance(value, str):
        stripped = value.strip()
        return stripped or None
    raise ValueError("source trial id must be a string, integer, or null")


def _normalize_source_trial_id_from_jsonl(raw: JSONDict) -> int | str | None:
    if "source_trial_id" in raw:
        return _normalize_source_trial_id(raw.get("source_trial_id"))
    if "trial_id" in raw:
        return _normalize_source_trial_id(raw.get("trial_id"))
    return None


def _normalize_source_trial_id_from_csv(row: JSONDict) -> int | str | None:
    if "source_trial_id" in row:
        return _normalize_source_trial_id(row.get("source_trial_id"))
    if "trial_id" in row:
        return _normalize_source_trial_id(row.get("trial_id"))
    return None


def infer_observation_format(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix == ".csv":
        return "csv"
    if suffix in {".jsonl", ".ndjson"}:
        return "jsonl"
    raise ValueError(
        f"Unsupported observation file format for '{path}'; expected .csv, .jsonl, or .ndjson"
    )


def plan_import_trial_ids(state: JSONDict, row_count: int) -> list[int]:
    if not isinstance(row_count, int) or row_count < 0:
        raise ValueError("row_count must be an integer >= 0")

    pending = state.get("pending")
    if not isinstance(pending, list):
        raise ValueError("state.pending must be a list")
    if pending:
        raise ValueError("import-observations requires zero pending trials in the first pass")

    next_trial_id = _require_trial_id(state.get("next_trial_id"), field_name="state.next_trial_id")
    return list(range(next_trial_id, next_trial_id + row_count))


def export_observation_json_record(observation: JSONDict) -> JSONDict:
    record = _require_object(observation, field_name="observation")
    _require_trial_id(record.get("trial_id"), field_name="observation.trial_id")
    _normalize_status(record.get("status"), field_name="observation.status")
    _require_object(record.get("params"), field_name="observation.params")
    _require_object(record.get("objectives"), field_name="observation.objectives")

    out: JSONDict = {}
    for field in _EXPORT_FIELD_ORDER:
        if field in record:
            out[field] = record[field]
    return out


def flatten_observation_for_csv(observation: JSONDict) -> JSONDict:
    record = export_observation_json_record(observation)
    params = _require_object(record.pop("params"), field_name="observation.params")
    objectives = _require_object(record.pop("objectives"), field_name="observation.objectives")

    out: JSONDict = dict(record)
    if "heartbeat_meta" in out:
        heartbeat_meta = out.pop("heartbeat_meta")
        if heartbeat_meta is None:
            out[_CSV_HEARTBEAT_META_FIELD] = None
        elif isinstance(heartbeat_meta, dict):
            out[_CSV_HEARTBEAT_META_FIELD] = json.dumps(
                heartbeat_meta,
                sort_keys=True,
                separators=(",", ":"),
            )
        else:
            raise ValueError("observation.heartbeat_meta must be an object or null")

    for key, value in params.items():
        out[f"param_{key}"] = value
    for key, value in objectives.items():
        out[f"objective_{key}"] = value
    return out


def flatten_observations_for_csv(observations: list[JSONDict]) -> list[JSONDict]:
    return [flatten_observation_for_csv(observation) for observation in observations]


def _normalize_common_observation_fields(
    *,
    raw_status: Any,
    raw_suggested_at: Any,
    raw_completed_at: Any,
    raw_terminal_reason: Any,
    raw_penalty_objective: Any,
    raw_artifact_path: Any,
    raw_last_heartbeat_at: Any,
    raw_heartbeat_count: Any,
    raw_heartbeat_note: Any,
    raw_heartbeat_meta: Any,
    raw_lease_token: Any,
    raw_runtime_seconds: Any,
    local_trial_id: int,
    imported_at: float,
) -> JSONDict:
    status = _normalize_status(raw_status, field_name="status")
    suggested_at = _normalize_optional_float(raw_suggested_at, field_name="suggested_at")
    completed_at = _normalize_optional_float(raw_completed_at, field_name="completed_at")
    if completed_at is None:
        completed_at = float(imported_at)

    terminal_reason = _normalize_optional_string(raw_terminal_reason, field_name="terminal_reason")
    if status != "ok" and terminal_reason is None:
        terminal_reason = f"status={status}"

    penalty_objective = _normalize_optional_float(
        raw_penalty_objective, field_name="penalty_objective"
    )
    if status == "ok" and penalty_objective is not None:
        raise ValueError("penalty_objective must be null when status=ok")

    artifact_path = _normalize_optional_string(raw_artifact_path, field_name="artifact_path")
    last_heartbeat_at = _normalize_optional_float(
        raw_last_heartbeat_at,
        field_name="last_heartbeat_at",
    )
    heartbeat_count = _normalize_optional_nonnegative_int(
        raw_heartbeat_count,
        field_name="heartbeat_count",
    )
    heartbeat_note = _normalize_optional_string(raw_heartbeat_note, field_name="heartbeat_note")
    lease_token = _normalize_optional_string(raw_lease_token, field_name="lease_token")
    runtime_seconds = _normalize_optional_float(raw_runtime_seconds, field_name="runtime_seconds")

    heartbeat_meta: JSONDict | None = None
    if raw_heartbeat_meta is not None:
        if isinstance(raw_heartbeat_meta, str):
            stripped = raw_heartbeat_meta.strip()
            if stripped:
                try:
                    decoded = json.loads(stripped)
                except json.JSONDecodeError as exc:
                    raise ValueError("heartbeat_meta_json must decode to a JSON object") from exc
                if not isinstance(decoded, dict):
                    raise ValueError("heartbeat_meta_json must decode to a JSON object")
                heartbeat_meta = cast(JSONDict, decoded)
        elif isinstance(raw_heartbeat_meta, dict):
            heartbeat_meta = cast(JSONDict, raw_heartbeat_meta)
        else:
            raise ValueError("heartbeat_meta must be an object, JSON object string, or null")

    observation: JSONDict = {
        "trial_id": local_trial_id,
        "status": status,
        "suggested_at": suggested_at,
        "completed_at": completed_at,
        "artifact_path": artifact_path,
    }
    if terminal_reason is not None:
        observation["terminal_reason"] = terminal_reason
    if penalty_objective is not None or status != "ok":
        observation["penalty_objective"] = penalty_objective
    if last_heartbeat_at is not None:
        observation["last_heartbeat_at"] = last_heartbeat_at
    if heartbeat_count is not None:
        observation["heartbeat_count"] = heartbeat_count
    if heartbeat_note is not None:
        observation["heartbeat_note"] = heartbeat_note
    if heartbeat_meta is not None:
        observation["heartbeat_meta"] = heartbeat_meta
    if lease_token is not None:
        observation["lease_token"] = lease_token
    if runtime_seconds is not None:
        observation["runtime_seconds"] = runtime_seconds
    return observation


def normalize_import_record(
    raw: Any,
    *,
    row_format: str,
    params: list[JSONDict],
    objective_cfg: JSONDict,
    local_trial_id: int,
    imported_at: float,
) -> JSONDict:
    normalized_format = _require_supported_format(row_format)
    _require_trial_id(local_trial_id, field_name="local_trial_id")
    if not _is_finite_number(imported_at):
        raise ValueError("imported_at must be a finite number")

    if normalized_format == "jsonl":
        row = _require_object(raw, field_name="jsonl observation row")
        source_trial_id = _normalize_source_trial_id_from_jsonl(row)
        known_fields = {
            "trial_id",
            "source_trial_id",
            "params",
            "objectives",
            "status",
            "suggested_at",
            "completed_at",
            "runtime_seconds",
            "terminal_reason",
            "penalty_objective",
            "artifact_path",
            "last_heartbeat_at",
            "heartbeat_count",
            "heartbeat_note",
            "heartbeat_meta",
            "lease_token",
        }
        extras = sorted(set(row) - known_fields)
        if extras:
            raise ValueError(f"jsonl observation row includes unknown fields {extras}")

        observation = _normalize_common_observation_fields(
            raw_status=row.get("status"),
            raw_suggested_at=row.get("suggested_at"),
            raw_completed_at=row.get("completed_at"),
            raw_terminal_reason=row.get("terminal_reason"),
            raw_penalty_objective=row.get("penalty_objective"),
            raw_artifact_path=row.get("artifact_path"),
            raw_last_heartbeat_at=row.get("last_heartbeat_at"),
            raw_heartbeat_count=row.get("heartbeat_count"),
            raw_heartbeat_note=row.get("heartbeat_note"),
            raw_heartbeat_meta=row.get("heartbeat_meta"),
            raw_lease_token=row.get("lease_token"),
            raw_runtime_seconds=row.get("runtime_seconds"),
            local_trial_id=local_trial_id,
            imported_at=float(imported_at),
        )
        observation["params"] = _normalize_param_payload(
            row.get("params"),
            params,
            field_name="params",
        )
        observation["objectives"] = _normalize_objective_payload(
            row.get("objectives"),
            objective_cfg=objective_cfg,
            status=str(observation["status"]),
            field_name="objectives",
        )
        return {
            "row_format": normalized_format,
            "source_trial_id": source_trial_id,
            "observation": observation,
        }

    row = _require_object(raw, field_name="csv observation row")
    source_trial_id = _normalize_source_trial_id_from_csv(row)
    observation = _normalize_common_observation_fields(
        raw_status=row.get("status"),
        raw_suggested_at=row.get("suggested_at"),
        raw_completed_at=row.get("completed_at"),
        raw_terminal_reason=row.get("terminal_reason"),
        raw_penalty_objective=row.get("penalty_objective"),
        raw_artifact_path=row.get("artifact_path"),
        raw_last_heartbeat_at=row.get("last_heartbeat_at"),
        raw_heartbeat_count=row.get("heartbeat_count"),
        raw_heartbeat_note=row.get("heartbeat_note"),
        raw_heartbeat_meta=row.get(_CSV_HEARTBEAT_META_FIELD),
        raw_lease_token=row.get("lease_token"),
        raw_runtime_seconds=row.get("runtime_seconds"),
        local_trial_id=local_trial_id,
        imported_at=float(imported_at),
    )
    observation["params"] = _normalize_csv_param_payload(row, params)
    observation["objectives"] = _normalize_csv_objective_payload(
        row,
        objective_cfg=objective_cfg,
        status=str(observation["status"]),
    )
    return {
        "row_format": normalized_format,
        "source_trial_id": source_trial_id,
        "observation": observation,
    }
