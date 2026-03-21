from __future__ import annotations

import json
import math
from typing import Any, cast

JSONDict = dict[str, Any]
ConstraintValue = bool | str | int | float
_NUMERIC_PARAMETER_TYPES = {"float", "int"}
_NUMERIC_COMPARISON_TOLERANCE = 1e-12


def _is_finite_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def _choice_key(value: ConstraintValue) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


def _params_by_name(params: list[JSONDict]) -> dict[str, JSONDict]:
    return {str(param["name"]): param for param in params}


def _canonicalize_match_value(
    raw_value: Any,
    param: JSONDict,
    *,
    context: str,
    enforce_bounds: bool,
) -> ConstraintValue:
    param_name = str(param["name"])
    param_type = str(param["type"])

    if param_type == "bool":
        if not isinstance(raw_value, bool):
            raise ValueError(f"{context}.{param_name} must use boolean values")
        return raw_value

    if param_type == "int":
        if (
            isinstance(raw_value, bool)
            or not isinstance(raw_value, (int, float))
            or not float(raw_value).is_integer()
        ):
            raise ValueError(f"{context}.{param_name} must use integer values")
        value = int(raw_value)
        if enforce_bounds:
            lo, hi = map(int, param["bounds"])
            if value < lo or value > hi:
                raise ValueError(
                    f"{context}.{param_name} must stay within parameter bounds [{lo}, {hi}]"
                )
        return value

    if param_type == "float":
        if not _is_finite_number(raw_value):
            raise ValueError(f"{context}.{param_name} must use finite numeric values")
        numeric_value = float(raw_value)
        if enforce_bounds:
            lo_bound, hi_bound = map(float, param["bounds"])
            if numeric_value < lo_bound or numeric_value > hi_bound:
                raise ValueError(
                    f"{context}.{param_name} must stay within parameter bounds [{lo_bound}, {hi_bound}]"
                )
        return numeric_value

    if param_type == "categorical":
        if not (isinstance(raw_value, str) or _is_finite_number(raw_value)):
            raise ValueError(
                f"{context}.{param_name} must use a configured categorical choice value"
            )
        rendered = _choice_key(cast(ConstraintValue, raw_value))
        for choice in param["choices"]:
            if _choice_key(cast(ConstraintValue, choice)) == rendered:
                return cast(ConstraintValue, choice)
        raise ValueError(
            f"{context}.{param_name} must match one of the configured categorical choices"
        )

    raise ValueError(f"Unsupported parameter type for constraint matching: {param_type}")


def _normalize_match_object(
    raw_when: Any, params_by_name: dict[str, JSONDict], *, context: str
) -> dict[str, list[ConstraintValue]]:
    when_context = f"{context}.when"
    if not isinstance(raw_when, dict) or not raw_when:
        raise ValueError(f"{context} must define 'when' as a non-empty object")

    normalized: dict[str, list[ConstraintValue]] = {}
    for raw_name, raw_value in raw_when.items():
        if not isinstance(raw_name, str) or not raw_name:
            raise ValueError(f"{when_context} keys must be non-empty strings")
        param = params_by_name.get(raw_name)
        if param is None:
            raise ValueError(f"{when_context} references unknown parameter '{raw_name}'")

        raw_values = raw_value if isinstance(raw_value, list) else [raw_value]
        if not raw_values:
            raise ValueError(f"{when_context}.{raw_name} must not be empty")

        values: list[ConstraintValue] = []
        seen_values: set[str] = set()
        for candidate in raw_values:
            normalized_value = _canonicalize_match_value(
                candidate,
                param,
                context=when_context,
                enforce_bounds=True,
            )
            rendered = _choice_key(normalized_value)
            if rendered in seen_values:
                raise ValueError(f"{when_context}.{raw_name} must not contain duplicate values")
            seen_values.add(rendered)
            values.append(normalized_value)
        normalized[raw_name] = values
    return normalized


