#!/usr/bin/env python3
"""Client-fill objective adapter stub.

Replace the body of `evaluate(params)` with code that runs one evaluation in
your environment and returns a scalar objective.
"""

from __future__ import annotations

from typing import Any


def evaluate(params: dict[str, Any]) -> float | dict[str, Any]:
    """Run one evaluation for the provided params and return a scalar objective.

    Expected inputs:
    - `params`: exact parameter dictionary from `run_bo.py suggest`

    Supported return values:
    - `float` / `int`: interpreted as the scalar objective value (status = "ok")
    - `dict` with:
      - `objective` or `objective_value` (required): numeric scalar
      - `status` (optional): "ok" or "failed" (default "ok")

    Replace this stub with your real integration.
    """
    raise NotImplementedError(
        "Implement client_harness_template/objective.py:evaluate(params) to "
        "map params -> your run -> scalar objective."
    )

