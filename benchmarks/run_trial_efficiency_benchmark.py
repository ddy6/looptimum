#!/usr/bin/env python3
"""Compare Looptimum trial-efficiency vs random search at a fixed budget."""

from __future__ import annotations

import argparse
import json
import math
import random
import shutil
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

REPO_ROOT = Path(__file__).resolve().parents[1]
TEMPLATES_SOURCE = REPO_ROOT / "templates"
TEMPLATE_SOURCE = TEMPLATES_SOURCE / "bo_client_demo"

DEFAULT_SEEDS = [17, 29, 41, 53, 67, 79, 97, 113, 131, 149]


@dataclass(frozen=True)
class ObjectiveSpec:
    objective_id: str
    description: str
    evaluate: Callable[[dict[str, float]], float]


def _require_float(params: dict[str, float], name: str) -> float:
    if name not in params:
        raise KeyError(f"missing parameter: {name}")
    value = params[name]
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError(f"parameter {name} must be numeric")
    return float(value)


def _tiny_quadratic(params: dict[str, float]) -> float:
    x1 = _require_float(params, "x1")
    x2 = _require_float(params, "x2")
    base = (x1 - 0.32) ** 2 + (x2 - 0.74) ** 2
    pseudo_noise = 0.012 * math.sin(29.0 * x1 + 41.0 * x2)
    return float(base + pseudo_noise)


def _anisotropic_quadratic(params: dict[str, float]) -> float:
    """Optional second objective with mild anisotropy and deterministic perturbation."""
    x1 = _require_float(params, "x1")
    x2 = _require_float(params, "x2")
    base = 1.8 * (x1 - 0.18) ** 2 + 0.35 * (x2 - 0.86) ** 2
    perturbation = 0.008 * math.cos(13.0 * x1 - 17.0 * x2)
    return float(base + perturbation)


OBJECTIVES: dict[str, ObjectiveSpec] = {
    "tiny_quadratic": ObjectiveSpec(
        objective_id="tiny_quadratic",
        description=(
            "Canonical deterministic pseudo-noisy quadratic objective used in the tiny loop demo."
        ),
        evaluate=_tiny_quadratic,
    ),
    "anisotropic_quadratic": ObjectiveSpec(
        objective_id="anisotropic_quadratic",
        description=(
            "Low-maintenance secondary objective with anisotropic curvature and deterministic perturbation."
        ),
        evaluate=_anisotropic_quadratic,
    ),
}


@dataclass
class RunResult:
    best_objective: float
    best_params: dict[str, float]
    best_trace: list[float]
    failure_rate: float


@dataclass
class SeedBenchmark:
    seed: int
    looptimum: RunResult
    random_search: RunResult


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Run fixed-budget trial-efficiency benchmark comparing Looptimum against random search."
        )
    )
    parser.add_argument(
        "--objective",
        choices=sorted(OBJECTIVES.keys()),
        default="tiny_quadratic",
        help="Objective family to evaluate (default: tiny_quadratic).",
    )
    parser.add_argument(
        "--budget",
        type=int,
        default=20,
        help="Fixed evaluation budget per seed (default: 20).",
    )
    parser.add_argument(
        "--seeds",
        default=",".join(str(seed) for seed in DEFAULT_SEEDS),
        help="Comma-separated integer seeds (default: 10-seed baseline).",
    )
    parser.add_argument(
        "--write-summary",
        default=str(REPO_ROOT / "benchmarks" / "summary.json"),
        help="Output path for compact summary JSON.",
    )
    parser.add_argument(
        "--write-case-study",
        default=str(REPO_ROOT / "benchmarks" / "case_study.md"),
        help="Output path for generated compact case-study markdown.",
    )
    parser.add_argument(
        "--raw-artifacts-dir",
        default=None,
        help=(
            "Optional directory for per-seed raw traces. "
            "Use for release evidence runs; keep out of git by default."
        ),
    )
    parser.add_argument(
        "--keep-temp-dir",
        action="store_true",
        help="Keep temporary benchmark workspace for debugging.",
    )
    return parser.parse_args()


def _parse_seeds(raw: str) -> list[int]:
    seeds: list[int] = []
    for token in raw.split(","):
        text = token.strip()
        if not text:
            continue
        value = int(text)
        if value < 0:
            raise ValueError(f"seed must be non-negative: {value}")
        seeds.append(value)
    if not seeds:
        raise ValueError("at least one seed is required")
    return seeds


