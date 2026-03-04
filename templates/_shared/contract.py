from __future__ import annotations

import json
import math
import warnings
from pathlib import Path
from typing import Any

CANONICAL_STATUSES = {"ok", "failed", "killed", "timeout"}
SUCCESS_ALIAS = "success"
_MISSING = object()


def _render_value(value: Any) -> str:
    if value is _MISSING:
        return "<missing>"
    try:
        return json.dumps(value, sort_keys=True)
    except TypeError:
        return repr(value)


def _warn_deprecation(message: str) -> None:
    warnings.warn(message, UserWarning, stacklevel=2)


def _validation_error(
    *,
    source_path: Path,
    field_path: str,
    expected: str,
    received: Any,
    trial_id: int | None = None,
) -> ValueError:
    prefix = (
        f"file={source_path} trial_id={trial_id} field={field_path}"
        if trial_id is not None
        else f"file={source_path} field={field_path}"
    )
    return ValueError(
        f"Validation error: {prefix} expected={expected} received={_render_value(received)}"
    )


def _is_type(value: Any, expected: str) -> bool:
    if expected == "object":
        return isinstance(value, dict)
    if expected == "array":
        return isinstance(value, list)
    if expected == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if expected == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if expected == "string":
        return isinstance(value, str)
    if expected == "boolean":
        return isinstance(value, bool)
    if expected == "null":
        return value is None
    return True


def validate_against_schema(
    value: Any,
    schema: dict,
    *,
    source_path: Path,
    field_path: str = "$",
    trial_id: int | None = None,
) -> None:
    expected_type = schema.get("type")
    if expected_type is not None:
        type_options = [expected_type] if isinstance(expected_type, str) else list(expected_type)
        if not any(_is_type(value, t) for t in type_options):
            expected_label = (
                f"type '{expected_type}'"
                if isinstance(expected_type, str)
                else f"one of types {type_options}"
            )
            raise _validation_error(
                source_path=source_path,
                field_path=field_path,
                expected=expected_label,
                received=value,
                trial_id=trial_id,
            )

    if "enum" in schema and value not in schema["enum"]:
        raise _validation_error(
            source_path=source_path,
            field_path=field_path,
            expected=f"one of {schema['enum']}",
            received=value,
            trial_id=trial_id,
        )

    if isinstance(value, (int, float)) and not isinstance(value, bool):
        if "minimum" in schema and float(value) < float(schema["minimum"]):
            raise _validation_error(
                source_path=source_path,
                field_path=field_path,
                expected=f">= {schema['minimum']}",
                received=value,
                trial_id=trial_id,
            )
        if "maximum" in schema and float(value) > float(schema["maximum"]):
            raise _validation_error(
                source_path=source_path,
                field_path=field_path,
                expected=f"<= {schema['maximum']}",
                received=value,
                trial_id=trial_id,
            )

    if schema.get("type") == "object" and isinstance(value, dict):
        for key in schema.get("required", []):
            if key not in value:
                raise _validation_error(
                    source_path=source_path,
                    field_path=f"{field_path}.{key}",
                    expected="required field present",
                    received=_MISSING,
                    trial_id=trial_id,
                )

        props = schema.get("properties", {})
        for key, child_schema in props.items():
            if key in value:
                validate_against_schema(
                    value[key],
                    child_schema,
                    source_path=source_path,
                    field_path=f"{field_path}.{key}",
                    trial_id=trial_id,
                )

        if schema.get("additionalProperties") is False:
            extras = sorted(set(value.keys()) - set(props.keys()))
            if extras:
                raise _validation_error(
                    source_path=source_path,
                    field_path=field_path,
                    expected=f"no unknown fields (unexpected: {extras})",
                    received=value,
                    trial_id=trial_id,
                )

    if schema.get("type") == "array" and isinstance(value, list):
        min_items = schema.get("minItems")
        if min_items is not None and len(value) < int(min_items):
            raise _validation_error(
                source_path=source_path,
                field_path=field_path,
                expected=f"array length >= {min_items}",
                received=value,
                trial_id=trial_id,
            )
        max_items = schema.get("maxItems")
        if max_items is not None and len(value) > int(max_items):
            raise _validation_error(
                source_path=source_path,
                field_path=field_path,
                expected=f"array length <= {max_items}",
                received=value,
                trial_id=trial_id,
            )

        item_schema = schema.get("items")
        if isinstance(item_schema, dict):
            for idx, item in enumerate(value):
                validate_against_schema(
                    item,
                    item_schema,
                    source_path=source_path,
                    field_path=f"{field_path}[{idx}]",
                    trial_id=trial_id,
                )


