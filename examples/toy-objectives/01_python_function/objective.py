#!/usr/bin/env python3
"""Toy example: direct Python function objective (in-process)."""

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
    """Return a deterministic scalar objective (lower is better)."""
    x1 = _require_float(params, "x1")
    x2 = _require_float(params, "x2")

    # Smooth bowl + mild nonlinearity for visible structure.
    loss = (x1 - 0.22) ** 2 + (x2 - 0.78) ** 2 + 0.12 * math.sin(7.0 * x1)
    return float(loss)
