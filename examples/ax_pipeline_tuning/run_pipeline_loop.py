#!/usr/bin/env python3
"""Demonstrate mixed-parameter tuning with a replaceable external pipeline evaluator."""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from examples.ax_pipeline_tuning.objective import PARAMETER_SPACE  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--destination", type=Path, required=True)
    parser.add_argument("--steps", type=int, default=8)
    parser.add_argument("--initialization", type=int, default=3)
    args = parser.parse_args()
    if not 1 <= args.initialization < args.steps:
        parser.error("Require 1 <= initialization < steps to reach modeled generation")
    destination = args.destination.resolve()
    subprocess.run(
        [
            sys.executable,
            str(ROOT / "templates/_shared/vendor_copy.py"),
            str(ROOT / "templates/bo_client"),
            str(destination),
        ],
        check=True,
    )
    config_path = destination / "bo_config.json"
    config = json.loads(config_path.read_text())
    config.update(
        max_trials=args.steps, worker_leases={"enabled": True}, max_pending_age_seconds=None
    )
    config["optimizer"] = {"backend": "ax", "ax": {"initialization_budget": args.initialization}}
    config_path.write_text(json.dumps(config, indent=2) + "\n")
    (destination / "parameter_space.json").write_text(json.dumps(PARAMETER_SPACE, indent=2) + "\n")
    (destination / "objective_schema.json").write_text(
        json.dumps(
            {
                "primary_objective": {"name": "latency_ms", "direction": "minimize"},
            },
            indent=2,
        )
        + "\n"
    )
    shutil.copy2(Path(__file__).with_name("objective.py"), destination / "evaluate_pipeline.py")
    for _ in range(args.steps):
        proposed = subprocess.run(
            [sys.executable, "run_bo.py", "suggest", "--json-only"],
            cwd=destination,
            capture_output=True,
            text=True,
            check=True,
        )
        suggestion = json.loads(proposed.stdout)
        (destination / "suggestion.json").write_text(proposed.stdout)
        # -S proves this external evaluator has no need for the Ax/numerical stack.
        subprocess.run(
            [
                sys.executable,
                "-S",
                "evaluate_pipeline.py",
                "--suggestion",
                "suggestion.json",
                "--result",
                "pipeline_result.json",
            ],
            cwd=destination,
            check=True,
        )
        subprocess.run(
            [
                sys.executable,
                "-S",
                "run_bo.py",
                "ingest",
                "--results-file",
                "pipeline_result.json",
                "--lease-token",
                suggestion["lease_token"],
            ],
            cwd=destination,
            capture_output=True,
            check=True,
        )
        print((destination / "pipeline_result.json").read_text().strip(), flush=True)
    subprocess.run([sys.executable, "-S", "run_bo.py", "report"], cwd=destination, check=True)
    subprocess.run(
        [sys.executable, "-S", "run_bo.py", "validate", "--strict"], cwd=destination, check=True
    )


if __name__ == "__main__":
    main()