def load_data_file(path: Path) -> Any:
    text = path.read_text(encoding="utf-8")
    suffix = path.suffix.lower()
    if suffix == ".json":
        try:
            return json.loads(text)
        except json.JSONDecodeError as exc:
            raise ValueError(f"Failed to parse JSON file {path}: {exc}") from exc

    if suffix in {".yaml", ".yml"}:
        try:
            import yaml  # type: ignore
        except ModuleNotFoundError:
            # Legacy compatibility: old .yaml files were JSON syntax in this repo.
            try:
                parsed = json.loads(text)
            except json.JSONDecodeError as exc:
                raise ValueError(
                    f"Failed to parse YAML file {path}. Install YAML support with "
                    f'`pip install ".[yaml]"` (or `pip install "looptimum[yaml]"`).'
                ) from exc
            _warn_deprecation(
                f"Deprecated config extension: {path.name}. Parsed as JSON compatibility fallback. "
                "Rename to .json. Full YAML requires `.[yaml]` / `looptimum[yaml]`."
            )
            return parsed

        parsed = yaml.safe_load(text)
        if parsed is None:
            return {}
        return parsed

    raise ValueError(f"Unsupported config extension for {path}. Supported: .json, .yaml, .yml")


def resolve_contract_path(project_root: Path, stem: str) -> tuple[Path, bool]:
    preferred = project_root / f"{stem}.json"
    if preferred.exists():
        return preferred, False

    legacy_yaml = project_root / f"{stem}.yaml"
    if legacy_yaml.exists():
        return legacy_yaml, True

    legacy_yml = project_root / f"{stem}.yml"
    if legacy_yml.exists():
        return legacy_yml, True

    raise FileNotFoundError(
        f"Missing required contract file for '{stem}' under {project_root}. "
        "Expected .json (preferred) or legacy .yaml/.yml."
    )


def load_contract_document(project_root: Path, stem: str) -> tuple[Any, Path]:
    path, is_legacy = resolve_contract_path(project_root, stem)
    if is_legacy:
        _warn_deprecation(
            f"Deprecated config extension in use: {path.name}. Rename to {stem}.json."
        )
    return load_data_file(path), path


def load_schema_from_paths(
    project_root: Path,
    paths_cfg: dict,
    *,
    key: str,
    default_rel: str,
    legacy_key: str | None = None,
) -> tuple[dict, Path]:
    used_legacy_key = False
    rel = paths_cfg.get(key)
    if rel is None and legacy_key is not None and legacy_key in paths_cfg:
        rel = paths_cfg.get(legacy_key)
        used_legacy_key = True
    if rel is None:
        rel = default_rel
    if used_legacy_key and legacy_key is not None:
        _warn_deprecation(f"Deprecated config path key '{legacy_key}' used; rename to '{key}'.")
    schema_path = (project_root / str(rel)).resolve()
    schema = load_data_file(schema_path)
    if not isinstance(schema, dict):
        raise ValueError(f"Schema file must contain a JSON/YAML object: {schema_path}")
    return schema, schema_path


def _require_int(value: Any, *, source_path: Path, field_path: str) -> int:
    if not (isinstance(value, int) and not isinstance(value, bool)):
        raise _validation_error(
            source_path=source_path,
            field_path=field_path,
            expected="integer",
            received=value,
        )
    return int(value)


def _require_number(
    value: Any, *, source_path: Path, field_path: str, trial_id: int | None
) -> float:
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        raise _validation_error(
            source_path=source_path,
            field_path=field_path,
            expected="finite number",
            received=value,
            trial_id=trial_id,
        )
    out = float(value)
    if not math.isfinite(out):
        raise _validation_error(
            source_path=source_path,
            field_path=field_path,
            expected="finite number",
            received=value,
            trial_id=trial_id,
        )
    return out


def normalize_status(
    raw_status: Any,
    *,
    source_path: Path,
    field_path: str = "$.status",
    trial_id: int | None = None,
) -> str:
    if raw_status is None:
        return "ok"
    if not isinstance(raw_status, str):
        raise _validation_error(
            source_path=source_path,
            field_path=field_path,
            expected=f"status string in {sorted(CANONICAL_STATUSES)} or '{SUCCESS_ALIAS}'",
            received=raw_status,
            trial_id=trial_id,
        )
    normalized = raw_status.strip().lower()
    if normalized == SUCCESS_ALIAS:
        _warn_deprecation(
            "Deprecated status alias 'success' received; normalizing to 'ok'. "
            "Use canonical statuses: ok|failed|killed|timeout."
        )
        return "ok"
    if normalized not in CANONICAL_STATUSES:
        raise _validation_error(
            source_path=source_path,
            field_path=field_path,
            expected=f"one of {sorted(CANONICAL_STATUSES)} or '{SUCCESS_ALIAS}'",
            received=raw_status,
            trial_id=trial_id,
        )
    return normalized


