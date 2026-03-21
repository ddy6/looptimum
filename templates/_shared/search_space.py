from __future__ import annotations

import json
import math
import random
from typing import Any

JSONDict = dict[str, Any]
_NUMERIC_PARAMETER_TYPES = {"float", "int"}
_SUPPORTED_PARAMETER_TYPES = _NUMERIC_PARAMETER_TYPES | {"bool", "categorical"}
_SUPPORTED_NUMERIC_SCALES = {"linear", "log"}


def _is_finite_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def _normalize_description(param: JSONDict, idx: int) -> str | None:
    description = param.get("description")
    if description is None:
        return None
    if not isinstance(description, str):
        raise ValueError(f"parameter_space.parameters[{idx}].description must be a string")
    return description


def _normalize_numeric_param(idx: int, name: str, param: JSONDict, param_type: str) -> JSONDict:
    if "choices" in param:
        raise ValueError(
            f"parameter_space.parameters[{idx}] ({name}) must not define 'choices' for type '{param_type}'"
        )

    bounds = param.get("bounds")
    if not isinstance(bounds, list) or len(bounds) != 2:
        raise ValueError(
            f"parameter_space.parameters[{idx}] ({name}) must define 'bounds' with exactly two values"
        )

    lo_raw, hi_raw = bounds
    lo: int | float
    hi: int | float
    if param_type == "int":
        if not (
            isinstance(lo_raw, int)
            and not isinstance(lo_raw, bool)
            and isinstance(hi_raw, int)
            and not isinstance(hi_raw, bool)
        ):
            raise ValueError(
                f"parameter_space.parameters[{idx}] ({name}) must use integer bounds for type 'int'"
            )
        lo, hi = int(lo_raw), int(hi_raw)
    else:
        if not _is_finite_number(lo_raw) or not _is_finite_number(hi_raw):
            raise ValueError(
                f"parameter_space.parameters[{idx}] ({name}) must use finite numeric bounds for type 'float'"
            )
        lo, hi = float(lo_raw), float(hi_raw)

    if lo > hi:
        raise ValueError(
            f"parameter_space.parameters[{idx}] ({name}) must satisfy bounds[0] <= bounds[1]"
        )

    scale = param.get("scale", "linear")
    if not isinstance(scale, str) or scale not in _SUPPORTED_NUMERIC_SCALES:
        raise ValueError(
            f"parameter_space.parameters[{idx}] ({name}) must use scale 'linear' or 'log'"
        )
    if scale == "log" and (float(lo) <= 0.0 or float(hi) <= 0.0):
        raise ValueError(
            f"parameter_space.parameters[{idx}] ({name}) must use strictly positive bounds for log scale"
        )

    return {
        "name": name,
        "type": param_type,
        "bounds": [lo, hi],
        "scale": scale,
        "encoding": "scalar",
        "encoded_size": 1,
    }


def _normalize_bool_param(idx: int, name: str, param: JSONDict) -> JSONDict:
    if "bounds" in param:
        raise ValueError(f"parameter_space.parameters[{idx}] ({name}) must not define 'bounds'")
    if "choices" in param:
        raise ValueError(f"parameter_space.parameters[{idx}] ({name}) must not define 'choices'")
    if "scale" in param:
        raise ValueError(f"parameter_space.parameters[{idx}] ({name}) must not define 'scale'")
    return {
        "name": name,
        "type": "bool",
        "choices": [False, True],
        "encoding": "binary",
        "encoded_size": 1,
    }


def _choice_key(choice: str | int | float) -> str:
    return json.dumps(choice, sort_keys=True, separators=(",", ":"))


def _normalize_categorical_param(idx: int, name: str, param: JSONDict) -> JSONDict:
    if "bounds" in param:
        raise ValueError(f"parameter_space.parameters[{idx}] ({name}) must not define 'bounds'")
    if "scale" in param:
        raise ValueError(f"parameter_space.parameters[{idx}] ({name}) must not define 'scale'")

    raw_choices = param.get("choices")
    if not isinstance(raw_choices, list) or not raw_choices:
        raise ValueError(
            f"parameter_space.parameters[{idx}] ({name}) must define non-empty 'choices'"
        )

    choices: list[str | int | float] = []
    seen_choices: set[str] = set()
    for choice_idx, raw_choice in enumerate(raw_choices):
        if isinstance(raw_choice, str):
            choice = raw_choice
        elif _is_finite_number(raw_choice):
            choice = raw_choice
        else:
            raise ValueError(
                f"parameter_space.parameters[{idx}].choices[{choice_idx}] must be a string or finite number"
            )

        rendered = _choice_key(choice)
        if rendered in seen_choices:
            raise ValueError(
                f"parameter_space.parameters[{idx}] ({name}) must not contain duplicate categorical choices"
            )
        seen_choices.add(rendered)
        choices.append(choice)

    return {
        "name": name,
        "type": "categorical",
        "choices": choices,
        "encoding": "one_hot",
        "encoded_size": len(choices),
    }