def _normalize_bound_tightening_rule(
    raw_rule: Any, params_by_name: dict[str, JSONDict], idx: int
) -> JSONDict:
    context = f"constraints.bound_tightening[{idx}]"
    if not isinstance(raw_rule, dict):
        raise ValueError(f"{context} must be an object")

    raw_param_name = raw_rule.get("param")
    if not isinstance(raw_param_name, str) or not raw_param_name:
        raise ValueError(f"{context}.param must be a non-empty string")
    param = params_by_name.get(raw_param_name)
    if param is None:
        raise ValueError(f"{context}.param references unknown parameter '{raw_param_name}'")
    if str(param["type"]) not in _NUMERIC_PARAMETER_TYPES:
        raise ValueError(f"{context}.param must reference a numeric parameter")

    has_min = "min" in raw_rule
    has_max = "max" in raw_rule
    if not has_min and not has_max:
        raise ValueError(f"{context} must define at least one of 'min' or 'max'")

    normalized: JSONDict = {
        "rule_id": f"bound_tightening[{idx}]",
        "param": raw_param_name,
    }
    lo, hi = param["bounds"]
    if has_min:
        min_value = raw_rule["min"]
        if not _is_finite_number(min_value):
            raise ValueError(f"{context}.min must be a finite number")
        if str(param["type"]) == "int":
            if float(min_value).is_integer() is False:
                raise ValueError(f"{context}.min must use an integer value")
            min_number: int | float = int(min_value)
        else:
            min_number = float(min_value)
        if float(min_number) < float(lo):
            raise ValueError(f"{context}.min must stay within parameter bounds [{lo}, {hi}]")
        normalized["min"] = min_number
    if has_max:
        max_value = raw_rule["max"]
        if not _is_finite_number(max_value):
            raise ValueError(f"{context}.max must be a finite number")
        if str(param["type"]) == "int":
            if float(max_value).is_integer() is False:
                raise ValueError(f"{context}.max must use an integer value")
            max_number: int | float = int(max_value)
        else:
            max_number = float(max_value)
        if float(max_number) > float(hi):
            raise ValueError(f"{context}.max must stay within parameter bounds [{lo}, {hi}]")
        normalized["max"] = max_number

    if (
        "min" in normalized
        and "max" in normalized
        and float(normalized["min"]) > float(normalized["max"])
    ):
        raise ValueError(f"{context} must satisfy min <= max")
    return normalized


def _normalize_linear_inequality_rule(
    raw_rule: Any, params_by_name: dict[str, JSONDict], idx: int
) -> JSONDict:
    context = f"constraints.linear_inequalities[{idx}]"
    if not isinstance(raw_rule, dict):
        raise ValueError(f"{context} must be an object")

    raw_terms = raw_rule.get("terms")
    if not isinstance(raw_terms, list) or not raw_terms:
        raise ValueError(f"{context}.terms must be a non-empty array")
    operator = raw_rule.get("operator")
    if not isinstance(operator, str) or operator not in {"<=", ">="}:
        raise ValueError(f"{context}.operator must be '<=' or '>='")
    rhs = raw_rule.get("rhs")
    if not _is_finite_number(rhs):
        raise ValueError(f"{context}.rhs must be a finite number")

    terms: list[JSONDict] = []
    seen_params: set[str] = set()
    for term_idx, raw_term in enumerate(raw_terms):
        term_context = f"{context}.terms[{term_idx}]"
        if not isinstance(raw_term, dict):
            raise ValueError(f"{term_context} must be an object")
        raw_param_name = raw_term.get("param")
        if not isinstance(raw_param_name, str) or not raw_param_name:
            raise ValueError(f"{term_context}.param must be a non-empty string")
        if raw_param_name in seen_params:
            raise ValueError(f"{context} must not repeat parameter '{raw_param_name}'")
        param = params_by_name.get(raw_param_name)
        if param is None:
            raise ValueError(
                f"{term_context}.param references unknown parameter '{raw_param_name}'"
            )
        if str(param["type"]) not in _NUMERIC_PARAMETER_TYPES:
            raise ValueError(f"{term_context}.param must reference a raw numeric parameter")
        coefficient = raw_term.get("coefficient")
        if not _is_finite_number(coefficient):
            raise ValueError(f"{term_context}.coefficient must be a finite number")
        seen_params.add(raw_param_name)
        terms.append({"param": raw_param_name, "coefficient": float(cast(float, coefficient))})

    return {
        "rule_id": f"linear_inequalities[{idx}]",
        "terms": terms,
        "operator": operator,
        "rhs": float(cast(float, rhs)),
    }