def _run_command(cmd: list[str], *, cwd: Path) -> str:
    proc = subprocess.run(
        cmd,
        cwd=str(cwd),
        text=True,
        capture_output=True,
        check=False,
    )
    if proc.returncode != 0:
        raise RuntimeError(
            "Command failed\n"
            f"cmd: {' '.join(cmd)}\n"
            f"returncode: {proc.returncode}\n"
            f"stdout:\n{proc.stdout}\n"
            f"stderr:\n{proc.stderr}"
        )
    return proc.stdout


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def _prepare_temp_project(temp_root: Path, *, seed: int, budget: int) -> Path:
    temp_templates = temp_root / "templates"
    project_root = temp_templates / "bo_client_demo"
    ignore = shutil.ignore_patterns(
        "__pycache__",
        "*.pyc",
        ".DS_Store",
        "bo_state.json",
        "observations.csv",
        "acquisition_log.jsonl",
        "event_log.jsonl",
        "report.json",
        "report.md",
        ".looptimum.lock",
    )
    shutil.copytree(TEMPLATES_SOURCE, temp_templates, ignore=ignore)

    state_dir = project_root / "state"
    state_dir.mkdir(parents=True, exist_ok=True)
    for child in state_dir.iterdir():
        if child.name == ".gitkeep":
            continue
        if child.is_dir():
            shutil.rmtree(child)
        else:
            child.unlink()

    config_path = project_root / "bo_config.json"
    cfg = json.loads(config_path.read_text(encoding="utf-8"))
    if not isinstance(cfg, dict):
        raise ValueError("bo_config.json must be an object")
    cfg["seed"] = int(seed)
    cfg["max_trials"] = int(budget)
    config_path.write_text(json.dumps(cfg, indent=2) + "\n", encoding="utf-8")
    return project_root