def _sample_log_scaled_value(
    rng: random.Random, lo: int | float, hi: int | float, param_type: str
) -> int | float:
    sampled = math.exp(rng.uniform(math.log(float(lo)), math.log(float(hi))))
    if param_type == "int":
        return min(int(hi), max(int(lo), int(round(sampled))))
    return sampled


def _clamp_unit_interval(value: float) -> float:
    return min(1.0, max(0.0, value))


def _require_supported_choice(value: Any, *, param_name: str) -> str:
    if isinstance(value, str) or _is_finite_number(value):
        return _choice_key(value)
    raise ValueError(
        f"Parameter '{param_name}' must use a string or finite number categorical value"
    )


def _normalize_numeric_value(value: Any, param: JSONDict) -> float:
    param_name = str(param["name"])
    param_type = str(param["type"])
    if param_type == "int":
        if (
            isinstance(value, bool)
            or not isinstance(value, (int, float))
            or not float(value).is_integer()
        ):
            raise ValueError(f"Parameter '{param_name}' must use an integer value")
        numeric_value = float(value)
    elif param_type == "float":
        if not _is_finite_number(value):
            raise ValueError(f"Parameter '{param_name}' must use a finite numeric value")
        numeric_value = float(value)
    else:  # pragma: no cover - guarded by callers
        raise ValueError(f"Unsupported numeric parameter type: {param_type}")

    lo, hi = map(float, param["bounds"])
    scale = str(param.get("scale", "linear"))
    if scale == "linear":
        span = hi - lo
        if abs(span) < 1e-12:
            return 0.0
        return _clamp_unit_interval((numeric_value - lo) / span)
    if scale == "log":
        if numeric_value <= 0.0:
            raise ValueError(f"Parameter '{param_name}' must be strictly positive for log scale")
        log_lo = math.log(lo)
        log_hi = math.log(hi)
        span = log_hi - log_lo
        if abs(span) < 1e-12:
            return 0.0
        return _clamp_unit_interval((math.log(numeric_value) - log_lo) / span)
    raise ValueError(f"Unsupported numeric scale: {scale}")


def _denormalize_numeric_value(value: float, param: JSONDict) -> int | float:
    lo, hi = map(float, param["bounds"])
    unit = _clamp_unit_interval(float(value))
    scale = str(param.get("scale", "linear"))
    if scale == "linear":
        raw_value = lo if abs(hi - lo) < 1e-12 else lo + unit * (hi - lo)
    elif scale == "log":
        log_lo = math.log(lo)
        log_hi = math.log(hi)
        raw_value = (
            lo if abs(log_hi - log_lo) < 1e-12 else math.exp(log_lo + unit * (log_hi - log_lo))
        )
    else:  # pragma: no cover - guarded by normalize_search_space
        raise ValueError(f"Unsupported numeric scale: {scale}")
    if str(param["type"]) == "int":
        return min(int(hi), max(int(lo), int(round(raw_value))))
    return float(raw_value)


def _categorical_choice_index(value: Any, param: JSONDict) -> int:
    rendered = _require_supported_choice(value, param_name=str(param["name"]))
    for idx, choice in enumerate(param["choices"]):
        if _choice_key(choice) == rendered:
            return idx
    raise ValueError(
        f"Parameter '{param['name']}' must use one of the configured categorical choices"
    )


def normalize_search_space(space_cfg: JSONDict) -> list[JSONDict]:
    params = space_cfg.get("parameters", [])
    if not params:
        raise ValueError("parameter_space.json must define 'parameters'")
    if not isinstance(params, list):
        raise ValueError("parameter_space.parameters must be a list")

    out: list[JSONDict] = []
    seen_names: set[str] = set()
    for idx, param in enumerate(params):
        if not isinstance(param, dict):
            raise ValueError(f"parameter_space.parameters[{idx}] must be an object")

        name = param.get("name")
        if not isinstance(name, str) or not name:
            raise ValueError(f"parameter_space.parameters[{idx}].name must be a non-empty string")
        if name in seen_names:
            raise ValueError(f"parameter_space.parameters contains duplicate name '{name}'")

        param_type = param.get("type")
        if not isinstance(param_type, str) or param_type not in _SUPPORTED_PARAMETER_TYPES:
            raise ValueError(
                f"parameter_space.parameters[{idx}] ({name}) must use a supported type in {sorted(_SUPPORTED_PARAMETER_TYPES)}"
            )

        description = _normalize_description(param, idx)
        if param_type in _NUMERIC_PARAMETER_TYPES:
            normalized = _normalize_numeric_param(idx, name, param, param_type)
        elif param_type == "bool":
            normalized = _normalize_bool_param(idx, name, param)
        else:
            normalized = _normalize_categorical_param(idx, name, param)

        if description is not None:
            normalized["description"] = description
        out.append(normalized)
        seen_names.add(name)
    return out