def _normalize_forbidden_combination_rule(
    raw_rule: Any, params_by_name: dict[str, JSONDict], idx: int
) -> JSONDict:
    context = f"constraints.forbidden_combinations[{idx}]"
    if not isinstance(raw_rule, dict):
        raise ValueError(f"{context} must be an object")

    return {
        "rule_id": f"forbidden_combinations[{idx}]",
        "when": _normalize_match_object(raw_rule.get("when"), params_by_name, context=context),
    }


def _validate_combined_bound_tightening(
    normalized: JSONDict, params_by_name: dict[str, JSONDict]
) -> None:
    by_param: dict[str, tuple[float | None, float | None]] = {}
    for rule in normalized["bound_tightening"]:
        param_name = str(rule["param"])
        min_bound, max_bound = by_param.get(param_name, (None, None))
        if "min" in rule:
            next_min = float(rule["min"])
            min_bound = next_min if min_bound is None else max(min_bound, next_min)
        if "max" in rule:
            next_max = float(rule["max"])
            max_bound = next_max if max_bound is None else min(max_bound, next_max)
        by_param[param_name] = (min_bound, max_bound)

    for param_name, (min_bound, max_bound) in by_param.items():
        if min_bound is None or max_bound is None:
            continue
        if min_bound > max_bound:
            param = params_by_name[param_name]
            lo, hi = param["bounds"]
            raise ValueError(
                f"constraints.bound_tightening collapses parameter '{param_name}' outside [{lo}, {hi}]"
            )


def normalize_constraints(constraints_cfg: JSONDict, params: list[JSONDict]) -> JSONDict:
    if not isinstance(constraints_cfg, dict):
        raise ValueError("constraints must be an object")

    params_by_name = _params_by_name(params)
    bound_tightening = constraints_cfg.get("bound_tightening", [])
    if bound_tightening is None:
        bound_tightening = []
    if not isinstance(bound_tightening, list):
        raise ValueError("constraints.bound_tightening must be an array")

    linear_inequalities = constraints_cfg.get("linear_inequalities", [])
    if linear_inequalities is None:
        linear_inequalities = []
    if not isinstance(linear_inequalities, list):
        raise ValueError("constraints.linear_inequalities must be an array")

    forbidden_combinations = constraints_cfg.get("forbidden_combinations", [])
    if forbidden_combinations is None:
        forbidden_combinations = []
    if not isinstance(forbidden_combinations, list):
        raise ValueError("constraints.forbidden_combinations must be an array")

    normalized: JSONDict = {
        "bound_tightening": [
            _normalize_bound_tightening_rule(rule, params_by_name, idx)
            for idx, rule in enumerate(bound_tightening)
        ],
        "linear_inequalities": [
            _normalize_linear_inequality_rule(rule, params_by_name, idx)
            for idx, rule in enumerate(linear_inequalities)
        ],
        "forbidden_combinations": [
            _normalize_forbidden_combination_rule(rule, params_by_name, idx)
            for idx, rule in enumerate(forbidden_combinations)
        ],
    }
    _validate_combined_bound_tightening(normalized, params_by_name)
    return normalized


def _match_allowed_values(values: JSONDict, when: dict[str, list[ConstraintValue]]) -> bool:
    for param_name, allowed_values in when.items():
        if param_name not in values:
            return False
        observed = cast(ConstraintValue, values[param_name])
        if not any(_choice_key(observed) == _choice_key(candidate) for candidate in allowed_values):
            return False
    return True


def _bound_violation_details(rule: JSONDict, value: float) -> tuple[str, JSONDict] | None:
    if "min" in rule and value < float(rule["min"]) - _NUMERIC_COMPARISON_TOLERANCE:
        return (
            f"value {value} is below minimum {rule['min']}",
            {"observed": value, "minimum": rule["min"]},
        )
    if "max" in rule and value > float(rule["max"]) + _NUMERIC_COMPARISON_TOLERANCE:
        return (
            f"value {value} exceeds maximum {rule['max']}",
            {"observed": value, "maximum": rule["max"]},
        )
    return None


