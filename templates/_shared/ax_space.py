"""Exact, dependency-free public-value codec for the Ax contract2 subset."""

from __future__ import annotations

import copy
import importlib.util
import json
import math
from pathlib import Path
from typing import Any, cast

JSONDict = dict[str, Any]


def _load(name: str) -> Any:
    spec = importlib.util.spec_from_file_location(
        f"looptimum_ax_space_{name}", Path(__file__).with_name(f"{name}.py")
    )
    if spec is None or spec.loader is None:
        raise ImportError(f"Missing sibling module {name}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


SPACE = _load("search_space")
CONSTRAINTS = _load("constraints")


def key(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


def _generation_choices(
    parameters: list[JSONDict],
    parents: dict[str, tuple[str, Any]],
    constraints: JSONDict | None,
) -> list[JSONDict] | None:
    """Prune finite values only when activation proves every other forbidden term.

    Keep the public codec intact, including categorical token positions. Values
    with dependent children and exclusions that empty a domain retain bounded
    post-filtering; removing them would require a different hierarchy.
    """
    generated = copy.deepcopy(parameters)
    for original, parameter in zip(parameters, generated, strict=True):
        name = original.get("raw_name")
        if name is None or "values" not in original:
            continue
        ancestors: JSONDict = {}
        ancestor = name
        while ancestor in parents:
            ancestor, value = parents[ancestor]
            ancestors[ancestor] = value
        raw_values: list[Any] = (
            original["raw_values"] if "raw_values" in original else original["values"]
        )
        choices = dict(zip((key(value) for value in original["values"]), raw_values, strict=True))
        controlling = {key(item["value"]) for item in original.get("dependents", [])}
        for rule in (constraints or {}).get("forbidden_combinations", []):
            when = rule["when"]
            if name not in when or any(
                other not in ancestors
                or key(ancestors[other]) not in {key(value) for value in allowed}
                for other, allowed in when.items()
                if other != name
            ):
                continue
            forbidden = {key(value) for value in when[name]}
            kept = [
                value
                for value in parameter["values"]
                if key(value) in controlling or key(choices[key(value)]) not in forbidden
            ]
            if kept:
                parameter["values"] = kept
    return generated if generated != parameters else None


def build_codec(params: list[JSONDict], constraints: JSONDict | None) -> JSONDict:
    definitions = [
        {name: value for name, value in param.items() if name != "description"}
        for param in CONSTRAINTS.apply_bound_tightening(params, constraints)
    ]
    by_name = {p["name"]: p for p in definitions}
    aliases = {p["name"]: f"p{i}" for i, p in enumerate(definitions)}
    children: dict[str, list[str]] = {}
    parents: dict[str, tuple[str, Any]] = {}
    for param in definitions:
        when = param.get("when", {})
        if not when:
            continue
        if len(when) != 1:
            raise ValueError("Ax contract2 supports finite trees, not multiparent conditional DAGs")
        parent, values = next(iter(when.items()))
        if len(values) != 1:
            raise ValueError(
                "Ax finite-tree dependents need one parent value; shared branches are unsupported"
            )
        if parent not in by_name:
            raise ValueError("Unknown conditional parent")
        parents[param["name"]] = (parent, values[0])
        children.setdefault(parent, []).append(param["name"])
    ordered: list[str] = []
    active: set[str] = set()

    def visit(name: str) -> None:
        if name in active:
            raise ValueError("Ax conditional tree contains a cycle")
        if name in ordered:
            return
        active.add(name)
        if name in parents:
            visit(parents[name][0])
        active.remove(name)
        ordered.append(name)

    for param in definitions:
        visit(param["name"])
    parameters = []
    for param in definitions:
        name, kind = param["name"], param["type"]
        entry: JSONDict = {"name": aliases[name], "raw_name": name, "parameter_type": kind}
        if kind == "categorical":
            entry.update(
                parameter_type="str",
                values=[f"c{i}" for i in range(len(param["choices"]))],
                raw_values=list(param["choices"]),
            )
        elif kind == "bool":
            entry["values"] = [False, True]
        elif name in children:
            lo, hi = param["bounds"]
            if lo == hi:
                entry["values"] = [lo]
            elif kind == "int" and param.get("scale", "linear") == "linear" and hi - lo + 1 <= 256:
                entry["values"] = list(range(lo, hi + 1))
            else:
                raise ValueError(
                    "Ax tree parents must have a bounded finite domain (at most 256 linear integers)"
                )
        else:
            entry["bounds"] = list(param["bounds"])
            if param.get("scale") == "log":
                entry["scaling"] = "log"
        parameters.append(entry)
    lookup = {p["raw_name"]: p for p in parameters}

    def encode_value(param: JSONDict, value: Any) -> Any:
        if "raw_values" in param:
            matches = [
                i for i, choice in enumerate(param["raw_values"]) if key(choice) == key(value)
            ]
            if not matches:
                raise ValueError("Conditional parent value is not a declared typed choice")
            return param["values"][matches[0]]
        if "values" not in param or key(value) not in {key(v) for v in param["values"]}:
            raise ValueError("Conditional parent value is not in its finite domain")
        return value

    for child, (parent, value) in parents.items():
        entry = lookup[parent]
        encoded = encode_value(entry, value)
        dependent = next(
            (d for d in entry.get("dependents", []) if key(d["value"]) == key(encoded)), None
        )
        if dependent is None:
            dependent = {"value": encoded, "children": []}
            entry.setdefault("dependents", []).append(dependent)
        dependent["children"].append(aliases[child])
    dummy = None
    if parents:
        dummy = "root"
        parameters.insert(
            0,
            {
                "name": dummy,
                "parameter_type": "str",
                "values": ["all"],
                "dependents": [
                    {
                        "value": "all",
                        "children": [aliases[name] for name in ordered if name not in parents],
                    }
                ],
            },
        )
    linear = []
    for rule in (constraints or {}).get("linear_inequalities", []):
        terms = []
        constant = 0.0
        for term in rule["terms"]:
            param = by_name[term["param"]]
            if param.get("when"):
                raise ValueError(
                    "Ax does not support linear rules referencing conditional/inactive parameters"
                )
            coefficient = term["coefficient"]
            lo, hi = param["bounds"]
            if lo == hi:
                constant += coefficient * lo
            else:
                if param.get("scale") == "log" and coefficient != 0:
                    raise ValueError(
                        "Ax cannot exactly translate raw-domain linear rules on log-scaled parameters"
                    )
                if "values" in lookup[param["name"]] and coefficient != 0:
                    raise ValueError("Ax linear terms cannot reference enumerated tree controllers")
                if coefficient != 0:
                    terms.append(f"({coefficient!r}) * {aliases[param['name']]}")
        bound = rule["rhs"] - constant
        if not math.isfinite(bound):
            raise ValueError("Ax linear rule has nonfinite arithmetic")
        if terms:
            linear.append(f"{' + '.join(terms)} {rule['operator']} {bound!r}")
        elif not CONSTRAINTS.evaluate_constraints(
            {term["param"]: by_name[term["param"]]["bounds"][0] for term in rule["terms"]},
            {"linear_inequalities": [rule]},
        )["feasible"]:
            raise ValueError("No feasible point satisfies the fixed linear rule")
    codec = {
        "codec_version": 1,
        "definitions": definitions,
        "parameters": parameters,
        "order": ordered,
        "dummy_root": dummy,
        "parameter_constraints": linear,
        "constraints": constraints,
    }
    generation = _generation_choices(parameters, parents, constraints)
    if generation is not None:
        codec["generation_parameters"] = generation
    return codec


def encode(codec: JSONDict, values: JSONDict) -> JSONDict:
    if not isinstance(values, dict):
        raise ValueError("Ax public parameterization must be an object")
    definitions = codec["definitions"]
    expected = {p["name"] for p in SPACE.active_parameters(definitions, values)}
    if set(values) != expected:
        raise ValueError("Ax parameterization must contain exactly the active public parameters")
    out = {codec["dummy_root"]: "all"} if codec["dummy_root"] else {}
    for param in codec["parameters"]:
        raw_name = param.get("raw_name")
        if raw_name not in expected:
            continue
        value = values[raw_name]
        if "raw_values" in param:
            matches = [
                i for i, choice in enumerate(param["raw_values"]) if key(choice) == key(value)
            ]
            if not matches:
                raise ValueError(f"Invalid typed choice for {raw_name!r}")
            value = param["values"][matches[0]]
        else:
            kind = param["parameter_type"]
            valid = type(value) is {"bool": bool, "int": int, "float": float, "str": str}[kind] or (
                kind == "float" and type(value) is int
            )
            if not valid or (isinstance(value, float) and not math.isfinite(value)):
                raise ValueError(f"Invalid raw parameter type for {raw_name!r}")
            if kind == "float":
                value = float(value)
            if "values" in param and key(value) not in {key(v) for v in param["values"]}:
                raise ValueError(f"Parameter {raw_name!r} is not a declared value")
            if "bounds" in param and not param["bounds"][0] <= value <= param["bounds"][1]:
                raise ValueError(f"Parameter {raw_name!r} is outside its bounds")
        out[param["name"]] = value
    return out


def decode(codec: JSONDict, values: JSONDict) -> JSONDict:
    if not isinstance(values, dict):
        raise ValueError("Ax encoded parameterization must be an object")
    by_name = {p.get("raw_name"): p for p in codec["parameters"] if "raw_name" in p}
    raw = {}
    for name in codec["order"]:
        param = by_name[name]
        if param["name"] not in values:
            continue
        value = values[param["name"]]
        if "raw_values" in param:
            if value not in param["values"] or not isinstance(value, str):
                raise ValueError("Ax returned an unknown categorical token")
            value = param["raw_values"][param["values"].index(value)]
        elif param["parameter_type"] == "float" and type(value) is int:
            value = float(value)
        raw[name] = value
    if encode(codec, raw) != values:
        raise ValueError("Ax encoded candidate failed its typed/active-field round trip")
    return raw


def feasible(codec: JSONDict, values: JSONDict) -> JSONDict:
    return cast(JSONDict, CONSTRAINTS.evaluate_constraints(values, codec.get("constraints") or {}))


def finite_points(codec: JSONDict, *, limit: int = 65536) -> set[str] | None:
    """Enumerate feasible active parameterizations, or use bounded generation."""
    definitions = {p["name"]: p for p in codec["definitions"]}
    points: set[str] = set()
    visits = 0

    def walk(index: int, values: JSONDict) -> None:
        nonlocal visits
        visits += 1
        if visits > 4 * limit or len(points) > limit:
            raise OverflowError
        if not feasible(codec, values)["feasible"]:
            return
        if index == len(codec["order"]):
            points.add(key(values))
            if len(points) > limit:
                raise OverflowError
            return
        param = definitions[codec["order"][index]]
        if not SPACE.is_parameter_active(param, values):
            walk(index + 1, values)
            return
        kind = param["type"]
        if kind == "categorical":
            choices = param["choices"]
        elif kind == "bool":
            choices = [False, True]
        else:
            lo, hi = param["bounds"]
            if lo == hi:
                choices = [lo]
            elif kind == "int":
                if hi - lo + 1 > limit:
                    raise OverflowError
                choices = range(lo, hi + 1)
            else:
                raise OverflowError
        for value in choices:
            walk(index + 1, {**values, param["name"]: value})

    try:
        walk(0, {})
    except OverflowError:
        return None
    return points


def check_capacity(
    codec: JSONDict, rows: list[JSONDict], count: int, *, allow_completed_repeats: bool
) -> None:
    if count == 0:
        return
    points = finite_points(codec)
    if points is None:
        return
    blocked = {
        key(row["params"])
        for row in rows
        if row["status"] == "pending" or not allow_completed_repeats
    }
    available = len(points - blocked)
    if available < count:
        raise ValueError(
            f"Ax finite feasible space has {available} available unique points; cannot allocate complete batch of {count}"
        )
