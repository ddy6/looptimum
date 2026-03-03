#!/usr/bin/env python3
"""Toy subprocess worker that returns raw metrics JSON on stdout."""

from __future__ import annotations

import json
import math
import sys
from pathlib import Path
from typing import Any


def _load_params(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("params payload must be a JSON object")
    return data


def _f(name: str, params: dict[str, Any]) -> float:
    value = params.get(name)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{name} must be numeric")
    return float(value)


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print("Usage: worker_cli.py <params_json>", file=sys.stderr)
        return 64

    params = _load_params(Path(argv[1]))
    x1 = _f("x1", params)
    x2 = _f("x2", params)

    # Synthetic invalid region to demonstrate explicit failure handling.
    if (x1 + x2) > 1.55:
        print(
            json.dumps(
                {
                    "status": "invalid_region",
                    "reason": "x1 + x2 exceeds synthetic feasibility threshold",
                    "x1": x1,
                    "x2": x2,
                }
            )
        )
        return 2

    quality = 1.0 - ((x1 - 0.28) ** 2 + (x2 - 0.73) ** 2)
    runtime_s = 0.2 + 0.5 * x1 + 0.15 * x2
    penalty = 0.03 * abs(math.sin(12.0 * x2))

    payload = {
        "quality": float(quality),
        "runtime_s": float(runtime_s),
        "penalty": float(penalty),
        "status": "ok",
    }
    print(json.dumps(payload))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
