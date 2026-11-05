"""Run one small capability walkthrough in a fresh output directory."""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--destination", type=Path, required=True)
    parser.add_argument(
        "--workload",
        choices=("noisy_scalar", "typed_conditional", "measured_scalar", "pareto_tradeoff"),
        default="measured_scalar",
    )
    parser.add_argument("--steps", type=int, default=4)
    parser.add_argument("--initialization", type=int, default=2)
    parser.add_argument("--seed", type=int, choices=(17, 23, 41, 67, 97), default=17)
    args = parser.parse_args()
    subprocess.run(
        [
            sys.executable,
            "-m",
            "benchmarks.ax_capabilities.run",
            "--output",
            str(args.destination.resolve()),
            "--workloads",
            args.workload,
            "--budget",
            str(args.steps),
            "--initialization",
            str(args.initialization),
            "--seeds",
            str(args.seed),
            "--workers",
            "2",
        ],
        cwd=Path(__file__).resolve().parents[2],
        check=True,
    )


if __name__ == "__main__":
    main()
