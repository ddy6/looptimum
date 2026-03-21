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


def _runtime_numeric_param(param: JSONDict, *, context: str) -> None:
    param_type = str(param.get("type"))
    if param_type not in _NUMERIC_PARAMETER_TYPES:
        raise ValueError(
            f"Parameter '{param.get('name')}' uses type '{param_type}', which is not supported by {context} yet"
        )
    scale = str(param.get("scale", "linear"))
    if scale != "linear":
        raise ValueError(
            f"Parameter '{param.get('name')}' uses scale '{scale}', which is not supported by {context} yet"
        )


def _sample_log_scaled_value(
    rng: random.Random, lo: int | float, hi: int | float, param_type: str
) -> int | float:
    sampled = math.exp(rng.uniform(math.log(float(lo)), math.log(float(hi))))
    if param_type == "int":
        return min(int(hi), max(int(lo), int(round(sampled))))
    return sampled


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


def surrogate_numeric_only_capability_gap(params: list[JSONDict]) -> JSONDict | None:
    for param in params:
        param_name = str(param.get("name"))
        param_type = str(param.get("type"))
        if param_type not in _NUMERIC_PARAMETER_TYPES:
            return {
                "fallback_reason": "search_space_requires_workstream1_model_encoding",
                "fallback_param": param_name,
                "fallback_param_type": param_type,
            }
        scale = str(param.get("scale", "linear"))
        if scale != "linear":
            return {
                "fallback_reason": "search_space_requires_workstream1_model_encoding",
                "fallback_param": param_name,
                "fallback_param_type": param_type,
                "fallback_param_scale": scale,
            }
    return None


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
    total = 0.0
    for param in params:
        _runtime_numeric_param(param, context="numeric distance scoring")
        lo, hi = map(float, param["bounds"])
        span = max(hi - lo, 1e-12)
        total += ((float(a[param["name"]]) - float(b[param["name"]])) / span) ** 2
    return math.sqrt(total)


def normalize_numeric_point(vec: JSONDict, params: list[JSONDict]) -> list[float]:
    out: list[float] = []
    for param in params:
        _runtime_numeric_param(param, context="numeric vector normalization")
        lo, hi = map(float, param["bounds"])
        span = max(hi - lo, 1e-12)
        out.append((float(vec[param["name"]]) - lo) / span)
    return out


def denormalize_numeric_point(vals: list[float], params: list[JSONDict]) -> JSONDict:
    out: JSONDict = {}
    for idx, param in enumerate(params):
        _runtime_numeric_param(param, context="numeric vector denormalization")
        lo, hi = map(float, param["bounds"])
        value = lo + float(vals[idx]) * (hi - lo)
        out[param["name"]] = int(round(value)) if param["type"] == "int" else float(value)
    return out
