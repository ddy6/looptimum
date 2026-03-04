#!/usr/bin/env python3
"""Tiny deterministic noisy-quadratic objective used for end-to-end demos."""

from __future__ import annotations

import math
from typing import Any


def _require_float(params: dict[str, Any], name: str) -> float:
    if name not in params:
        raise KeyError(f"missing parameter: {name}")
    value = params[name]
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError(f"parameter {name} must be numeric")
    return float(value)


def evaluate(params: dict[str, Any]) -> float:
    """Return a scalar loss (lower is better)."""
    x1 = _require_float(params, "x1")
    x2 = _require_float(params, "x2")

    # Intentionally simple bowl with a deterministic pseudo-noise perturbation.
    base = (x1 - 0.32) ** 2 + (x2 - 0.74) ** 2
    pseudo_noise = 0.012 * math.sin(29.0 * x1 + 41.0 * x2)
    return float(base + pseudo_noise)
