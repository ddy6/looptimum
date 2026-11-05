"""Dependency-free measurement contracts for the opt-in Ax adapter version 2."""

from __future__ import annotations

import math
from collections.abc import Iterable
from typing import Any

JSONDict = dict[str, Any]
MEASUREMENT_FIELDS = ("objective_sems", "measurements", "measurement_sems", "scalarized_sem")
OUTCOME_CONFIG_FIELDS = ("measurement_metrics", "outcome_constraints", "pareto_reference")


def finite_number(value: Any, field: str, *, nonnegative: bool = False) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{field} must be a finite {'nonnegative ' if nonnegative else ''}number")
    try:
        result = float(value)
    except (OverflowError, ValueError) as exc:
        raise ValueError(f"{field} must be finite") from exc
    if not math.isfinite(result) or (nonnegative and result < 0):
        raise ValueError(f"{field} must be a finite {'nonnegative ' if nonnegative else ''}number")
    return result


def normalize_outcome_config(raw: JSONDict, objective_names: list[str]) -> JSONDict:
    metrics = raw.get("measurement_metrics", [])
    if not isinstance(metrics, list) or any(
        not isinstance(x, str) or not x.strip() for x in metrics
    ):
        raise ValueError("measurement_metrics must list nonempty metric names")
    metrics = [name.strip() for name in metrics]
    if len(set(metrics)) != len(metrics) or set(metrics) & set(objective_names):
        raise ValueError("measurement_metrics must be unique and disjoint from objectives")
    constraints = raw.get("outcome_constraints", [])
    if not isinstance(constraints, list):
        raise ValueError("outcome_constraints must be a list")
    normalized = []
    limits: dict[str, tuple[float, float]] = {}
    for constraint in constraints:
        if not isinstance(constraint, dict) or set(constraint) != {"metric", "op", "bound"}:
            raise ValueError("Each outcome constraint requires exactly metric, op and bound")
        metric, op = constraint["metric"], constraint["op"]
        if metric in objective_names:
            raise ValueError(
                "Outcome constraints must use disjoint extra measurements, not objective thresholds"
            )
        if not isinstance(metric, str) or metric not in metrics or op not in ("<=", ">="):
            raise ValueError("Outcome constraints require a declared measurement and <= or >=")
        bound = finite_number(constraint["bound"], "outcome_constraints.bound")
        lo, hi = limits.get(metric, (-math.inf, math.inf))
        lo, hi = (max(lo, bound), hi) if op == ">=" else (lo, min(hi, bound))
        if lo > hi:
            raise ValueError(f"Contradictory outcome constraints for {metric!r}")
        limits[metric] = (lo, hi)
        normalized.append({"metric": metric, "op": op, "bound": bound})
    out: JSONDict = {}
    if metrics:
        out["measurement_metrics"] = metrics
    if normalized:
        out["outcome_constraints"] = normalized
    if "pareto_reference" in raw:
        reference = raw["pareto_reference"]
        if not isinstance(reference, dict) or set(reference) != set(objective_names):
            raise ValueError(
                "pareto_reference must supply exactly every objective in original units"
            )
        out["pareto_reference"] = {
            name: finite_number(reference[name], f"pareto_reference.{name}")
            for name in objective_names
        }
    return out


def _metric_map(payload: JSONDict, key: str, allowed: list[str], *, sem: bool = False) -> JSONDict:
    value = payload.get(key, {})
    if not isinstance(value, dict):
        raise ValueError(f"{key} must be a metric map; null is not an unknown-noise value")
    if set(value) - set(allowed):
        raise ValueError(f"{key} contains undeclared metric names")
    return {
        name: finite_number(item, f"{key}.{name}", nonnegative=sem) for name, item in value.items()
    }


def normalize_measurements(payload: JSONDict, objective_cfg: JSONDict) -> JSONDict:
    """Canonicalize only explicitly validated fields; empty maps equal absence."""
    if objective_cfg.get("ax_contract_version", 1) != 2:
        if any(key in payload for key in MEASUREMENT_FIELDS):
            raise ValueError("Measurement/SEM fields require optimizer.ax.contract_version=2")
        return {}
    names = list(objective_cfg["objective_names"])
    metrics = list(objective_cfg.get("measurement_metrics", []))
    objective_sems = _metric_map(payload, "objective_sems", names, sem=True)
    measurements = _metric_map(payload, "measurements", metrics)
    measurement_sems = _metric_map(payload, "measurement_sems", metrics, sem=True)
    scalar_sem = (
        finite_number(payload["scalarized_sem"], "scalarized_sem", nonnegative=True)
        if "scalarized_sem" in payload
        else None
    )
    if payload.get("status", "ok") != "ok":
        if objective_sems or measurements or measurement_sems or scalar_sem is not None:
            raise ValueError("Non-ok outcomes cannot carry measurements or SEMs")
        return {}
    if set(measurements) != set(metrics):
        raise ValueError("Successful outcomes must supply every declared measurement")
    objectives = payload.get("objectives", {})
    for name in objective_sems:
        finite_number(objectives.get(name), f"objectives.{name} required by objective_sems")
    if set(measurement_sems) - set(measurements):
        raise ValueError("A measurement SEM requires its corresponding measurement")
    weighted = objective_cfg["scalarization"]["policy"] in ("weighted_sum", "weighted_tchebycheff")
    pareto = objective_cfg.get("acquisition", "scalar") == "pareto"
    if scalar_sem is not None and (not weighted or pareto):
        raise ValueError("scalarized_sem is used only by weighted scalar acquisition")
    if weighted and not pareto and objective_sems and scalar_sem is None:
        raise ValueError("Weighted objective SEMs require an evaluator-supplied scalarized_sem")
    result: JSONDict = {
        key: value
        for key, value in (
            ("objective_sems", objective_sems),
            ("measurements", measurements),
            ("measurement_sems", measurement_sems),
        )
        if value
    }
    if scalar_sem is not None:
        result["scalarized_sem"] = scalar_sem
    return result


