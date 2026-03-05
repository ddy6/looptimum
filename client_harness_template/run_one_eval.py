#!/usr/bin/env python3
"""Convert one optimization suggestion into one ingest-ready result payload.

This script is intentionally small and file-backed so it can run inside a client
environment with minimal dependencies.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import math
import re
import sys
import warnings
from pathlib import Path
from typing import Any

DEFAULT_FAILURE_PENALTY_MINIMIZE = 1e12
DEFAULT_FAILURE_PENALTY_MAXIMIZE = -1e12
DEFAULT_SCHEMA_VERSION = "0.3.0"
CANONICAL_STATUSES = {"ok", "failed", "killed", "timeout"}
SUCCESS_ALIAS = "success"
_MISSING = object()
_SCHEMA_VERSION_PATTERN = re.compile(r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)$")


def _warn_deprecation(message: str) -> None:
    warnings.warn(message, UserWarning, stacklevel=2)


def _load_data_file(path: Path) -> Any:
    text = path.read_text(encoding="utf-8")
    suffix = path.suffix.lower()

    if suffix == ".json":
        try:
            return json.loads(text)
        except json.JSONDecodeError as exc:
            raise ValueError(f"Failed to parse JSON file {path}: {exc}") from exc

    if suffix in {".yaml", ".yml"}:
        _warn_deprecation(
            f"Deprecated objective schema extension in use: {path.name}. "
            "Rename to objective_schema.json."
        )
        try:
            import yaml  # type: ignore
        except ModuleNotFoundError:
            try:
                parsed = json.loads(text)
            except json.JSONDecodeError as exc:
                raise ValueError(
                    f"Failed to parse YAML file {path}. Install YAML support with "
                    f'`pip install ".[yaml]"` (or `pip install "looptimum[yaml]"`).'
                ) from exc
            _warn_deprecation(
                f"Parsed {path.name} via JSON compatibility fallback. "
                'Full YAML requires `pip install ".[yaml]"` or `pip install "looptimum[yaml]"`.'
            )
            return parsed

        parsed = yaml.safe_load(text)
        if parsed is None:
            return {}
        return parsed

    raise ValueError(
        f"Unsupported objective schema extension for {path}. Supported: .json, .yaml, .yml"
    )


def _load_json_or_suggest_stdout(path: Path) -> dict[str, Any]:
    text = path.read_text(encoding="utf-8")
    try:
        data = json.loads(text)
        if isinstance(data, dict):
            return data
    except json.JSONDecodeError:
        pass

    # Handle raw `run_bo.py suggest` stdout by dropping trailing non-JSON lines
    # (e.g., "Objective direction: minimize (loss)").
    lines = [line for line in text.splitlines() if line.strip()]
    for end in range(len(lines), 0, -1):
        chunk = "\n".join(lines[:end])
        try:
            data = json.loads(chunk)
        except json.JSONDecodeError:
            continue
        if isinstance(data, dict):
            return data
    raise ValueError(f"Could not parse suggestion JSON from {path}")


def _require_suggestion_shape(suggestion: dict[str, Any]) -> None:
    if "trial_id" not in suggestion:
        raise ValueError("suggestion missing trial_id")
    if "params" not in suggestion:
        raise ValueError("suggestion missing params")
    if not isinstance(suggestion["params"], dict):
        raise ValueError("suggestion params must be an object")
    tid = suggestion["trial_id"]
    if not isinstance(tid, int) or isinstance(tid, bool) or tid < 1:
        raise ValueError("suggestion trial_id must be an integer >= 1")


def _load_objective_module(path: Path):
    spec = importlib.util.spec_from_file_location("client_objective", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Failed to load objective module from {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    if not hasattr(module, "evaluate"):
        raise AttributeError(f"{path} must define evaluate(params)")
    return module


def _require_finite_number(value: Any, *, field_name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{field_name} must be a finite number")
    out = float(value)
    if not math.isfinite(out):
        raise ValueError(f"{field_name} must be a finite number")
    return out


def _normalize_status(raw_status: Any) -> str:
    if raw_status is None:
        return "ok"
    if not isinstance(raw_status, str):
        raise ValueError("status must be a string")
    normalized = raw_status.strip().lower()
    if normalized == SUCCESS_ALIAS:
        return "ok"
    if normalized not in CANONICAL_STATUSES:
        raise ValueError(f"status must be one of {sorted(CANONICAL_STATUSES)} or '{SUCCESS_ALIAS}'")
    return normalized


def _normalize_schema_version(raw_schema_version: Any) -> str:
    if raw_schema_version is None:
        return DEFAULT_SCHEMA_VERSION
    if not isinstance(raw_schema_version, str):
        raise ValueError("schema_version must be a semver string")
    normalized = raw_schema_version.strip()
    if _SCHEMA_VERSION_PATTERN.fullmatch(normalized) is None:
        raise ValueError("schema_version must match semver '<major>.<minor>.<patch>'")
    return normalized


def _normalize_eval_output(value: Any, *, default_failure_penalty: float) -> dict[str, Any]:
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return {"status": "ok", "objective": _require_finite_number(value, field_name="objective")}

    if not isinstance(value, dict):
        raise ValueError("evaluate(params) must return a number or dict")

    status = _normalize_status(value.get("status", "ok"))
    objective_raw = value.get("objective", value.get("objective_value", _MISSING))
    penalty_raw = value.get("penalty_objective", _MISSING)

    if status == "ok":
        if objective_raw is _MISSING:
            raise ValueError(
                "dict return value with status='ok' must include objective/objective_value"
            )
        if penalty_raw is not _MISSING:
            raise ValueError("penalty_objective is only valid for non-ok statuses")
        return {
            "status": "ok",
            "objective": _require_finite_number(objective_raw, field_name="objective"),
        }

    # Non-ok statuses: output normalized contract shape with primary objective null.
    penalty_objective: float | None = None
    if penalty_raw is not _MISSING and penalty_raw is not None:
        penalty_objective = _require_finite_number(penalty_raw, field_name="penalty_objective")

    if objective_raw is _MISSING or objective_raw is None:
        if penalty_objective is None:
            penalty_objective = default_failure_penalty
    else:
        legacy_sentinel = _require_finite_number(objective_raw, field_name="objective")
        if penalty_objective is None:
            penalty_objective = legacy_sentinel

    return {
        "status": status,
        "objective": None,
        "penalty_objective": penalty_objective,
    }


def _load_objective_contract(path: Path) -> tuple[str, str]:
    data = _load_data_file(path)
    if not isinstance(data, dict):
        raise ValueError(f"objective schema at {path} must be an object")

    primary = data.get("primary_objective")
    if not isinstance(primary, dict):
        raise ValueError(f"objective schema at {path} missing primary_objective object")

    name = primary.get("name")
    direction = primary.get("direction")
    if not isinstance(name, str) or not name.strip():
        raise ValueError(f"objective schema at {path} has invalid primary_objective.name")
    if direction not in {"minimize", "maximize"}:
        raise ValueError(f"objective schema at {path} has invalid primary_objective.direction")
    return name, str(direction)


def _default_failure_penalty(direction: str) -> float:
    if direction == "maximize":
        return DEFAULT_FAILURE_PENALTY_MAXIMIZE
    return DEFAULT_FAILURE_PENALTY_MINIMIZE


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def build_failed_payload(
    suggestion: dict[str, Any],
    objective_name: str,
    penalty_value: float,
    schema_version: str,
) -> dict[str, Any]:
    if not math.isfinite(penalty_value):
        raise ValueError("failure penalty_objective must be finite")
    return {
        "schema_version": schema_version,
        "trial_id": int(suggestion["trial_id"]),
        "params": suggestion["params"],
        "objectives": {objective_name: None},
        "penalty_objective": float(penalty_value),
        "status": "failed",
    }


def parse_args() -> tuple[argparse.Namespace, bool]:
    here = Path(__file__).resolve().parent
    p = argparse.ArgumentParser(
        description="Run one client evaluation and emit ingest payload JSON"
    )
    p.add_argument("suggestion_file", help="Path to suggestion JSON (or raw suggest stdout text)")
    p.add_argument("result_file", help="Path to write ingest payload JSON")
    p.add_argument(
        "--objective-module",
        default=str(here / "objective.py"),
        help="Path to module defining evaluate(params)",
    )
    p.add_argument(
        "--objective-name",
        default=None,
        help="Primary objective name expected by optimization harness",
    )
    p.add_argument(
        "--objective-direction",
        choices=["minimize", "maximize"],
        default=None,
        help="Objective direction used to choose the default failure penalty",
    )
    p.add_argument(
        "--objective-schema",
        default=None,
        help=(
            "Path to objective_schema.json (preferred). "
            "Legacy .yaml/.yml accepted with deprecation warnings."
        ),
    )
    p.add_argument(
        "--on-exception",
        choices=["failed", "raise"],
        default="failed",
        help="Write a failed payload (objective=null + penalty_objective) or re-raise",
    )
    p.add_argument(
        "--failure-penalty-objective",
        dest="failure_penalty_objective",
        type=float,
        default=None,
        help=(
            "Finite penalty_objective value for on-exception=failed; defaults to "
            "+1e12 for minimize or -1e12 for maximize"
        ),
    )
    p.add_argument(
        "--failure-sentinel",
        dest="failure_penalty_objective",
        type=float,
        default=None,
        help=argparse.SUPPRESS,
    )
    p.add_argument("--print-result", action="store_true", help="Print written payload to stdout")
    args = p.parse_args()
    legacy_flag_used = "--failure-sentinel" in sys.argv[1:]
    return args, legacy_flag_used


def main() -> None:
    args, legacy_failure_flag_used = parse_args()
    suggestion_path = Path(args.suggestion_file)
    result_path = Path(args.result_file)
    objective_module_path = Path(args.objective_module)

    objective_name = str(args.objective_name) if args.objective_name else None
    objective_direction = str(args.objective_direction) if args.objective_direction else None
    if args.objective_schema:
        schema_name, schema_direction = _load_objective_contract(Path(args.objective_schema))
        if objective_name is None:
            objective_name = schema_name
        if objective_direction is None:
            objective_direction = schema_direction
    if objective_name is None:
        objective_name = "loss"
    if objective_direction is None:
        objective_direction = "minimize"

    failure_penalty = (
        float(args.failure_penalty_objective)
        if args.failure_penalty_objective is not None
        else _default_failure_penalty(objective_direction)
    )
    if not math.isfinite(failure_penalty):
        raise ValueError("failure penalty_objective must be finite")
    if legacy_failure_flag_used:
        print(
            "[run_one_eval] Deprecated flag '--failure-sentinel' used; "
            "prefer '--failure-penalty-objective'.",
            file=sys.stderr,
        )

    suggestion = _load_json_or_suggest_stdout(suggestion_path)
    _require_suggestion_shape(suggestion)
    schema_version = _normalize_schema_version(suggestion.get("schema_version"))

    try:
        objective_module = _load_objective_module(objective_module_path)
        eval_output = objective_module.evaluate(dict(suggestion["params"]))
        normalized = _normalize_eval_output(eval_output, default_failure_penalty=failure_penalty)
        result = {
            "schema_version": schema_version,
            "trial_id": int(suggestion["trial_id"]),
            "params": suggestion["params"],
            "objectives": {objective_name: normalized["objective"]},
            "status": normalized["status"],
        }
        if normalized.get("penalty_objective") is not None:
            result["penalty_objective"] = normalized["penalty_objective"]
    except Exception as exc:
        if args.on_exception == "raise":
            raise
        print(
            f"[run_one_eval] objective evaluation failed; writing status=failed payload: {exc}",
            file=sys.stderr,
        )
        result = build_failed_payload(suggestion, objective_name, failure_penalty, schema_version)

    _write_json(result_path, result)
    if args.print_result:
        print(json.dumps(result, indent=2))
    else:
        print(f"Wrote result payload to {result_path}")


if __name__ == "__main__":
    main()