def _load_parameter_specs() -> list[dict[str, Any]]:
    raw = json.loads((TEMPLATE_SOURCE / "parameter_space.json").read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError("parameter_space.json must be an object")
    specs = raw.get("parameters")
    if not isinstance(specs, list) or not specs:
        raise ValueError("parameter_space.parameters must be a non-empty list")
    out: list[dict[str, Any]] = []
    for idx, spec in enumerate(specs):
        if not isinstance(spec, dict):
            raise ValueError(f"parameter spec at index {idx} must be an object")
        out.append(spec)
    return out


def _sample_random_params(rng: random.Random, specs: list[dict[str, Any]]) -> dict[str, float]:
    params: dict[str, float] = {}
    for spec in specs:
        name = str(spec["name"])
        ptype = str(spec["type"])
        bounds = spec.get("bounds")
        if not isinstance(bounds, list) or len(bounds) != 2:
            raise ValueError(f"invalid bounds for parameter {name}")
        lo = float(bounds[0])
        hi = float(bounds[1])
        if ptype == "float":
            params[name] = float(rng.uniform(lo, hi))
        elif ptype == "int":
            params[name] = float(rng.randint(int(lo), int(hi)))
        else:
            raise ValueError(f"unsupported parameter type in benchmark sampling: {ptype}")
    return params


def _run_looptimum_seed(
    *,
    seed: int,
    budget: int,
    objective: ObjectiveSpec,
    keep_temp_dir: bool,
) -> RunResult:
    temp_root = Path(tempfile.mkdtemp(prefix=f"looptimum_benchmark_seed_{seed}_"))
    try:
        project_root = _prepare_temp_project(temp_root, seed=seed, budget=budget)
        run_bo = project_root / "run_bo.py"
        result_path = project_root / "state" / "benchmark_result.json"

        best_value = float("inf")
        best_params: dict[str, float] = {}
        best_trace: list[float] = []

        for _ in range(budget):
            suggestion_stdout = _run_command(
                [
                    sys.executable,
                    str(run_bo),
                    "suggest",
                    "--project-root",
                    str(project_root),
                    "--json-only",
                ],
                cwd=REPO_ROOT,
            )
            suggestion = json.loads(suggestion_stdout)
            if not isinstance(suggestion, dict):
                raise ValueError("suggest output must be an object")

            params_raw = suggestion.get("params")
            if not isinstance(params_raw, dict):
                raise ValueError("suggest output missing params object")
            params = {str(k): float(v) for k, v in params_raw.items()}
            value = float(objective.evaluate(params))
            if value < best_value:
                best_value = value
                best_params = dict(params)
            best_trace.append(best_value)

            result_payload = {
                "schema_version": suggestion.get("schema_version", "0.3.0"),
                "trial_id": suggestion["trial_id"],
                "params": params_raw,
                "objectives": {"loss": value},
                "status": "ok",
            }
            _write_json(result_path, result_payload)

            _run_command(
                [
                    sys.executable,
                    str(run_bo),
                    "ingest",
                    "--project-root",
                    str(project_root),
                    "--results-file",
                    str(result_path),
                ],
                cwd=REPO_ROOT,
            )

        return RunResult(
            best_objective=best_value,
            best_params=best_params,
            best_trace=best_trace,
            failure_rate=0.0,
        )
    finally:
        if keep_temp_dir:
            print(f"[benchmark] kept temp dir for seed {seed}: {temp_root}")
        else:
            shutil.rmtree(temp_root, ignore_errors=True)


def _run_random_seed(*, seed: int, budget: int, objective: ObjectiveSpec) -> RunResult:
    specs = _load_parameter_specs()
    rng = random.Random(seed)
    best_value = float("inf")
    best_params: dict[str, float] = {}
    best_trace: list[float] = []
    for _ in range(budget):
        params = _sample_random_params(rng, specs)
        value = float(objective.evaluate(params))
        if value < best_value:
            best_value = value
            best_params = dict(params)
        best_trace.append(best_value)
    return RunResult(
        best_objective=best_value,
        best_params=best_params,
        best_trace=best_trace,
        failure_rate=0.0,
    )


def _percentile(values: list[float], p: float) -> float:
    if not values:
        raise ValueError("cannot compute percentile of empty list")
    if len(values) == 1:
        return values[0]
    ordered = sorted(values)
    rank = (len(ordered) - 1) * p
    lo = int(math.floor(rank))
    hi = int(math.ceil(rank))
    if lo == hi:
        return ordered[lo]
    weight = rank - lo
    return ordered[lo] * (1.0 - weight) + ordered[hi] * weight


def _iqr(values: list[float]) -> float:
    return _percentile(values, 0.75) - _percentile(values, 0.25)


def _build_summary(
    *,
    objective: ObjectiveSpec,
    budget: int,
    seeds: list[int],
    runs: list[SeedBenchmark],
) -> dict[str, Any]:
    looptimum_best = [row.looptimum.best_objective for row in runs]
    random_best = [row.random_search.best_objective for row in runs]

    median_looptimum = _percentile(looptimum_best, 0.5)
    median_random = _percentile(random_best, 0.5)

    best_seed_run = min(runs, key=lambda row: row.looptimum.best_objective)
    per_seed = []
    for row in runs:
        delta = row.random_search.best_objective - row.looptimum.best_objective
        per_seed.append(
            {
                "seed": row.seed,
                "looptimum_best_objective": row.looptimum.best_objective,
                "random_best_objective": row.random_search.best_objective,
                "delta_best_objective_vs_random": delta,
            }
        )

    win_count = sum(
        1 for row in runs if row.looptimum.best_objective < row.random_search.best_objective
    )

    return {
        "schema_version": "0.1.0",
        "generated_at": time.time(),
        "objective": {
            "id": objective.objective_id,
            "description": objective.description,
            "direction": "minimize",
        },
        "metric": {
            "name": "best_objective_at_fixed_budget",
            "budget": budget,
            "seed_count": len(seeds),
            "required_seed_count": 10,
        },
        "seeds": seeds,
        "results": {
            "looptimum": {
                "median_best_objective": median_looptimum,
                "iqr_best_objective": _iqr(looptimum_best),
                "per_seed_best_objective": looptimum_best,
            },
            "random_search": {
                "median_best_objective": median_random,
                "iqr_best_objective": _iqr(random_best),
                "per_seed_best_objective": random_best,
            },
            "comparison": {
                "median_improvement_vs_random": median_random - median_looptimum,
                "win_rate_vs_random": win_count / len(runs),
            },
        },
        "per_seed": per_seed,
        "case_study_source": {
            "best_seed": best_seed_run.seed,
            "best_objective": best_seed_run.looptimum.best_objective,
            "best_params": best_seed_run.looptimum.best_params,
            "failure_rate": best_seed_run.looptimum.failure_rate,
        },
    }


def _render_case_study(summary: dict[str, Any], summary_path_label: str) -> str:
    objective = summary["objective"]
    metric = summary["metric"]
    results = summary["results"]
    source = summary["case_study_source"]

    return "\n".join(
        [
            "# Phase 8 Benchmark Case Study",
            "",
            "This case study is generated directly from benchmark summary artifacts.",
            "",
            "## Objective",
            "",
            f"- Objective id: `{objective['id']}`",
            f"- Description: {objective['description']}",
            f"- Direction: `{objective['direction']}`",
            "",
            "## Benchmark Protocol",
            "",
            f"- Fixed budget per seed: `{metric['budget']}`",
            f"- Seed count: `{metric['seed_count']}`",
            f"- Canonical metric: `{metric['name']}`",
            "",
            "## Outcome Summary",
            "",
            f"- Looptimum median best objective: `{results['looptimum']['median_best_objective']:.6f}`",
            f"- Random-search median best objective: `{results['random_search']['median_best_objective']:.6f}`",
            f"- Median improvement vs random: `{results['comparison']['median_improvement_vs_random']:.6f}`",
            f"- Win rate vs random: `{results['comparison']['win_rate_vs_random']:.2%}`",
            "",
            "## Reliability Signal",
            "",
            f"- Failure rate (best-seed exemplar run): `{source['failure_rate']:.2%}`",
            "",
            "## Best Config Excerpt",
            "",
            f"- Seed: `{source['best_seed']}`",
            f"- Best objective: `{source['best_objective']:.6f}`",
            f"- Params: `{json.dumps(source['best_params'], sort_keys=True)}`",
            "",
            "## Traceability",
            "",
            f"- Source summary artifact: `{summary_path_label}`",
            "",
        ]
    )


def _write_raw_seed_artifact(raw_dir: Path, run: SeedBenchmark) -> None:
    payload = {
        "seed": run.seed,
        "looptimum": {
            "best_objective": run.looptimum.best_objective,
            "best_params": run.looptimum.best_params,
            "best_trace": run.looptimum.best_trace,
        },
        "random_search": {
            "best_objective": run.random_search.best_objective,
            "best_params": run.random_search.best_params,
            "best_trace": run.random_search.best_trace,
        },
    }
    _write_json(raw_dir / f"seed_{run.seed}.json", payload)


def main() -> None:
    args = _parse_args()
    if args.budget < 1:
        raise SystemExit("--budget must be >= 1")

    seeds = _parse_seeds(args.seeds)
    objective = OBJECTIVES[args.objective]

    print(f"[benchmark] objective={objective.objective_id} budget={args.budget} seeds={len(seeds)}")

    runs: list[SeedBenchmark] = []
    for seed in seeds:
        looptimum = _run_looptimum_seed(
            seed=seed,
            budget=args.budget,
            objective=objective,
            keep_temp_dir=args.keep_temp_dir,
        )
        random_search = _run_random_seed(seed=seed, budget=args.budget, objective=objective)
        runs.append(SeedBenchmark(seed=seed, looptimum=looptimum, random_search=random_search))
        print(
            "[benchmark] "
            f"seed={seed} looptimum={looptimum.best_objective:.6f} "
            f"random={random_search.best_objective:.6f}"
        )

    summary = _build_summary(objective=objective, budget=args.budget, seeds=seeds, runs=runs)

    summary_path = Path(args.write_summary).resolve()
    _write_json(summary_path, summary)
    print(f"[benchmark] wrote summary: {summary_path}")

    try:
        summary_path_label = summary_path.relative_to(REPO_ROOT).as_posix()
    except ValueError:
        summary_path_label = summary_path.as_posix()

    case_study_path = Path(args.write_case_study).resolve()
    case_study_path.parent.mkdir(parents=True, exist_ok=True)
    case_study_path.write_text(
        _render_case_study(summary, summary_path_label),
        encoding="utf-8",
    )
    print(f"[benchmark] wrote case study: {case_study_path}")

    if args.raw_artifacts_dir:
        raw_dir = Path(args.raw_artifacts_dir).resolve()
        raw_dir.mkdir(parents=True, exist_ok=True)
        for run in runs:
            _write_raw_seed_artifact(raw_dir, run)
        print(f"[benchmark] wrote raw per-seed artifacts: {raw_dir}")


if __name__ == "__main__":
    main()
