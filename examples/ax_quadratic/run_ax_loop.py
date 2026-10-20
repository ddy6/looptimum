#!/usr/bin/env python3
"""Create an empty portable campaign and run a small native Ax optimization loop."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--destination", type=Path, required=True, help="New or empty campaign directory"
    )
    parser.add_argument("--steps", type=int, default=5)
    args = parser.parse_args()
    if args.steps < 3:
        parser.error("--steps must be at least 3 to reach model-guided generation")
    destination = args.destination.resolve()
    subprocess.run(
        [
            sys.executable,
            str(REPO_ROOT / "templates/_shared/vendor_copy.py"),
            str(REPO_ROOT / "templates/bo_client"),
            str(destination),
        ],
        check=True,
    )
    config_path = destination / "bo_config.json"
    config = json.loads(config_path.read_text())
    config["optimizer"] = {"backend": "ax", "ax": {"initialization_budget": 2}}
    config["max_trials"] = args.steps
    config_path.write_text(json.dumps(config, indent=2) + "\n")
    (destination / "parameter_space.json").write_text(
        json.dumps(
            {
                "parameters": [
                    {"name": "x", "type": "float", "bounds": [0.0, 1.0]},
                    {"name": "y", "type": "float", "bounds": [0.0, 1.0]},
                ]
            },
            indent=2,
        )
        + "\n"
    )
    (destination / "objective_schema.json").write_text(
        json.dumps(
            {
                "primary_objective": {"name": "loss", "direction": "minimize"},
            },
            indent=2,
        )
        + "\n"
    )
    for _ in range(args.steps):
        suggested = subprocess.run(
            [sys.executable, "run_bo.py", "suggest", "--json-only"],
            cwd=destination,
            text=True,
            capture_output=True,
            check=True,
        )
        trial = json.loads(suggested.stdout)
        x, y = trial["params"]["x"], trial["params"]["y"]
        loss = (x - 0.3) ** 2 + (y - 0.7) ** 2
        result = {
            "trial_id": trial["trial_id"],
            "params": trial["params"],
            "status": "ok",
            "objectives": {"loss": loss},
        }
        result_path = destination / "examples/ax_result.json"
        result_path.write_text(json.dumps(result) + "\n")
        subprocess.run(
            [sys.executable, "run_bo.py", "ingest", "--results-file", str(result_path)],
            cwd=destination,
            check=True,
            capture_output=True,
            text=True,
        )
        print(json.dumps({"trial_id": trial["trial_id"], "params": trial["params"], "loss": loss}))
    subprocess.run([sys.executable, "run_bo.py", "report"], cwd=destination, check=True)
    subprocess.run([sys.executable, "run_bo.py", "status"], cwd=destination, check=True)


if __name__ == "__main__":
    main()
