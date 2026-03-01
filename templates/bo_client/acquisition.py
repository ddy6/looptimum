from __future__ import annotations

import math


def _std_norm_pdf(z: float) -> float:
    return math.exp(-0.5 * z * z) / math.sqrt(2.0 * math.pi)


def _std_norm_cdf(z: float) -> float:
    return 0.5 * (1.0 + math.erf(z / math.sqrt(2.0)))


def _expected_improvement(mean: float, std: float, best: float | None, direction: str, xi: float) -> float:
    if best is None:
        return max(0.0, std)
    if std <= 1e-12:
        return 0.0
    imp = (best - mean - xi) if direction == "minimize" else (mean - best - xi)
    z = imp / std
    return max(0.0, imp * _std_norm_cdf(z) + std * _std_norm_pdf(z))


def acquisition_score(mean: float, std: float, best: float | None, direction: str, acq: dict) -> float:
    t = str(acq.get("type", "ei")).lower()
    if t == "ucb":
        kappa = float(acq.get("kappa", 1.5))
        return -(mean - kappa * std) if direction == "minimize" else (mean + kappa * std)
    if t in {"ei", "ei_proxy"}:
        xi = float(acq.get("xi", 0.01))
        return _expected_improvement(mean, std, best, direction, xi)
    raise ValueError(f"Unsupported acquisition type: {t}")
