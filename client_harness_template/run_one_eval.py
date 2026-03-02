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
import sys
from pathlib import Path
from typing import Any

DEFAULT_FAILURE_SENTINEL_MINIMIZE = 1e12
DEFAULT_FAILURE_SENTINEL_MAXIMIZE = -1e12


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


def _normalize_eval_output(value: Any) -> tuple[float, str]:
    if isinstance(value, bool):
        raise ValueError("boolean objective values are not supported")
    if isinstance(value, (int, float)):
        out = float(value)
        if not math.isfinite(out):
            raise ValueError("objective value must be finite")
        return out, "ok"
    if isinstance(value, dict):
        raw = value.get("objective", value.get("objective_value"))
        if isinstance(raw, bool) or not isinstance(raw, (int, float)):
            raise ValueError("dict return value must include numeric objective/objective_value")
        out = float(raw)
        if not math.isfinite(out):
            raise ValueError("objective value must be finite")
        status = str(value.get("status", "ok"))
        if status not in {"ok", "failed"}:
            raise ValueError("status must be 'ok' or 'failed'")
        return out, status
    raise ValueError("evaluate(params) must return a number or dict")


def _load_objective_contract(path: Path) -> tuple[str, str]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"objective schema at {path} must be a JSON object")

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


def _default_failure_sentinel(direction: str) -> float:
    if direction == "maximize":
        return DEFAULT_FAILURE_SENTINEL_MAXIMIZE
    return DEFAULT_FAILURE_SENTINEL_MINIMIZE


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def build_failed_payload(
    suggestion: dict[str, Any],
    objective_name: str,
    sentinel_value: float,
) -> dict[str, Any]:
    if not math.isfinite(sentinel_value):
        raise ValueError("failure sentinel must be finite")
    return {
        "trial_id": int(suggestion["trial_id"]),
        "params": suggestion["params"],
        "objectives": {objective_name: float(sentinel_value)},
        "status": "failed",
    }


def parse_args() -> argparse.Namespace:
    here = Path(__file__).resolve().parent
    p = argparse.ArgumentParser(description="Run one client evaluation and emit ingest payload JSON")
    p.add_argument("suggestion_file", help="Path to suggestion JSON (or raw suggest stdout text)")
    p.add_argument("result_file", help="Path to write ingest payload JSON")
    p.add_argument(
        "--objective-module",
        default=str(here / "objective.py"),
        help="Path to module defining evaluate(params)",
    )
    p.add_argument("--objective-name", default=None, help="Primary objective name expected by optimization harness")
    p.add_argument(
        "--objective-direction",
        choices=["minimize", "maximize"],
        default=None,
        help="Objective direction used to choose the default failed-run sentinel",
    )
    p.add_argument(
        "--objective-schema",
        default=None,
        help="Path to objective_schema.yaml/json; if provided, objective name/direction default from primary_objective",
    )
    p.add_argument(
        "--on-exception",
        choices=["failed", "raise"],
        default="failed",
        help="Write a failed payload with sentinel objective or re-raise",
    )
    p.add_argument(
        "--failure-sentinel",
        type=float,
        default=None,
        help=(
            "Finite objective value for on-exception=failed; defaults to +1e12 for minimize "
            "or -1e12 for maximize"
        ),
    )
    p.add_argument("--print-result", action="store_true", help="Print written payload to stdout")
    return p.parse_args()


def main() -> None:
    args = parse_args()
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

    failure_sentinel = float(args.failure_sentinel) if args.failure_sentinel is not None else _default_failure_sentinel(objective_direction)
    if not math.isfinite(failure_sentinel):
        raise ValueError("failure sentinel must be finite")

    suggestion = _load_json_or_suggest_stdout(suggestion_path)
    _require_suggestion_shape(suggestion)

    try:
        objective_module = _load_objective_module(objective_module_path)
        eval_output = objective_module.evaluate(dict(suggestion["params"]))
        objective_value, status = _normalize_eval_output(eval_output)
        result = {
            "trial_id": int(suggestion["trial_id"]),
            "params": suggestion["params"],
            "objectives": {objective_name: objective_value},
            "status": status,
        }
    except Exception as exc:
        if args.on_exception == "raise":
            raise
        print(
            f"[run_one_eval] objective evaluation failed; writing status=failed payload: {exc}",
            file=sys.stderr,
        )
        result = build_failed_payload(suggestion, objective_name, failure_sentinel)

    _write_json(result_path, result)
    if args.print_result:
        print(json.dumps(result, indent=2))
    else:
        print(f"Wrote result payload to {result_path}")


if __name__ == "__main__":
    main()
