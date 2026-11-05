"""Preregistered synthetic problems; simulator truth never enters Ax model inputs."""

from __future__ import annotations

import importlib.util
import random
from pathlib import Path
from types import ModuleType
from typing import Any, cast

JSON = dict[str, Any]
ROOT = Path(__file__).resolve().parents[2]
WORKLOADS = ("noisy_scalar", "typed_conditional", "measured_scalar", "pareto_tradeoff")
SEEDS = (17, 23, 41, 67, 97)


def shared(name: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        f"capabilities_{name}", ROOT / "templates/_shared" / f"{name}.py"
    )
    if spec is None or spec.loader is None:
        raise ImportError(name)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


SPACE = shared("search_space")
CONSTRAINTS = shared("constraints")
CODEC = shared("ax_space")
OBJECTIVES = shared("objectives")


def arms(workload: str) -> tuple[str, str]:
    return ("reported_sem", "unknown_sem") if workload == "noisy_scalar" else ("ax", "random")


def definition(workload: str) -> JSON:
    if workload not in WORKLOADS:
        raise ValueError(f"Unknown workload {workload}")
    parameters: list[JSON] = [
        {"name": name, "type": "float", "bounds": [0, 1]} for name in ("x", "y")
    ]
    objective: JSON = {"primary_objective": {"name": "loss", "direction": "minimize"}}
    rules: JSON = {}
    if workload == "typed_conditional":
        parameters = [
            {"name": "kind", "type": "categorical", "choices": [1, 1.0, "1"]},
            {"name": "flag", "type": "bool", "when": {"kind": 1}},
            {"name": "leaf", "type": "int", "bounds": [3, 3], "when": {"flag": True}},
            *parameters,
            {"name": "count", "type": "int", "bounds": [1, 3]},
        ]
        rules = {
            "linear_inequalities": [
                {
                    "operator": "<=",
                    "rhs": 1.6,
                    "terms": [
                        {"param": "x", "coefficient": 1},
                        {"param": "y", "coefficient": 1},
                        {"param": "count", "coefficient": 0.1},
                    ],
                }
            ],
            "forbidden_combinations": [{"when": {"kind": 1, "flag": False}}],
        }
    if workload in ("measured_scalar", "pareto_tradeoff"):
        objective.update(
            measurement_metrics=["resource"],
            outcome_constraints=[
                {
                    "metric": "resource",
                    "op": "<=",
                    "bound": 0.7 if workload == "measured_scalar" else 0.8,
                }
            ],
        )
    if workload == "pareto_tradeoff":
        objective.update(
            secondary_objectives=[{"name": "gain", "direction": "maximize"}],
            pareto_reference={"loss": 1, "gain": -0.1},
        )
    return {
        "parameter_space": {"parameters": parameters},
        "constraints": rules,
        "objective_schema": objective,
        "acquisition": "pareto" if workload == "pareto_tradeoff" else "scalar",
        "scalar_optimum": 0.045 if workload == "measured_scalar" else 0.0,
        "pareto_optimal_hypervolume": 0.58 if workload == "pareto_tradeoff" else None,
    }


def codec(workload: str) -> JSON:
    spec = definition(workload)
    parameters = SPACE.normalize_search_space(spec["parameter_space"])
    constraints = (
        CONSTRAINTS.normalize_constraints(spec["constraints"], parameters)
        if spec["constraints"]
        else None
    )
    return cast(JSON, CODEC.build_codec(parameters, constraints))


def valid(params: JSON, workload: str) -> bool:
    mapping = codec(workload)
    try:
        CODEC.encode(mapping, params)
    except (ValueError, TypeError, KeyError):
        return False
    return bool(CODEC.feasible(mapping, params)["feasible"])