def _evaluate_bound_tightening(values: JSONDict, rules: list[JSONDict]) -> list[JSONDict]:
    violations: list[JSONDict] = []
    for rule in rules:
        param_name = str(rule["param"])
        if param_name not in values:
            continue
        observed = values[param_name]
        if not _is_finite_number(observed):
            continue
        detail = _bound_violation_details(rule, float(observed))
        if detail is None:
            continue
        message, payload = detail
        violations.append(
            {
                "rule_id": rule["rule_id"],
                "rule_type": "bound_tightening",
                "message": f"Parameter '{param_name}' {message}",
                "details": {"param": param_name, **payload},
            }
        )
    return violations


def _evaluate_linear_inequalities(values: JSONDict, rules: list[JSONDict]) -> list[JSONDict]:
    violations: list[JSONDict] = []
    for rule in rules:
        terms = cast(list[JSONDict], rule["terms"])
        if any(str(term["param"]) not in values for term in terms):
            continue
        lhs = 0.0
        term_values: list[JSONDict] = []
        for term in terms:
            param_name = str(term["param"])
            observed = float(values[param_name])
            coefficient = float(term["coefficient"])
            lhs += coefficient * observed
            term_values.append(
                {"param": param_name, "coefficient": coefficient, "observed": observed}
            )
        operator = str(rule["operator"])
        rhs = float(rule["rhs"])
        feasible = lhs <= rhs + _NUMERIC_COMPARISON_TOLERANCE
        if operator == ">=":
            feasible = lhs >= rhs - _NUMERIC_COMPARISON_TOLERANCE
        if feasible:
            continue
        violations.append(
            {
                "rule_id": rule["rule_id"],
                "rule_type": "linear_inequality",
                "message": f"Linear constraint {lhs} {operator} {rhs} is not satisfied",
                "details": {
                    "operator": operator,
                    "lhs": lhs,
                    "rhs": rhs,
                    "terms": term_values,
                },
            }
        )
    return violations


def _evaluate_forbidden_combinations(values: JSONDict, rules: list[JSONDict]) -> list[JSONDict]:
    violations: list[JSONDict] = []
    for rule in rules:
        when = cast(dict[str, list[ConstraintValue]], rule["when"])
        if not _match_allowed_values(values, when):
            continue
        violations.append(
            {
                "rule_id": rule["rule_id"],
                "rule_type": "forbidden_combination",
                "message": "Forbidden parameter combination matched",
                "details": {"when": when},
            }
        )
    return violations


def evaluate_constraints(values: JSONDict, constraints: JSONDict) -> JSONDict:
    violations: list[JSONDict] = []
    violations.extend(
        _evaluate_bound_tightening(
            values, cast(list[JSONDict], constraints.get("bound_tightening", []))
        )
    )
    violations.extend(
        _evaluate_linear_inequalities(
            values, cast(list[JSONDict], constraints.get("linear_inequalities", []))
        )
    )
    violations.extend(
        _evaluate_forbidden_combinations(
            values, cast(list[JSONDict], constraints.get("forbidden_combinations", []))
        )
    )
    reject_counts = summarize_reject_counts(violations)
    return {
        "feasible": not violations,
        "violations": violations,
        "reject_counts": reject_counts,
    }


def summarize_reject_counts(violations: list[JSONDict]) -> JSONDict:
    counts: JSONDict = {}
    for violation in violations:
        rule_id = str(violation["rule_id"])
        counts[rule_id] = int(counts.get(rule_id, 0)) + 1
    return counts


def accumulate_reject_counts(counts: JSONDict, evaluation: JSONDict) -> JSONDict:
    updated = dict(counts)
    for rule_id, count in cast(JSONDict, evaluation.get("reject_counts", {})).items():
        updated[str(rule_id)] = int(updated.get(str(rule_id), 0)) + int(count)
    return updated
