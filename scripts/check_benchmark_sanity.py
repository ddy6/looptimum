#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
BENCHMARK_RUNNER = REPO_ROOT / "benchmarks" / "run_trial_efficiency_benchmark.py"


REQUIRED_SUMMARY_KEYS = {
    "schema_version",
    "generated_at",
    "objective",
    "metric",
    "seeds",
    "results",
    "per_seed",
    "case_study_source",
}


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run lightweight benchmark sanity checks (shape/contract only)."
    )
    parser.add_argument(
        "--objective",
        default="tiny_quadratic",
        help="Benchmark objective id for sanity check (default: tiny_quadratic).",
    )
    parser.add_argument(
        "--budget",
        type=int,
        default=6,
        help="Tiny budget for fast sanity checks (default: 6).",
    )
    parser.add_argument(
        "--seeds",
        default="17,29",
        help="Comma-separated seeds for sanity check (default: 17,29).",
    )
    return parser.parse_args()


def _run(cmd: list[str]) -> None:
    proc = subprocess.run(
        cmd,
        cwd=str(REPO_ROOT),
        text=True,
        capture_output=True,
        check=False,
    )
    if proc.returncode != 0:
        raise RuntimeError(
            "Benchmark sanity command failed\n"
            f"cmd: {' '.join(cmd)}\n"
            f"returncode: {proc.returncode}\n"
            f"stdout:\n{proc.stdout}\n"
            f"stderr:\n{proc.stderr}"
        )


def _validate_summary(path: Path, expected_objective: str, expected_seed_count: int) -> None:
    payload = json.loads(path.read_text(encoding="utf-8"))
    missing = sorted(REQUIRED_SUMMARY_KEYS - set(payload.keys()))
    if missing:
        raise RuntimeError(f"summary missing keys: {missing}")

    objective = payload.get("objective", {})
    if objective.get("id") != expected_objective:
        raise RuntimeError(
            f"summary objective mismatch: expected {expected_objective}, got {objective.get('id')}"
        )

    metric = payload.get("metric", {})
    if metric.get("name") != "best_objective_at_fixed_budget":
        raise RuntimeError("summary metric.name must be 'best_objective_at_fixed_budget'")

    seeds = payload.get("seeds")
    if not isinstance(seeds, list) or len(seeds) != expected_seed_count:
        raise RuntimeError(f"summary seeds must be list with {expected_seed_count} entries")

    per_seed = payload.get("per_seed")
    if not isinstance(per_seed, list) or len(per_seed) != expected_seed_count:
        raise RuntimeError(f"summary per_seed must be list with {expected_seed_count} entries")


def main() -> int:
    args = _parse_args()
    if not BENCHMARK_RUNNER.exists():
        print(f"benchmark sanity check failed: missing runner {BENCHMARK_RUNNER}")
        return 1

    seeds = [token.strip() for token in args.seeds.split(",") if token.strip()]
    if not seeds:
        print("benchmark sanity check failed: no seeds provided")
        return 1

    with tempfile.TemporaryDirectory(prefix="looptimum_benchmark_sanity_") as temp_dir:
        temp_root = Path(temp_dir)
        summary_path = temp_root / "summary.json"
        case_study_path = temp_root / "case_study.md"

        _run(
            [
                sys.executable,
                str(BENCHMARK_RUNNER),
                "--objective",
                args.objective,
                "--budget",
                str(args.budget),
                "--seeds",
                args.seeds,
                "--write-summary",
                str(summary_path),
                "--write-case-study",
                str(case_study_path),
            ]
        )

        if not summary_path.exists():
            print("benchmark sanity check failed: summary output missing")
            return 1
        if not case_study_path.exists():
            print("benchmark sanity check failed: case-study output missing")
            return 1

        try:
            _validate_summary(
                summary_path,
                expected_objective=args.objective,
                expected_seed_count=len(seeds),
            )
        except RuntimeError as exc:
            print(f"benchmark sanity check failed: {exc}")
            return 1

    print(
        "benchmark sanity check passed "
        f"(objective={args.objective}, budget={args.budget}, seeds={len(seeds)})"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
