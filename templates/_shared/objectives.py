from __future__ import annotations

import math
from typing import Any

JSONDict = dict[str, Any]

_DIRECTIONS = {"minimize", "maximize"}
_SCALARIZATION_POLICIES = {"weighted_sum", "weighted_tchebycheff", "lexicographic"}
_WEIGHTED_POLICIES = {"weighted_sum", "weighted_tchebycheff"}
_PRIMARY_ONLY_POLICY = "primary_only"


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


def primary_objective_name(objective_cfg: JSONDict) -> str:
    primary = _require_object(
        objective_cfg.get("primary_objective"),
        field_name="objective_cfg.primary_objective",
    )
    return _require_string(primary.get("name"), field_name="objective_cfg.primary_objective.name")


def primary_objective_direction(objective_cfg: JSONDict) -> str:
    primary = _require_object(
        objective_cfg.get("primary_objective"),
        field_name="objective_cfg.primary_objective",
    )
    direction = _require_string(
        primary.get("direction"),
        field_name="objective_cfg.primary_objective.direction",
    ).lower()
    if direction not in _DIRECTIONS:
        raise ValueError(f"objective_cfg.primary_objective.direction must be one of {_DIRECTIONS}")
    return direction


def objective_descriptors(objective_cfg: JSONDict) -> list[JSONDict]:
    raw = objective_cfg.get("objectives")
    if not isinstance(raw, list):
        raise ValueError("objective_cfg.objectives must be a list")
    out: list[JSONDict] = []
    for index, item in enumerate(raw):
        out.append(_require_object(item, field_name=f"objective_cfg.objectives[{index}]"))
    return out


def objective_names(objective_cfg: JSONDict) -> list[str]:
    return [str(objective["name"]) for objective in objective_descriptors(objective_cfg)]


def scalarization_policy(objective_cfg: JSONDict) -> str:
    scalarization = _require_object(
        objective_cfg.get("scalarization"),
        field_name="objective_cfg.scalarization",
    )
    policy = _require_string(
        scalarization.get("policy"),
        field_name="objective_cfg.scalarization.policy",
    ).lower()
    valid = {*_SCALARIZATION_POLICIES, _PRIMARY_ONLY_POLICY}
    if policy not in valid:
        raise ValueError(f"objective_cfg.scalarization.policy must be one of {sorted(valid)}")
    return policy


def scalarized_direction(objective_cfg: JSONDict) -> str:
    policy = scalarization_policy(objective_cfg)
    if policy in _WEIGHTED_POLICIES:
        return "minimize"
    return primary_objective_direction(objective_cfg)


def best_objective_name(objective_cfg: JSONDict) -> str:
    policy = scalarization_policy(objective_cfg)
    if policy == _PRIMARY_ONLY_POLICY or policy == "lexicographic":
        return primary_objective_name(objective_cfg)
    return "scalarized"


def _numeric_objective_value(raw: Any, *, field_name: str) -> float:
    return _require_finite_number(raw, field_name=field_name)


def canonical_objective_vector(raw_objectives: Any, objective_cfg: JSONDict) -> JSONDict:
    objectives = _require_object(raw_objectives, field_name="objectives")
    names = objective_names(objective_cfg)
    missing = [name for name in names if name not in objectives]
    if missing:
        raise ValueError(f"objectives missing configured names {missing}")

    extras = sorted(set(objectives) - set(names))
    if extras:
        raise ValueError(f"objectives include unknown names {extras}")

    out: JSONDict = {}
    for name in names:
        out[name] = _numeric_objective_value(
            objectives.get(name),
            field_name=f"objectives.{name}",
        )
    return out


def _transformed_value(value: float, *, direction: str) -> float:
    return value if direction == "minimize" else -value


def lexicographic_key(raw_objectives: Any, objective_cfg: JSONDict) -> tuple[float, ...]:
    vector = canonical_objective_vector(raw_objectives, objective_cfg)
    return tuple(
        _transformed_value(
            float(vector[str(objective["name"])]), direction=str(objective["direction"])
        )
        for objective in objective_descriptors(objective_cfg)
    )


