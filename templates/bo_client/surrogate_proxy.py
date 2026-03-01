from __future__ import annotations

import math

from acquisition import acquisition_score


def _norm_dist(a: dict, b: dict, params: list[dict]) -> float:
    s = 0.0
    for p in params:
        lo, hi = map(float, p["bounds"])
        span = max(hi - lo, 1e-12)
        s += ((float(a[p["name"]]) - float(b[p["name"]])) / span) ** 2
    return math.sqrt(s)


def _predict_rbf_proxy(x: dict, obs: list[dict], params: list[dict], obj_name: str, length_scale: float) -> tuple[float, float]:
    if not obs:
        return 0.0, 1.0
    ys, ws = [], []
    for row in obs:
        d = _norm_dist(x, row["params"], params)
        w = math.exp(-(d * d) / (2.0 * max(length_scale, 1e-6) ** 2))
        ys.append(float(row["objectives"][obj_name]))
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
    objective: dict,
    surrogate_cfg: dict,
    acq_cfg: dict,
    best: float | None,
) -> tuple[dict, dict]:
    obj_name = str(objective["name"])
    direction = str(objective["direction"])
    length_scale = float(surrogate_cfg.get("length_scale", 0.2))
    scored = []
    for cand in candidates:
        mean, std = _predict_rbf_proxy(cand, observations, params, obj_name, length_scale)
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
