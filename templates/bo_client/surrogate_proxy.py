from __future__ import annotations

import importlib.util
import math
from pathlib import Path

from acquisition import acquisition_score

_TEMPLATE_DIR = Path(__file__).resolve().parent


def _load_shared_module(module_name: str, filename: str):
    module_path = _TEMPLATE_DIR.parent / "_shared" / filename
    if not module_path.exists():
        raise ModuleNotFoundError(
            f"Missing shared module at {module_path}. Ensure templates/_shared is present."
        )
    spec = importlib.util.spec_from_file_location(module_name, module_path)
    if spec is None or spec.loader is None:
        raise ImportError(f"Unable to load shared module from {module_path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


_SEARCH_SPACE = _load_shared_module("looptimum_shared_search_space", "search_space.py")
_OBJECTIVES = _load_shared_module("looptimum_shared_objectives", "objectives.py")

normalized_numeric_distance = _SEARCH_SPACE.normalized_numeric_distance
scalarize_objectives = _OBJECTIVES.scalarize_objectives
scalarized_direction = _OBJECTIVES.scalarized_direction


def _norm_dist(a: dict, b: dict, params: list[dict]) -> float:
    return float(normalized_numeric_distance(a, b, params))


def _predict_rbf_proxy(
    x: dict, obs: list[dict], params: list[dict], objective_cfg: dict, length_scale: float
) -> tuple[float, float]:
    if not obs:
        return 0.0, 1.0
    ys, ws = [], []
    for row in obs:
        d = _norm_dist(x, row["params"], params)
        w = math.exp(-(d * d) / (2.0 * max(length_scale, 1e-6) ** 2))
        ys.append(float(scalarize_objectives(row["objectives"], objective_cfg)))
        ws.append(w)
    wsum = sum(ws)
    if wsum < 1e-9:
        return sum(ys) / len(ys), 1.0
    mean = sum(w * y for w, y in zip(ws, ys)) / wsum
    var = sum(w * (y - mean) ** 2 for w, y in zip(ws, ys)) / wsum
    density = wsum / len(obs)
    std = math.sqrt(max(var, 1e-12)) + max(0.0, 1.0 - min(1.0, density))
    return mean, std


def propose_with_proxy(
    candidates: list[dict],
    observations: list[dict],
    params: list[dict],
    objective_cfg: dict,
    surrogate_cfg: dict,
    acq_cfg: dict,
    best: float | None,
) -> tuple[dict, dict]:
    direction = str(scalarized_direction(objective_cfg))
    length_scale = float(surrogate_cfg.get("length_scale", 0.2))
    scored = []
    for cand in candidates:
        mean, std = _predict_rbf_proxy(cand, observations, params, objective_cfg, length_scale)
        score = acquisition_score(mean, std, best, direction, acq_cfg)
        scored.append((score, cand, mean, std))
    scored.sort(key=lambda x: x[0], reverse=True)
    score, cand, mean, std = scored[0]
    return cand, {
        "strategy": "surrogate_acquisition",
        "surrogate_backend": "rbf_proxy",
        "acquisition_type": acq_cfg.get("type", "ei"),
        "predicted_mean": mean,
        "predicted_std": std,
        "acquisition_score": score,
    }