def scalarize_objectives(raw_objectives: Any, objective_cfg: JSONDict) -> float:
    vector = canonical_objective_vector(raw_objectives, objective_cfg)
    policy = scalarization_policy(objective_cfg)

    if policy == _PRIMARY_ONLY_POLICY or policy == "lexicographic":
        return float(vector[primary_objective_name(objective_cfg)])

    scalarization = _require_object(
        objective_cfg.get("scalarization"),
        field_name="objective_cfg.scalarization",
    )
    weights = _require_object(
        scalarization.get("weights"),
        field_name="objective_cfg.scalarization.weights",
    )

    transformed: dict[str, float] = {}
    for objective in objective_descriptors(objective_cfg):
        name = str(objective["name"])
        transformed[name] = _transformed_value(
            float(vector[name]),
            direction=str(objective["direction"]),
        )

    if policy == "weighted_sum":
        return sum(
            float(weights[name]) * transformed[name] for name in objective_names(objective_cfg)
        )

    if policy == "weighted_tchebycheff":
        reference_raw = scalarization.get("reference_point")
        if reference_raw is None:
            reference_raw = {name: 0.0 for name in objective_names(objective_cfg)}
        reference = _require_object(
            reference_raw,
            field_name="objective_cfg.scalarization.reference_point",
        )
        distances: list[float] = []
        for objective in objective_descriptors(objective_cfg):
            name = str(objective["name"])
            ref_value = _numeric_objective_value(
                reference.get(name, 0.0),
                field_name=f"objective_cfg.scalarization.reference_point.{name}",
            )
            transformed_ref = _transformed_value(ref_value, direction=str(objective["direction"]))
            distances.append(float(weights[name]) * abs(transformed[name] - transformed_ref))
        return max(distances)

    raise ValueError(f"Unsupported scalarization policy '{policy}'")


def best_rank_key(
    raw_objectives: Any,
    objective_cfg: JSONDict,
    *,
    trial_id: int | None = None,
) -> tuple[Any, ...]:
    scalar_value = scalarize_objectives(raw_objectives, objective_cfg)
    direction = scalarized_direction(objective_cfg)
    scalar_key = scalar_value if direction == "minimize" else -scalar_value
    key: list[Any] = [scalar_key, lexicographic_key(raw_objectives, objective_cfg)]
    if trial_id is not None:
        key.append(int(trial_id))
    return tuple(key)


def build_best_record(
    observation: JSONDict,
    objective_cfg: JSONDict,
    *,
    updated_at: float,
) -> JSONDict:
    vector = canonical_objective_vector(observation.get("objectives", {}), objective_cfg)
    record: JSONDict = {
        "trial_id": int(observation["trial_id"]),
        "objective_name": best_objective_name(objective_cfg),
        "objective_value": float(scalarize_objectives(vector, objective_cfg)),
        "updated_at": float(updated_at),
    }
    if (
        len(objective_names(objective_cfg)) > 1
        or scalarization_policy(objective_cfg) != _PRIMARY_ONLY_POLICY
    ):
        record["scalarization_policy"] = scalarization_policy(objective_cfg)
        record["objective_vector"] = vector
    return record


def objective_config_snapshot(objective_cfg: JSONDict) -> JSONDict:
    primary = _require_object(
        objective_cfg.get("primary_objective"),
        field_name="objective_cfg.primary_objective",
    )
    secondary = [
        _require_object(item, field_name=f"objective_cfg.secondary_objectives[{index}]")
        for index, item in enumerate(objective_cfg.get("secondary_objectives", []))
    ]
    objectives = [
        _require_object(item, field_name=f"objective_cfg.objectives[{index}]")
        for index, item in enumerate(objective_cfg.get("objectives", []))
    ]
    scalarization = _require_object(
        objective_cfg.get("scalarization"),
        field_name="objective_cfg.scalarization",
    )
    return {
        "primary_objective": dict(primary),
        "secondary_objectives": [dict(item) for item in secondary],
        "objectives": [dict(item) for item in objectives],
        "objective_names": objective_names(objective_cfg),
        "scalarization": dict(scalarization),
    }


