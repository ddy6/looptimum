"""Ax planning and immutable snapshot storage, without importing Ax or Torch."""

from __future__ import annotations

import importlib.util
import json
import math
import os
import subprocess
import sys
import uuid
from pathlib import Path
from types import ModuleType
from typing import Any, cast

JSONDict = dict[str, Any]


def _shared(name: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        f"looptimum_ax_{name}", Path(__file__).with_name(f"{name}.py")
    )
    if spec is None or spec.loader is None:
        raise ImportError(f"Missing shared module: {name}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


_BACKEND = _shared("optimizer_backend")
_OBJECTIVES = _shared("objectives")
_CONSTRAINTS = _shared("constraints")
_RUNTIME = _shared("runtime")


def _parameters(params: list[JSONDict]) -> list[JSONDict]:
    result = []
    for i, param in enumerate(params):
        item: JSONDict = {
            "name": f"p{i}",
            "raw_name": param["name"],
            "parameter_type": param["type"],
        }
        if param["type"] in ("float", "int"):
            item["bounds"] = param["bounds"]
            item["scaling"] = "log" if param["scale"] == "log" else "linear"
        else:
            item["values"] = param["choices"]
            if param["type"] == "categorical":
                item["parameter_type"] = {str: "str", int: "int", float: "float"}[
                    type(param["choices"][0])
                ]
        result.append(item)
    return result


def _encode(values: JSONDict, parameters: list[JSONDict]) -> JSONDict:
    if set(values) != {param["raw_name"] for param in parameters}:
        raise ValueError("Ax parameter names do not match the declared search space")
    encoded = {}
    for param in parameters:
        value = values[param["raw_name"]]
        kind = param["parameter_type"]
        expected = {"bool": bool, "str": str, "int": int, "float": float}[kind]
        valid = type(value) is expected or (kind == "float" and type(value) is int)
        if not valid or (isinstance(value, float) and not math.isfinite(value)):
            raise ValueError(f"Invalid Ax parameter type/value for {param['raw_name']}")
        if "bounds" in param and not param["bounds"][0] <= value <= param["bounds"][1]:
            raise ValueError(f"Ax parameter '{param['raw_name']}' is outside its bounds")
        if "values" in param and value not in param["values"]:
            raise ValueError(f"Ax parameter '{param['raw_name']}' is not a declared choice")
        encoded[param["name"]] = float(value) if kind == "float" else value
    return encoded


def inspect_snapshot(root: Path, paths: dict[str, Path], state: JSONDict) -> JSONDict | None:
    metadata = state.get("optimizer")
    if metadata is None:
        return None
    try:
        reference = metadata["snapshot"]
        path = (root / reference["path"]).resolve()
        if not path.is_relative_to(paths["optimizer_dir"].resolve()):
            raise ValueError("Snapshot path escapes the optimizer directory")
        snapshot = json.loads(path.read_text())
        if _BACKEND.canonical_digest(snapshot) != reference["sha256"]:
            raise ValueError("Ax snapshot digest mismatch")
        if snapshot["format_version"] != _BACKEND.AX_FORMAT_VERSION:
            raise ValueError("Unsupported Ax snapshot format")
        return cast(JSONDict, snapshot)
    except (KeyError, TypeError, OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"Ax snapshot is missing or invalid: {exc}") from exc


def prepare_batch(
    root: Path,
    paths: dict[str, Path],
    state: JSONDict,
    cfg: JSONDict,
    params: list[JSONDict],
    objective_cfg: JSONDict,
    constraints: JSONDict | None,
    count: int,
    optimizer: JSONDict,
) -> list[tuple[JSONDict, JSONDict]]:
    """Stage a complete Ax allocation in planning state; caller owns the state commit."""
    _BACKEND.assert_backend_matches_state(state, optimizer)
    _BACKEND.validate_ax_capabilities(params, objective_cfg, constraints)
    parameters = _parameters(_CONSTRAINTS.apply_bound_tightening(params, constraints))
    options = optimizer["ax"]
    fingerprint = _BACKEND.canonical_digest(
        {
            "parameters": parameters,
            "objectives": _OBJECTIVES.objective_config_snapshot(objective_cfg),
            "options": {
                key: value
                for key, value in options.items()
                if key not in ("generation_timeout_seconds", "max_generation_attempts")
            },
            "seed": state["meta"]["seed"],
        }
    )
    previous = inspect_snapshot(root, paths, state)
    if previous is not None:
        if previous["fingerprint"] != fingerprint:
            raise ValueError(
                "Ax campaign configuration changed; use a new campaign or restore its original configuration"
            )
        if previous["versions"] != _BACKEND.dependency_versions():
            raise ValueError(
                "Ax dependency versions changed; restore the recorded environment before suggesting"
            )
    records = []
    for pending, rows in ((False, state["observations"]), (True, state["pending"])):
        for row in rows:
            raw = row["params"]
            status = "pending" if pending else row["status"]
            encoded = _encode(raw, parameters)
            raw_objectives = None if pending else row["objectives"]
            records.append(
                {
                    "trial_id": row["trial_id"],
                    "params": encoded,
                    "status": status,
                    "value": float(_OBJECTIVES.scalarize_objectives(raw_objectives, objective_cfg))
                    if status == "ok"
                    else None,
                    "signature": _BACKEND.canonical_digest(
                        {"params": encoded, "status": status, "objectives": raw_objectives}
                    ),
                }
            )
    generation = 0 if previous is None else previous["generation"]
    request = {
        "protocol": 1,
        "parameters": parameters,
        "options": options,
        "direction": _OBJECTIVES.scalarized_direction(objective_cfg),
        "records": records,
        "snapshot": None if previous is None else previous["ax"],
        "mapping": {} if previous is None else previous["mapping"],
        "signatures": {} if previous is None else previous["signatures"],
        "seed": state["meta"]["seed"],
        "generation": generation,
        "next_trial_id": state["next_trial_id"],
        "count": count,
    }
    env = dict(os.environ)
    for key in (
        "OMP_NUM_THREADS",
        "MKL_NUM_THREADS",
        "OPENBLAS_NUM_THREADS",
        "VECLIB_MAXIMUM_THREADS",
        "NUMEXPR_NUM_THREADS",
    ):
        env[key] = "1"
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    try:
        completed = subprocess.run(
            [sys.executable, str(Path(__file__).with_name("optimizer_ax_worker.py"))],
            input=json.dumps(request, allow_nan=False),
            capture_output=True,
            text=True,
            timeout=options["generation_timeout_seconds"],
            env=env,
        )
    except subprocess.TimeoutExpired as exc:
        raise ValueError("Ax generation timed out; no trials were allocated") from exc
    if completed.returncode:
        raise ValueError(f"Ax worker exited unsuccessfully: {completed.stderr[-2000:]}")
    try:
        response = json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        raise ValueError("Ax worker returned invalid JSON") from exc
    if not response.get("ok"):
        raise ValueError(
            f"Ax generation failed ({response.get('error_type')}): {response.get('error')}"
        )
    result = response["result"]
    if len(result["candidates"]) != count:
        raise ValueError("Ax returned an incomplete batch; no trials were allocated")
    planned = []
    for candidate in result["candidates"]:
        raw = {param["raw_name"]: candidate["params"][param["name"]] for param in parameters}
        if _encode(raw, parameters) != candidate["params"]:
            raise ValueError("Ax candidate failed its parameter round trip")
        if constraints and not _CONSTRAINTS.evaluate_constraints(raw, constraints)["feasible"]:
            raise ValueError("Ax candidate violates canonical constraints")
        planned.append(
            (
                raw,
                {
                    "strategy": "ax_generation",
                    "surrogate_backend": "ax",
                    "ax_trial_index": candidate["ax_trial_index"],
                    "generation_node": candidate["generation_node"],
                    "generation": generation,
                    "versions": result["versions"],
                },
            )
        )
    constraint_status = _CONSTRAINTS.build_constraint_status(
        constraints,
        {
            "attempts": count,
            "candidates": [row[0] for row in planned],
            "infeasible_attempts": 0,
            "reject_counts": {},
        },
        phase="ax-generation",
        requested=count,
    )
    for _, decision in planned:
        decision["constraint_status"] = constraint_status
        decision["ax_generation_attempts"] = result["attempts"]
    envelope = {
        "format_version": _BACKEND.AX_FORMAT_VERSION,
        "fingerprint": fingerprint,
        "lineage": previous["lineage"] if previous else uuid.uuid4().hex,
        "generation": generation + 1,
        "versions": result["versions"],
        "mapping": result["mapping"],
        "signatures": result["signatures"],
        "ax": result["snapshot"],
    }
    digest = _BACKEND.canonical_digest(envelope)
    path = paths["optimizer_dir"] / "ax" / "snapshots" / f"{digest}.json"
    relative = path.resolve().relative_to(root.resolve()).as_posix()
    _RUNTIME.atomic_write_json(path, envelope)
    for _, decision in planned:
        decision["optimizer_snapshot"] = digest
    state["schema_version"] = _BACKEND.AX_STATE_SCHEMA_VERSION
    state["optimizer"] = {
        "backend": "ax",
        "format_version": _BACKEND.AX_FORMAT_VERSION,
        "snapshot": {"path": relative, "sha256": digest},
    }
    return planned