def random_candidate(workload: str, seed: int, ordinal: int, blocked: set[str]) -> tuple[JSON, int]:
    spec = definition(workload)
    parameters = SPACE.normalize_search_space(spec["parameter_space"])
    rng = random.Random(f"ax-capabilities-random-v1:{workload}:{seed}:{ordinal}")
    for attempt in range(1, 4097):
        point = SPACE.sample_random_point(rng, parameters)
        if valid(point, workload) and CODEC.key(point) not in blocked:
            return point, attempt
    raise ValueError("Feasible uniform random sampler exhausted its 4096-attempt bound")


def measure(params: JSON, workload: str, arm: str, seed: int, ordinal: int) -> JSON:
    if not valid(params, workload):
        raise ValueError("Invalid public candidate")
    x, y = params["x"], params["y"]
    truth = (x - 0.32) ** 2 + (y - 0.74) ** 2
    if workload == "typed_conditional":
        truth += {int: 0.0, float: 0.04, str: 0.08}[type(params["kind"])] + 0.01 * (
            params["count"] - 1
        ) ** 2
    elif workload == "measured_scalar":
        truth = (x - 0.8) ** 2 + (y - 0.2) ** 2
    elif workload == "pareto_tradeoff":
        truth = x + y**2
    sem = 0.02 + 0.06 * x if workload == "noisy_scalar" else 0.0
    standardized_draw = random.Random(f"ax-capabilities-noise-v1:{seed}:{ordinal}").gauss(0, 1)
    payload: JSON = {"status": "ok", "objectives": {"loss": truth + sem * standardized_draw}}
    latent = {"loss": truth}
    if workload == "pareto_tradeoff":
        payload["objectives"]["gain"] = x - y**2
        latent["gain"] = x - y**2
    if arm != "unknown_sem":
        payload["objective_sems"] = {name: sem for name in payload["objectives"]}
    if workload in ("measured_scalar", "pareto_tradeoff"):
        payload["measurements"] = {
            "resource": x + (0.5 * y if workload == "pareto_tradeoff" else y)
        }
        payload["measurement_sems"] = {"resource": 0.0}
    return {
        "payload": payload,
        "simulator_truth": latent,
        "simulator_sem": sem,
        "standardized_noise_draw": standardized_draw,
    }


def metrics(trials: list[JSON], workload: str) -> JSON:
    spec = definition(workload)
    cfg = OBJECTIVES.normalize_objective_schema(
        spec["objective_schema"], contract_version=2, acquisition=spec["acquisition"]
    )
    rows = [
        {"trial_id": row["ordinal"], "params": row["params"], **row["measurement"]["payload"]}
        for row in trials
        if row.get("evaluation_status") == "completed"
    ]
    summary = OBJECTIVES.outcome_summary(rows, cfg)
    ids = {row["trial_id"] for row in summary["feasible_pareto_front"]["trials"]}
    # Regret ranges over all observed feasible configurations, not only the front.
    feasible_ids = {
        row["trial_id"] for row in summary["outcome_constraint_status"] if row["feasible"]
    }
    feasible = [row for row in trials if row["ordinal"] in feasible_ids]
    chosen = (
        min(feasible, key=lambda row: row["measurement"]["payload"]["objectives"]["loss"])
        if feasible
        else None
    )
    return {
        "evaluation_slots_attempted": len(trials),
        "evaluations_completed": len(rows),
        "evaluation_failures": len(trials) - len(rows),
        "feasible_fraction": len(feasible) / len(trials) if trials else 0.0,
        "feasible_simple_regret": max(
            0.0,
            min(row["measurement"]["simulator_truth"]["loss"] for row in feasible)
            - spec["scalar_optimum"],
        )
        if feasible and workload != "pareto_tradeoff"
        else None,
        "selected_latent_regret": max(
            0.0, chosen["measurement"]["simulator_truth"]["loss"] - spec["scalar_optimum"]
        )
        if chosen and workload != "pareto_tradeoff"
        else None,
        "feasible_hypervolume": summary["feasible_hypervolume"],
        "feasible_front_trial_ids": sorted(ids),
        "unique_parameterizations": len({CODEC.key(row["params"]) for row in trials}),
        "repeats": len(trials) - len({CODEC.key(row["params"]) for row in trials}),
    }
