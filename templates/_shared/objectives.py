from __future__ import annotations

import math
from typing import Any

JSONDict = dict[str, Any]

_DIRECTIONS = {"minimize", "maximize"}
_SCALARIZATION_POLICIES = {"weighted_sum", "weighted_tchebycheff", "lexicographic"}
_WEIGHTED_POLICIES = {"weighted_sum", "weighted_tchebycheff"}


def _require_object(value: Any, *, field_name: str) -> JSONDict:
    if not isinstance(value, dict):
        raise ValueError(f"{field_name} must be an object")
    return value


def _require_string(value: Any, *, field_name: str) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{field_name} must be a string")
    out = value.strip()
    if not out:
        raise ValueError(f"{field_name} must be a non-empty string")
    return out


def _require_finite_number(value: Any, *, field_name: str) -> float:
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        raise ValueError(f"{field_name} must be a finite number")
    out = float(value)
    if not math.isfinite(out):
        raise ValueError(f"{field_name} must be a finite number")
    return out


def _normalize_objective(raw: Any, *, field_name: str) -> JSONDict:
    objective = _require_object(raw, field_name=field_name)
    name = _require_string(objective.get("name"), field_name=f"{field_name}.name")
    direction = _require_string(
        objective.get("direction"), field_name=f"{field_name}.direction"
    ).lower()
    if direction not in _DIRECTIONS:
        raise ValueError(f"{field_name}.direction must be one of {sorted(_DIRECTIONS)}")

    tolerance = _require_finite_number(
        objective.get("tolerance", 0.0),
        field_name=f"{field_name}.tolerance",
    )
    failure_handling = _require_string(
        objective.get("failure_handling", "record_and_continue"),
        field_name=f"{field_name}.failure_handling",
    )
    return {
        "name": name,
        "direction": direction,
        "tolerance": tolerance,
        "failure_handling": failure_handling,
    }


def _normalize_weights(raw: Any, *, objective_names: list[str], field_name: str) -> JSONDict:
    weights = _require_object(raw, field_name=field_name)
    expected = set(objective_names)
    received = set(weights)
    missing = sorted(expected - received)
    extra = sorted(received - expected)
    if missing or extra:
        details: list[str] = []
        if missing:
            details.append(f"missing keys {missing}")
        if extra:
            details.append(f"unexpected keys {extra}")
        joined = ", ".join(details)
        raise ValueError(f"{field_name} must match declared objective names exactly ({joined})")

    normalized: JSONDict = {}
    total = 0.0
    for name in objective_names:
        value = _require_finite_number(weights[name], field_name=f"{field_name}.{name}")
        if value <= 0.0:
            raise ValueError(f"{field_name}.{name} must be > 0")
        normalized[name] = value
        total += value

    return {name: normalized[name] / total for name in objective_names}


def _normalize_reference_point(
    raw: Any, *, objective_names: list[str], field_name: str
) -> JSONDict:
    reference = _require_object(raw, field_name=field_name)
    expected = set(objective_names)
    received = set(reference)
    missing = sorted(expected - received)
    extra = sorted(received - expected)
    if missing or extra:
        details: list[str] = []
        if missing:
            details.append(f"missing keys {missing}")
        if extra:
            details.append(f"unexpected keys {extra}")
        joined = ", ".join(details)
        raise ValueError(f"{field_name} must match declared objective names exactly ({joined})")

    return {
        name: _require_finite_number(reference[name], field_name=f"{field_name}.{name}")
        for name in objective_names
    }


def _normalize_scalarization(raw: Any, *, objectives: list[JSONDict]) -> JSONDict:
    if raw is None:
        return {"policy": "primary_only"}

    scalarization = _require_object(raw, field_name="objective_schema.scalarization")
    policy = _require_string(
        scalarization.get("policy"),
        field_name="objective_schema.scalarization.policy",
    ).lower()
    if policy not in _SCALARIZATION_POLICIES:
        raise ValueError(
            "objective_schema.scalarization.policy must be one of "
            f"{sorted(_SCALARIZATION_POLICIES)}"
        )

    objective_names = [str(objective["name"]) for objective in objectives]
    out: JSONDict = {"policy": policy}
    if policy in _WEIGHTED_POLICIES:
        out["weights"] = _normalize_weights(
            scalarization.get("weights"),
            objective_names=objective_names,
            field_name="objective_schema.scalarization.weights",
        )
        reference_point = scalarization.get("reference_point")
        if policy == "weighted_tchebycheff" and reference_point is not None:
            out["reference_point"] = _normalize_reference_point(
                reference_point,
                objective_names=objective_names,
                field_name="objective_schema.scalarization.reference_point",
            )
        elif reference_point is not None:
            raise ValueError(
                "objective_schema.scalarization.reference_point is only supported "
                "for policy 'weighted_tchebycheff'"
            )
        return out

    if "weights" in scalarization:
        raise ValueError(
            "objective_schema.scalarization.weights is only supported for weighted policies"
        )
    if "reference_point" in scalarization:
        raise ValueError(
            "objective_schema.scalarization.reference_point is only supported "
            "for policy 'weighted_tchebycheff'"
        )
    return out


def normalize_objective_schema(raw: Any) -> JSONDict:
    objective_cfg = _require_object(raw, field_name="objective_schema")
    primary = _normalize_objective(
        objective_cfg.get("primary_objective"),
        field_name="objective_schema.primary_objective",
    )

    secondary_raw = objective_cfg.get("secondary_objectives", [])
    if not isinstance(secondary_raw, list):
        raise ValueError("objective_schema.secondary_objectives must be a list")
    secondary = [
        _normalize_objective(
            item,
            field_name=f"objective_schema.secondary_objectives[{index}]",
        )
        for index, item in enumerate(secondary_raw)
    ]

    objectives = [primary, *secondary]
    names = [str(objective["name"]) for objective in objectives]
    duplicates = sorted({name for name in names if names.count(name) > 1})
    if duplicates:
        raise ValueError(
            f"objective_schema objective names must be unique; duplicates={duplicates}"
        )

    scalarization = _normalize_scalarization(
        objective_cfg.get("scalarization"),
        objectives=objectives,
    )
    return {
        "primary_objective": primary,
        "secondary_objectives": secondary,
        "objectives": objectives,
        "objective_names": names,
        "scalarization": scalarization,
    }