def _normalize_primary_objective(
    *,
    payload: dict,
    objective_name: str,
    status: str,
    source_path: Path,
    trial_id: int | None,
    emit_transition_warnings: bool,
) -> tuple[dict, float | None]:
    objectives = payload.get("objectives")
    if not isinstance(objectives, dict):
        raise _validation_error(
            source_path=source_path,
            field_path="$.objectives",
            expected="object",
            received=objectives,
            trial_id=trial_id,
        )
    if objective_name not in objectives:
        raise _validation_error(
            source_path=source_path,
            field_path=f"$.objectives.{objective_name}",
            expected="required primary objective present",
            received=_MISSING,
            trial_id=trial_id,
        )

    normalized_objectives = dict(objectives)
    primary_value = normalized_objectives.get(objective_name)
    penalty_present = "penalty_objective" in payload
    penalty_value = payload.get("penalty_objective")

    if status == "ok":
        normalized_objectives[objective_name] = _require_number(
            primary_value,
            source_path=source_path,
            field_path=f"$.objectives.{objective_name}",
            trial_id=trial_id,
        )
        if penalty_present:
            raise _validation_error(
                source_path=source_path,
                field_path="$.penalty_objective",
                expected="omitted for status 'ok'",
                received=penalty_value,
                trial_id=trial_id,
            )
        return normalized_objectives, None

    # Non-ok statuses: new contract requires null primary objective.
    normalized_objectives[objective_name] = None
    normalized_penalty: float | None = None
    if penalty_present:
        normalized_penalty = _require_number(
            penalty_value,
            source_path=source_path,
            field_path="$.penalty_objective",
            trial_id=trial_id,
        )

    if primary_value is None:
        return normalized_objectives, normalized_penalty

    # Transition compatibility path for v0.1 sentinel objective payloads.
    sentinel_value = _require_number(
        primary_value,
        source_path=source_path,
        field_path=f"$.objectives.{objective_name}",
        trial_id=trial_id,
    )
    if normalized_penalty is None:
        normalized_penalty = sentinel_value
    if emit_transition_warnings:
        _warn_deprecation(
            f"Deprecated failure objective payload for trial_id={trial_id}: "
            f"status='{status}' with numeric primary objective. "
            "Use primary objective null and optional penalty_objective. "
            "Sentinel support is planned for removal in v0.3.0."
        )
    return normalized_objectives, normalized_penalty


def normalize_ingest_payload(
    payload: dict, *, objective_name: str, source_path: Path
) -> tuple[dict, int]:
    trial_id = _require_int(
        payload.get("trial_id"), source_path=source_path, field_path="$.trial_id"
    )
    status = normalize_status(
        payload.get("status"), source_path=source_path, field_path="$.status", trial_id=trial_id
    )

    params = payload.get("params")
    if not isinstance(params, dict):
        raise _validation_error(
            source_path=source_path,
            field_path="$.params",
            expected="object",
            received=params,
            trial_id=trial_id,
        )

    normalized = dict(payload)
    normalized["trial_id"] = trial_id
    normalized["status"] = status
    normalized["params"] = params

    objectives, penalty = _normalize_primary_objective(
        payload=normalized,
        objective_name=objective_name,
        status=status,
        source_path=source_path,
        trial_id=trial_id,
        emit_transition_warnings=True,
    )
    normalized["objectives"] = objectives
    if penalty is None:
        normalized.pop("penalty_objective", None)
    else:
        normalized["penalty_objective"] = penalty
    return normalized, trial_id


def build_observation_contract(observation: dict, *, objective_name: str) -> dict:
    trial_id = int(observation["trial_id"])
    status = str(observation.get("status", "ok")).strip().lower()
    if status == SUCCESS_ALIAS:
        status = "ok"
    if status not in CANONICAL_STATUSES:
        status = "failed"

    payload_like = {
        "trial_id": trial_id,
        "params": observation.get("params", {}),
        "objectives": dict(observation.get("objectives", {})),
        "status": status,
    }
    if "penalty_objective" in observation:
        payload_like["penalty_objective"] = observation["penalty_objective"]

    objectives, penalty = _normalize_primary_objective(
        payload=payload_like,
        objective_name=objective_name,
        status=status,
        source_path=Path("<state>"),
        trial_id=trial_id,
        emit_transition_warnings=False,
    )
    out = {
        "trial_id": trial_id,
        "params": payload_like["params"],
        "objectives": objectives,
        "status": status,
    }
    if penalty is not None:
        out["penalty_objective"] = penalty
    return out


def _diff_records(path: str, left: Any, right: Any, out: list[str]) -> None:
    if isinstance(left, dict) and isinstance(right, dict):
        for key in sorted(set(left.keys()) | set(right.keys())):
            child_path = f"{path}.{key}"
            lv = left.get(key, _MISSING)
            rv = right.get(key, _MISSING)
            if lv is _MISSING or rv is _MISSING:
                out.append(
                    f"{child_path} differs: expected={_render_value(lv)} received={_render_value(rv)}"
                )
                continue
            _diff_records(child_path, lv, rv, out)
        return

    if isinstance(left, list) and isinstance(right, list):
        if len(left) != len(right):
            out.append(f"{path} length differs: expected={len(left)} received={len(right)}")
            return
        for idx, (lv, rv) in enumerate(zip(left, right)):
            _diff_records(f"{path}[{idx}]", lv, rv, out)
        return

    if left != right:
        out.append(
            f"{path} differs: expected={_render_value(left)} received={_render_value(right)}"
        )


def diff_contract_records(expected: dict, received: dict) -> list[str]:
    out: list[str] = []
    _diff_records("$", expected, received, out)
    return out


def format_contract_diff_error(trial_id: int, diffs: list[str]) -> str:
    body = "\n".join(f"- field {line}" for line in diffs)
    return f"conflicting duplicate ingest for trial_id {trial_id}:\n{body}"