def modeled_sems(row: JSONDict, objective_cfg: JSONDict) -> JSONDict:
    """Coverage keys distinguish scalar acquisition from raw objective names."""
    errors = row.get("objective_sems", {})
    if objective_cfg.get("acquisition", "scalar") == "pareto":
        result = {
            f"objective:{name}": errors.get(name) for name in objective_cfg["objective_names"]
        }
    else:
        primary = objective_cfg["primary_objective"]["name"]
        value = (
            errors.get(primary)
            if objective_cfg["scalarization"]["policy"] == "primary_only"
            else row.get("scalarized_sem")
        )
        result = {"scalar_score": value}
    for constraint in objective_cfg.get("outcome_constraints", []):
        name = constraint["metric"]
        result[f"measurement:{name}"] = row.get("measurement_sems", {}).get(name)
    return result


def validate_measurement_coverage(rows: Iterable[JSONDict], objective_cfg: JSONDict) -> None:
    """Validate a whole proposed successful history without mutating any row."""
    if objective_cfg.get("ax_contract_version", 1) != 2:
        return
    coverage: dict[str, bool] = {}
    for row in rows:
        if row.get("status", "ok") != "ok":
            continue
        normalized = {**row, **normalize_measurements(row, objective_cfg)}
        for metric, sem in modeled_sems(normalized, objective_cfg).items():
            known = sem is not None
            if metric in coverage and coverage[metric] != known:
                raise ValueError(
                    f"Inconsistent SEM coverage for modeled metric {metric!r}; use SEMs on every successful observation or none"
                )
            coverage[metric] = known


def require_campaign_format(state: JSONDict, objective_cfg: JSONDict) -> None:
    version = objective_cfg.get("ax_contract_version", 1)
    optimizer = state.get("optimizer")
    if optimizer and optimizer.get("backend") == "ax":
        expected = 2 if version == 2 else 1
        if optimizer.get("format_version") != expected:
            raise ValueError(
                "Ax contract/state format changed; use an explicit validated rebuild or a new campaign"
            )
    elif version == 2 and (state.get("observations") or state.get("pending")):
        raise ValueError(
            "Existing history cannot be implicitly upgraded to Ax contract2; use a new campaign or validated rebuild"
        )


def initialize_measurement_state(
    state: JSONDict, objective_cfg: JSONDict, fingerprint: str | None = None
) -> None:
    """Mark a validated fresh import as version2 without importing the optimizer."""
    require_campaign_format(state, objective_cfg)
    if objective_cfg.get("ax_contract_version") == 2 and not state.get("optimizer"):
        state["schema_version"] = "0.5.0"
        state["optimizer"] = {"backend": "ax", "format_version": 2, "initialized": False}
        if fingerprint is not None:
            state["optimizer"]["fingerprint"] = fingerprint


def metric_aliases(objective_cfg: JSONDict) -> dict[str, str]:
    names = [*objective_cfg["objective_names"], *objective_cfg.get("measurement_metrics", [])]
    return {name: f"m{index}" for index, name in enumerate(names)}


def project_metrics(row: JSONDict, objective_cfg: JSONDict, scalar_score: float) -> JSONDict:
    aliases = metric_aliases(objective_cfg)

    def metric(mean: Any, sem: Any) -> JSONDict:
        return {"mean": finite_number(mean, "projected metric"), "sem": sem}

    if objective_cfg.get("acquisition", "scalar") == "pareto":
        out = {
            aliases[name]: metric(row["objectives"][name], row.get("objective_sems", {}).get(name))
            for name in objective_cfg["objective_names"]
        }
    else:
        out = {"score": metric(scalar_score, modeled_sems(row, objective_cfg)["scalar_score"])}
    for name in dict.fromkeys(
        item["metric"] for item in objective_cfg.get("outcome_constraints", [])
    ):
        out[aliases[name]] = metric(
            row["measurements"][name], row.get("measurement_sems", {}).get(name)
        )
    return out
