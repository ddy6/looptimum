#!/usr/bin/env python3
"""Tiny synthetic objective helper for local testing."""

from __future__ import annotations

import json
import math
import sys

if len(sys.argv) != 3:
    raise SystemExit("Usage: synthetic_experiment.py <suggestion_json> <result_json>")

with open(sys.argv[1], "r", encoding="utf-8") as handle:
    suggestion = json.load(handle)

x1 = float(suggestion["params"]["x1"])
x2 = float(suggestion["params"]["x2"])
loss = (x1 - 0.25) ** 2 + (x2 - 0.75) ** 2 + 0.2 * math.sin(8.0 * x1)

result = {
    "trial_id": int(suggestion["trial_id"]),
    "params": suggestion["params"],
    "objectives": {"loss": loss},
    "status": "ok",
}

with open(sys.argv[2], "w", encoding="utf-8") as handle:
    json.dump(result, handle, indent=2)
