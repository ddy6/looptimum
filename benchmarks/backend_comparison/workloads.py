"""Declared synthetic objectives, exact parameter feasibility, and independent measurement noise."""

from __future__ import annotations

import math
import random
from typing import Any

from examples.ax_pipeline_tuning.objective import PARAMETER_SPACE, evaluate

CONTINUOUS = {
    "parameters": [
        {"name": "x1", "type": "float", "bounds": [0.0, 1.0]},
        {"name": "x2", "type": "float", "bounds": [0.0, 1.0]},
    ]
}
WORKLOADS = ("smooth_quadratic", "multimodal", "pipeline", "noisy_quadratic")


def space(workload: str) -> dict[str, Any]:
    if workload not in WORKLOADS:
        raise ValueError(f"Unknown workload: {workload}")
    return PARAMETER_SPACE if workload == "pipeline" else CONTINUOUS


def valid(params: dict[str, Any], workload: str) -> bool:
    specifications = space(workload)["parameters"]
    if set(params) != {param["name"] for param in specifications}:
        return False
    for param in specifications:
        value = params[param["name"]]
        kind = param["type"]
        if kind == "bool":
            if type(value) is not bool:
                return False
        elif kind == "categorical":
            if not any(
                type(value) is type(choice) and value == choice for choice in param["choices"]
            ):
                return False
        elif (kind == "int" and type(value) is not int) or (
            kind == "float" and (type(value) not in (float, int) or not math.isfinite(value))
        ):
            return False
        elif not param["bounds"][0] <= value <= param["bounds"][1]:
            return False
    return True


def latent(params: dict[str, Any], workload: str) -> float:
    if not valid(params, workload):
        raise ValueError("Infeasible or incorrectly typed parameterization")
    if workload == "pipeline":
        return evaluate(params)
    if workload == "multimodal":
        # Rastrigin on [-5, 5]^2, rescaled by 40; known minimum zero at (0.5, 0.5).
        return float(
            sum(
                (10 * (params[name] - 0.5)) ** 2
                + 10 * (1 - math.cos(2 * math.pi * 10 * (params[name] - 0.5)))
                for name in ("x1", "x2")
            )
            / 40
        )
    return float((params["x1"] - 0.32) ** 2 + (params["x2"] - 0.74) ** 2)


def measure(params: dict[str, Any], workload: str, seed: int, ordinal: int) -> dict[str, float]:
    truth = latent(params, workload)
    sigma = 0.02 + 0.06 * params["x1"] if workload == "noisy_quadratic" else 0.0
    # Trial-indexed draws: repeats receive fresh noise; restart preserves the same draw.
    # The standardized draws are paired between backends at the same seed/ordinal.
    noise = random.Random(f"looptimum-observation-v1:{seed}:{ordinal}").gauss(0, sigma)
    return {"observed": truth + noise, "latent": truth, "noise_std": sigma}


def optimum(workload: str) -> float:
    return 10.0 if workload == "pipeline" else 0.0
