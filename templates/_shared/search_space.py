from __future__ import annotations

import math
import random
from typing import Any

JSONDict = dict[str, Any]


def normalize_search_space(space_cfg: JSONDict) -> list[JSONDict]:
    params = space_cfg.get("parameters", [])
    if not params:
        raise ValueError("parameter_space.json must define 'parameters'")
    if not isinstance(params, list):
        raise ValueError("parameter_space.parameters must be a list")

    out: list[JSONDict] = []
    for idx, param in enumerate(params):
        if not isinstance(param, dict):
            raise ValueError(f"parameter_space.parameters[{idx}] must be an object")
        out.append(param)
    return out


def sample_random_point(rng: random.Random, params: list[JSONDict]) -> JSONDict:
    out: JSONDict = {}
    for param in params:
        lo, hi = param["bounds"]
        if param["type"] == "float":
            out[param["name"]] = rng.uniform(float(lo), float(hi))
        elif param["type"] == "int":
            out[param["name"]] = rng.randint(int(lo), int(hi))
        else:
            raise ValueError(f"Unsupported parameter type: {param['type']}")
    return out


def normalized_numeric_distance(a: JSONDict, b: JSONDict, params: list[JSONDict]) -> float:
    total = 0.0
    for param in params:
        lo, hi = map(float, param["bounds"])
        span = max(hi - lo, 1e-12)
        total += ((float(a[param["name"]]) - float(b[param["name"]])) / span) ** 2
    return math.sqrt(total)


def normalize_numeric_point(vec: JSONDict, params: list[JSONDict]) -> list[float]:
    out: list[float] = []
    for param in params:
        lo, hi = map(float, param["bounds"])
        span = max(hi - lo, 1e-12)
        out.append((float(vec[param["name"]]) - lo) / span)
    return out


def denormalize_numeric_point(vals: list[float], params: list[JSONDict]) -> JSONDict:
    out: JSONDict = {}
    for idx, param in enumerate(params):
        lo, hi = map(float, param["bounds"])
        value = lo + float(vals[idx]) * (hi - lo)
        out[param["name"]] = int(round(value)) if param["type"] == "int" else float(value)
    return out