def nullable_objective_vector(raw_objectives: Any, objective_cfg: JSONDict) -> JSONDict:
    names = objective_names(objective_cfg)
    if raw_objectives is None:
        return {name: None for name in names}

    objectives = _require_object(raw_objectives, field_name="objectives")
    missing = [name for name in names if name not in objectives]
    if missing:
        raise ValueError(f"objectives missing configured names {missing}")

    extras = sorted(set(objectives) - set(names))
    if extras:
        raise ValueError(f"objectives include unknown names {extras}")

    out: JSONDict = {}
    for name in names:
        value = objectives.get(name)
        out[name] = (
            None
            if value is None
            else _numeric_objective_value(value, field_name=f"objectives.{name}")
        )
    return out


def build_objective_metadata(raw_objectives: Any, objective_cfg: JSONDict) -> JSONDict:
    vector = nullable_objective_vector(raw_objectives, objective_cfg)
    primary_name = primary_objective_name(objective_cfg)
    metadata: JSONDict = {
        "objective_name": primary_name,
        "objective_value": vector[primary_name],
        "objective_vector": vector,
        "scalarized_objective": None,
    }

    if all(value is not None for value in vector.values()):
        canonical = {name: float(value) for name, value in vector.items()}
        metadata["scalarized_objective"] = float(scalarize_objectives(canonical, objective_cfg))

    if (
        len(objective_names(objective_cfg)) > 1
        or scalarization_policy(objective_cfg) != _PRIMARY_ONLY_POLICY
    ):
        metadata["scalarization_policy"] = scalarization_policy(objective_cfg)
    return metadata


def _transformed_vector(raw_objectives: Any, objective_cfg: JSONDict) -> JSONDict:
    vector = canonical_objective_vector(raw_objectives, objective_cfg)
    return {
        str(objective["name"]): _transformed_value(
            float(vector[str(objective["name"])]),
            direction=str(objective["direction"]),
        )
        for objective in objective_descriptors(objective_cfg)
    }


def _dominates(left: JSONDict, right: JSONDict, objective_cfg: JSONDict) -> bool:
    transformed_left = _transformed_vector(left, objective_cfg)
    transformed_right = _transformed_vector(right, objective_cfg)
    names = objective_names(objective_cfg)
    return all(
        float(transformed_left[name]) <= float(transformed_right[name]) for name in names
    ) and any(float(transformed_left[name]) < float(transformed_right[name]) for name in names)


def pareto_front_records(records: list[JSONDict], objective_cfg: JSONDict) -> list[JSONDict]:
    prepared: list[tuple[JSONDict, JSONDict]] = []
    for index, record in enumerate(records):
        if not isinstance(record, dict):
            raise ValueError(f"records[{index}] must be an object")
        trial_id = record.get("trial_id")
        if not isinstance(trial_id, int):
            raise ValueError(f"records[{index}].trial_id must be an integer")
        prepared.append(
            (record, canonical_objective_vector(record.get("objectives"), objective_cfg))
        )

    frontier: list[tuple[JSONDict, JSONDict]] = []
    for index, (record, vector) in enumerate(prepared):
        dominated = any(
            _dominates(other_vector, vector, objective_cfg)
            for other_index, (_, other_vector) in enumerate(prepared)
            if other_index != index
        )
        if not dominated:
            frontier.append((record, vector))

    frontier.sort(
        key=lambda item: best_rank_key(
            item[1],
            objective_cfg,
            trial_id=int(item[0]["trial_id"]),
        )
    )
    return [record for record, _ in frontier]