def sample_random_point(rng: random.Random, params: list[JSONDict]) -> JSONDict:
    out: JSONDict = {}
    for param in params:
        param_name = str(param["name"])
        param_type = str(param["type"])
        if param_type in _NUMERIC_PARAMETER_TYPES:
            lo, hi = param["bounds"]
            scale = str(param.get("scale", "linear"))
            if scale == "linear":
                if param_type == "float":
                    out[param_name] = rng.uniform(float(lo), float(hi))
                elif param_type == "int":
                    out[param_name] = rng.randint(int(lo), int(hi))
                else:  # pragma: no cover - guarded by normalize_search_space
                    raise ValueError(f"Unsupported parameter type: {param_type}")
            elif scale == "log":
                out[param_name] = _sample_log_scaled_value(rng, lo, hi, param_type)
            else:  # pragma: no cover - guarded by normalize_search_space
                raise ValueError(f"Unsupported parameter scale: {scale}")
            continue

        if param_type == "bool":
            out[param_name] = bool(rng.randint(0, 1))
            continue
        if param_type == "categorical":
            choices = param["choices"]
            out[param_name] = choices[rng.randrange(len(choices))]
            continue
        raise ValueError(f"Unsupported parameter type: {param_type}")
    return out


def normalized_numeric_distance(a: JSONDict, b: JSONDict, params: list[JSONDict]) -> float:
    encoded_a = normalize_numeric_point(a, params)
    encoded_b = normalize_numeric_point(b, params)
    total = sum((left - right) ** 2 for left, right in zip(encoded_a, encoded_b))
    return math.sqrt(total)


def normalize_numeric_point(vec: JSONDict, params: list[JSONDict]) -> list[float]:
    out: list[float] = []
    for param in params:
        param_name = str(param["name"])
        param_type = str(param["type"])
        value = vec[param_name]
        if param_type in _NUMERIC_PARAMETER_TYPES:
            out.append(_normalize_numeric_value(value, param))
        elif param_type == "bool":
            if not isinstance(value, bool):
                raise ValueError(f"Parameter '{param_name}' must use a boolean value")
            out.append(1.0 if value else 0.0)
        elif param_type == "categorical":
            active_idx = _categorical_choice_index(value, param)
            for idx in range(len(param["choices"])):
                out.append(1.0 if idx == active_idx else 0.0)
        else:  # pragma: no cover - guarded by normalize_search_space
            raise ValueError(f"Unsupported parameter type: {param_type}")
    return out


def denormalize_numeric_point(vals: list[float], params: list[JSONDict]) -> JSONDict:
    out: JSONDict = {}
    offset = 0
    for param in params:
        param_name = str(param["name"])
        param_type = str(param["type"])
        encoded_size = int(param.get("encoded_size", 1))
        if param_type in _NUMERIC_PARAMETER_TYPES:
            if offset >= len(vals):
                raise ValueError(
                    "Encoded vector shorter than expected for numeric parameter decode"
                )
            out[param_name] = _denormalize_numeric_value(float(vals[offset]), param)
            offset += 1
        elif param_type == "bool":
            if offset >= len(vals):
                raise ValueError(
                    "Encoded vector shorter than expected for boolean parameter decode"
                )
            out[param_name] = _clamp_unit_interval(float(vals[offset])) >= 0.5
            offset += 1
        elif param_type == "categorical":
            segment = [float(value) for value in vals[offset : offset + encoded_size]]
            if len(segment) != encoded_size:
                raise ValueError(
                    "Encoded vector shorter than expected for categorical parameter decode"
                )
            best_idx = max(range(encoded_size), key=segment.__getitem__)
            out[param_name] = param["choices"][best_idx]
            offset += encoded_size
        else:  # pragma: no cover - guarded by normalize_search_space
            raise ValueError(f"Unsupported parameter type: {param_type}")
    if offset != len(vals):
        raise ValueError("Encoded vector longer than expected for parameter decode")
    return out
