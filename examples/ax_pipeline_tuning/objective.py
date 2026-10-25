"""Synthetic pipeline latency: replace this evaluator with a real benchmark for a pilot."""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from typing import Any

PARAMETER_SPACE: dict[str, Any] = {
    "parameters": [
        {"name": "batch_size", "type": "int", "bounds": [16, 128]},
        {"name": "workers", "type": "int", "bounds": [1, 8]},
        {"name": "cache", "type": "bool"},
        {"name": "compression", "type": "categorical", "choices": ["none", "lz4", "zstd"]},
        {"name": "buffer_mb", "type": "float", "bounds": [4, 256], "scale": "log"},
    ]
}


def evaluate(params: dict[str, Any]) -> float:
    """Deterministic simulated milliseconds; global minimum 10 at the stated recipe."""
    cost = (
        0.4 * math.log2(params["batch_size"] / 64) ** 2
        + 0.3 * (params["workers"] - 4) ** 2
        + 0.2 * math.log2(params["buffer_mb"] / 64) ** 2
        + (0 if params["cache"] else 0.6)
        + {"none": 0.8, "lz4": 0.0, "zstd": 0.3}[params["compression"]]
    )
    return float(10.0 + 10.0 * cost)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--suggestion", type=Path, required=True)
    parser.add_argument("--result", type=Path, required=True)
    args = parser.parse_args()
    suggestion = json.loads(args.suggestion.read_text())
    payload = {
        "trial_id": suggestion["trial_id"],
        "params": suggestion["params"],
        "objectives": {"latency_ms": evaluate(suggestion["params"])},
        "status": "ok",
    }
    args.result.write_text(json.dumps(payload, indent=2) + "\n")


if __name__ == "__main__":
    main()
