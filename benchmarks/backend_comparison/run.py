"""Resumable fixed-budget comparisons through portable Looptimum controllers."""

from __future__ import annotations

import argparse
import copy
import fcntl
import hashlib
import json
import math
import os
import platform
import random
import statistics
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from typing import Any, cast

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from benchmarks.backend_comparison import workloads  # noqa: E402

JSON = dict[str, Any]
BACKENDS = ("random", "proxy", "gp", "ax_sobol", "ax")
SEEDS = [17, 29, 41, 53, 67, 79, 97, 113, 131, 149]
LIMITS = {
    "p95_suggest_wall_seconds": 60.0,
    "peak_process_rss_mib": 4096.0,
    "modeled_controller_fraction": 0.10,
}
NUMERICAL_PACKAGES = ("ax-platform", "botorch", "torch", "gpytorch", "numpy", "scipy")


def read(path: Path) -> JSON:
    return cast(JSON, json.loads(path.read_text()))


def write(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, indent=2, allow_nan=False) + "\n")
    temporary.replace(path)


def digest(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, allow_nan=False).encode()).hexdigest()


def versions() -> dict[str, str | None]:
    result: dict[str, str | None] = {}
    for name in NUMERICAL_PACKAGES:
        try:
            result[name] = version(name)
        except PackageNotFoundError:
            result[name] = None
    return result


def source_hashes() -> dict[str, str]:
    paths = [
        ROOT / "benchmarks/__init__.py",
        ROOT / "examples/__init__.py",
        ROOT / "examples/ax_pipeline_tuning/__init__.py",
        *Path(__file__).parent.glob("*.py"),
        *(ROOT / "templates/_shared").glob("*.py"),
        *(ROOT / "templates/bo_client").glob("*.py"),
        ROOT / "templates/bo_client/bo_config.json",
        ROOT / "examples/ax_pipeline_tuning/objective.py",
    ]
    paths.extend((ROOT / "templates/_shared/schemas").glob("*.json"))
    return {
        str(path.relative_to(ROOT)): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(paths)
    }


def protocol(args: argparse.Namespace) -> JSON:
    return {
        "version": 1,
        "budget": args.budget,
        "initialization": args.initialization,
        "seeds": args.seeds,
        "backends": args.backends,
        "workloads": args.workloads,
        "candidate_pool_size": 256,
        "workers": args.workers,
        "evaluator_seconds": float(args.evaluator_seconds),
        "command_timeout_seconds": 180,
        "limits": LIMITS,
        "source_hashes": source_hashes(),
        "versions": versions(),
        "python": platform.python_version(),
        "platform": platform.platform(),
        "threads_per_controller": 1,
        "noise": "paired independent trial-indexed Gaussian draws",
        "primary_quality_metric": "latent regret of the configuration selected by minimum observed value",
        "initialization_comparison": "random/proxy/gp share random warmup; ax/ax_sobol share Sobol warmup",
        "memory_metric": "OS child high-water RSS (largest process, not simultaneous process-tree sum)",
        "execution": "fresh controller process per suggest/ingest; shared OS caches; sequential trials",
    }


def configuration(backend: str, seed: int, plan: JSON) -> JSON:
    cfg = read(ROOT / "templates/bo_client/bo_config.json")
    cfg.update(
        seed=seed,
        max_trials=plan["budget"],
        candidate_pool_size=plan["candidate_pool_size"],
        initial_random_trials=plan["budget"] if backend == "random" else plan["initialization"],
        max_pending_trials=1,
        max_pending_age_seconds=None,
        worker_leases={"enabled": True},
    )
    cfg["surrogate"]["type"] = "gp" if backend == "gp" else "rbf_proxy"
    cfg["optimizer"] = {"backend": "legacy"}
    if backend in ("ax", "ax_sobol"):
        cfg["optimizer"] = {
            "backend": "ax",
            "ax": {
                "initialization_budget": plan["budget"]
                if backend == "ax_sobol"
                else plan["initialization"],
            },
        }
    return cfg


def invoke(
    directory: Path, ordinal: int, command: str, extra: list[str], seed: int, plan: JSON
) -> JSON:
    """Durable command measurements survive an interruption of the benchmark driver."""
    output = directory / "commands" / f"{ordinal:03d}-{command}.json"
    if output.exists():
        result = read(output)
    else:
        request = output.with_suffix(".request.json")
        write(
            request,
            {
                "command": [sys.executable, "run_bo.py", command, *extra],
                "cwd": str(directory / "controller"),
                "timeout": plan["command_timeout_seconds"],
            },
        )
        environment = {
            **os.environ,
            "OMP_NUM_THREADS": "1",
            "MKL_NUM_THREADS": "1",
            "OPENBLAS_NUM_THREADS": "1",
            "VECLIB_MAXIMUM_THREADS": "1",
            "NUMEXPR_NUM_THREADS": "1",
            "PYTHONHASHSEED": str(seed),
            "PYTHONDONTWRITEBYTECODE": "1",
        }
        subprocess.run(
            [
                sys.executable,
                "-m",
                "benchmarks.backend_comparison.measure_command",
                "--request",
                str(request),
                "--output",
                str(output),
            ],
            cwd=ROOT,
            env=environment,
            check=True,
            timeout=plan["command_timeout_seconds"] + 15,
        )
        result = read(output)
    if result["returncode"] != 0:
        raise RuntimeError(f"{command} failed: {result['stderr'][-3000:]}")
    return result


def decision_matches(backend: str, ordinal: int, decision: JSON, plan: JSON) -> bool:
    if backend in ("ax", "ax_sobol"):
        node = "MBM" if backend == "ax" and ordinal > plan["initialization"] else "Sobol"
        return decision.get("surrogate_backend") == "ax" and decision.get("generation_node") == node
    if backend == "random" or ordinal <= plan["initialization"]:
        return decision.get("strategy") == "initial_random" and not decision.get("fallback_reason")
    return decision.get("surrogate_backend") == {"gp": "gp", "proxy": "rbf_proxy"}[backend]


def run_case(output: Path, workload: str, backend: str, seed: int, plan: JSON) -> JSON:
    directory = output / "runs" / workload / backend / str(seed)
    result_path = directory / "result.json"
    if result_path.exists():
        return read(result_path)  # Preserve failed cases too; never silently rerun until they win.
    controller = directory / "controller"
    started = time.perf_counter()
    trials: list[JSON] = []
    result: JSON = {"workload": workload, "backend": backend, "seed": seed, "status": "failed"}
    try:
        if not controller.exists():
            subprocess.run(
                [
                    sys.executable,
                    str(ROOT / "templates/_shared/vendor_copy.py"),
                    str(ROOT / "templates/bo_client"),
                    str(controller),
                ],
                check=True,
                capture_output=True,
                text=True,
            )
            configured = configuration(backend, seed, plan)
            configured["paths"] = read(controller / "bo_config.json")["paths"]
            write(controller / "bo_config.json", configured)
            write(controller / "parameter_space.json", workloads.space(workload))
            write(
                controller / "objective_schema.json",
                {
                    "primary_objective": {"name": "loss", "direction": "minimize"},
                },
            )
            write(directory / "prepared.json", {"protocol_digest": digest(plan)})
        if read(directory / "prepared.json")["protocol_digest"] != digest(plan):
            raise ValueError(
                "Case protocol changed; retain the old evidence and use a fresh output directory"
            )
        for ordinal in range(1, plan["budget"] + 1):
            receipt = directory / "trials" / f"{ordinal:03d}.json"
            state_path = controller / "state/bo_state.json"
            canonical = (
                read(state_path) if state_path.exists() else {"observations": [], "pending": []}
            )
            recorded = next(
                (row for row in canonical["observations"] if row["trial_id"] == ordinal), None
            )
            if receipt.exists():
                trial = read(receipt)
            else:
                pending = next(
                    (row for row in canonical["pending"] if row["trial_id"] == ordinal), None
                )
                command_file = directory / "commands" / f"{ordinal:03d}-suggest.json"
                if pending is not None and not command_file.exists():
                    raise RuntimeError(
                        "Committed suggestion has no timing receipt; preserve this run and use a fresh output root"
                    )
                if recorded is not None:
                    raise RuntimeError(
                        "Canonical result has no benchmark receipt; cannot reconstruct measured resource evidence"
                    )
                measurement = invoke(directory, ordinal, "suggest", ["--json-only"], seed, plan)
                suggestion = pending or json.loads(measurement["stdout"])
                if suggestion["trial_id"] != ordinal or not workloads.valid(
                    suggestion["params"], workload
                ):
                    result["invalid_suggestions"] = 1
                    raise ValueError("Invalid committed suggestion or unexpected public trial ID")
                decisions = [
                    json.loads(line)
                    for line in (controller / "state/acquisition_log.jsonl")
                    .read_text()
                    .splitlines()
                ]
                decision = next(
                    row["decision"] for row in reversed(decisions) if row["trial_id"] == ordinal
                )
                if not decision_matches(backend, ordinal, decision, plan):
                    raise ValueError(f"Unexpected optimizer phase/fallback: {decision}")
                value = workloads.measure(suggestion["params"], workload, seed, ordinal)
                trial = {
                    "trial_id": ordinal,
                    "params": suggestion["params"],
                    "lease_token": suggestion["lease_token"],
                    **value,
                    "decision": decision,
                    "suggest": {
                        key: measurement[key]
                        for key in ("wall_seconds", "cpu_seconds", "peak_process_rss_mib")
                    },
                    "status": "ok",
                }
                write(receipt, trial)  # Persist the observation/noise draw before delivery.
            payload = {
                "trial_id": ordinal,
                "params": trial["params"],
                "objectives": {"loss": trial["observed"]},
                "status": trial["status"],
            }
            if recorded is not None and any(recorded[key] != payload[key] for key in payload):
                raise ValueError("Canonical observation conflicts with benchmark receipt")
            result_file = directory / "trials" / f"{ordinal:03d}-result.json"
            write(result_file, payload)
            if (
                recorded is not None
                and not (directory / "commands" / f"{ordinal:03d}-ingest.json").exists()
            ):
                raise RuntimeError(
                    "Committed ingest has no original resource receipt; a replay cannot reconstruct its cost"
                )
            delivery = invoke(
                directory,
                ordinal,
                "ingest",
                ["--results-file", str(result_file), "--lease-token", trial["lease_token"]],
                seed,
                plan,
            )
            trial["ingest"] = {
                key: delivery[key]
                for key in ("wall_seconds", "cpu_seconds", "peak_process_rss_mib")
            }
            write(receipt, trial)
            trials.append(trial)
        canonical = read(controller / "state/bo_state.json")
        if canonical["pending"] or len(canonical["observations"]) != plan["budget"]:
            raise ValueError("Controller did not finish exactly the declared evaluation budget")
        result.update(status="complete", **metrics(trials, workload, plan))
    except Exception as exc:
        result["error"] = f"{type(exc).__name__}: {exc}"
        result["completed_receipts"] = len(trials)
        state_file = controller / "state/bo_state.json"
        if state_file.exists():
            canonical = read(state_file)
            result["allocated_evaluations"] = len(canonical["observations"]) + len(
                canonical["pending"]
            )
            result["unfinished_evaluations"] = len(canonical["pending"])
            result["terminal_failures"] = sum(
                row["status"] != "ok" for row in canonical["observations"]
            )
    result["elapsed_final_session_seconds"] = time.perf_counter() - started
    write(result_path, result)
    return result


def percentile(values: list[float], quantile: float) -> float:
    ordered = sorted(values)
    position = (len(ordered) - 1) * quantile
    low = math.floor(position)
    high = math.ceil(position)
    return ordered[low] + (ordered[high] - ordered[low]) * (position - low)


def distribution(values: list[float]) -> JSON:
    return {
        "median": statistics.median(values),
        "q25": percentile(values, 0.25),
        "q75": percentile(values, 0.75),
        "iqr": percentile(values, 0.75) - percentile(values, 0.25),
    }


def metrics(trials: list[JSON], workload: str, plan: JSON) -> JSON:
    successful = [row for row in trials if row["status"] == "ok"]
    selected = min(successful, key=lambda row: row["observed"])
    durations = [float(row["suggest"]["wall_seconds"]) for row in trials]
    calls = [row[command] for row in trials for command in ("suggest", "ingest")]
    controller = sum(float(call["wall_seconds"]) for call in calls)
    modeled = controller + len(trials) * plan["evaluator_seconds"]
    seen = {digest(row["params"]) for row in trials}
    peak = max(float(call["peak_process_rss_mib"]) for call in calls)
    return {
        "initial_parameters": [row["params"] for row in trials[: plan["initialization"]]],
        "initial_observations": [row["observed"] for row in trials[: plan["initialization"]]],
        "evaluations": len(trials),
        "successful_evaluations": len(successful),
        "best_observed": selected["observed"],
        "selected_latent": selected["latent"],
        "selected_regret": selected["latent"] - workloads.optimum(workload),
        "best_latent_seen": min(row["latent"] for row in successful),
        "selected_params": selected["params"],
        "failure_rate": 1 - len(successful) / len(trials),
        "repeat_rate": 1 - len(seen) / len(trials),
        "gp_fit_recovery_count": sum("gp_fit_recovery" in row["decision"] for row in trials),
        "feasible_rate": 1.0,
        "suggest_wall_seconds": durations,
        "p95_suggest_wall_seconds": percentile(durations, 0.95),
        "controller_wall_seconds": controller,
        "controller_cpu_seconds": sum(float(call["cpu_seconds"]) for call in calls),
        "peak_process_rss_mib": peak,
        "modeled_campaign_seconds": modeled,
        "modeled_controller_fraction": controller / modeled,
        "generation_nodes": {
            node: sum(
                row["decision"].get("generation_node", row["decision"]["strategy"]) == node
                for row in trials
            )
            for node in sorted(
                {
                    row["decision"].get("generation_node", row["decision"]["strategy"])
                    for row in trials
                }
            )
        },
    }


def summarize(plan: JSON, results: list[JSON]) -> JSON:
    groups = []
    for workload in plan["workloads"]:
        for backend in plan["backends"]:
            complete = [
                row
                for row in results
                if row["workload"] == workload
                and row["backend"] == backend
                and row["status"] == "complete"
            ]
            group: JSON = {
                "workload": workload,
                "backend": backend,
                "completed_seeds": len(complete),
                "expected_seeds": len(plan["seeds"]),
            }
            if len(complete) == len(plan["seeds"]):
                group["gp_fit_recovery_count"] = sum(
                    row.get("gp_fit_recovery_count", 0) for row in complete
                )
                for key in (
                    "best_observed",
                    "selected_regret",
                    "failure_rate",
                    "repeat_rate",
                    "controller_wall_seconds",
                    "controller_cpu_seconds",
                    "modeled_campaign_seconds",
                    "modeled_controller_fraction",
                ):
                    group[key] = distribution([float(row[key]) for row in complete])
                group["p95_suggest_wall_seconds"] = percentile(
                    [duration for row in complete for duration in row["suggest_wall_seconds"]], 0.95
                )
                group["max_process_rss_mib"] = max(row["peak_process_rss_mib"] for row in complete)
                baseline = {
                    row["seed"]: row
                    for row in results
                    if row["workload"] == workload
                    and row["backend"] == "random"
                    and row["status"] == "complete"
                }
                if len(baseline) == len(plan["seeds"]):
                    differences = [
                        baseline[row["seed"]]["selected_regret"] - row["selected_regret"]
                        for row in complete
                    ]
                    group["paired_improvement_vs_random"] = distribution(differences)
                    group["wins_vs_random"] = sum(value > 0 for value in differences)
            groups.append(group)
    expected = {
        (workload, backend, seed)
        for workload in plan["workloads"]
        for backend in plan["backends"]
        for seed in plan["seeds"]
    }
    actual = {(row["workload"], row["backend"], row["seed"]) for row in results}
    all_complete = (
        len(results) == len(expected)
        and actual == expected
        and all(row["status"] == "complete" for row in results)
    )
    completed = [row for row in results if row["status"] == "complete"]
    warmups_match = all_complete
    for workload in plan["workloads"]:
        for seed in plan["seeds"]:
            by_backend = {
                row["backend"]: row
                for row in completed
                if row["workload"] == workload and row["seed"] == seed
            }
            for family in (("random", "proxy", "gp"), ("ax_sobol", "ax")):
                members = [by_backend[backend] for backend in family if backend in by_backend]
                if members:
                    warmups_match = warmups_match and all(
                        row["initial_parameters"] == members[0]["initial_parameters"]
                        and row["initial_observations"] == members[0]["initial_observations"]
                        for row in members
                    )
    gates = {
        "all_declared_cases_complete": all_complete,
        "paired_family_initialization": warmups_match,
        "fixed_evaluation_budgets": all_complete
        and all(row["evaluations"] == plan["budget"] for row in completed),
        "valid_suggestions_and_backend_phases": all_complete
        and not any(row.get("invalid_suggestions", 0) for row in results),
        "suggestion_latency": all_complete
        and all(
            row["p95_suggest_wall_seconds"] <= LIMITS["p95_suggest_wall_seconds"]
            for row in completed
        ),
        "memory": all_complete
        and all(row["peak_process_rss_mib"] <= LIMITS["peak_process_rss_mib"] for row in completed),
        "modeled_overhead": all_complete
        and all(
            row["modeled_controller_fraction"] <= LIMITS["modeled_controller_fraction"]
            for row in completed
        ),
    }
    reference = (
        plan["budget"] == 12
        and plan["initialization"] == 4
        and plan["seeds"] == SEEDS
        and plan["backends"] == list(BACKENDS)
        and plan["workloads"] == list(workloads.WORKLOADS)
        and plan["workers"] == 2
        and plan["evaluator_seconds"] == 3600
    )
    return {
        "schema_version": 1,
        "protocol": plan,
        "reference_protocol": reference,
        "results": results,
        "groups": groups,
        "gates": gates,
        "passed": all(gates.values()),
        "limitations": [
            "Synthetic sequential workloads; no production or asynchronous performance claims.",
            "Seed-level median/IQR is descriptive; no statistical significance or universal superiority claim.",
            "Initialization policies differ; comparisons include their effects.",
            "Best observed noisy scores can be optimistic; selected latent regret is the primary quality measure.",
            "Fresh process overhead includes imports; OS caches and concurrent cases are shared.",
            "RSS is an OS child high-water mark, not simultaneous aggregate memory or GPU memory.",
        ],
    }


def publication_results(results: list[JSON]) -> list[JSON]:
    """Retain full raw diagnostics while excluding local prefixes from published errors."""
    published = copy.deepcopy(results)
    prefixes = {
        str(sys.prefix): "<controller-env>",
        str(ROOT): "<repo>",
        str(ROOT.parent): "<workspace>",
        str(Path.home()): "~",
    }
    for row in published:
        if "error" in row:
            for prefix, label in sorted(prefixes.items(), key=lambda item: -len(item[0])):
                row["error"] = row["error"].replace(prefix, label)
    return published


def report(summary: JSON) -> str:
    lines = [
        "# Optional backend comparison",
        "",
        "Synthetic fixed-budget evidence. Interpret results within the limitations below.",
        "",
        f"Protocol: {'declared ten-seed reference' if summary['reference_protocol'] else 'custom/smoke; not the reference evidence run'}.",
        f"Budget: {summary['protocol']['budget']} evaluations per seed; seeds: {summary['protocol']['seeds']}.",
        f"Initialization: {summary['protocol']['initialization']}; concurrent campaigns: {summary['protocol']['workers']}.",
        f"Modeled evaluator cost: {summary['protocol']['evaluator_seconds']} seconds per evaluation; no actual sleep.",
        "",
        "| Workload | Backend | Seeds | Selected latent regret, median [Q25, Q75] | Suggest p95, s | Peak process MiB | Fit recoveries |",
        "|---|---|---:|---:|---:|---:|---:|",
    ]
    for group in summary["groups"]:
        if "selected_regret" not in group:
            lines.append(
                f"| {group['workload']} | {group['backend']} | {group['completed_seeds']}/{group['expected_seeds']} | incomplete | — | — | — |"
            )
            continue
        values = group["selected_regret"]
        lines.append(
            f"| {group['workload']} | {group['backend']} | {group['completed_seeds']} | {values['median']:.5g} [{values['q25']:.5g}, {values['q75']:.5g}] | {group['p95_suggest_wall_seconds']:.3f} | {group['max_process_rss_mib']:.1f} | {group.get('gp_fit_recovery_count', 0)} |"
        )
    failed = [row for row in summary["results"] if row["status"] != "complete"]
    if failed:
        lines += [
            "",
            "## Incomplete campaigns",
            "",
            "The reference acceptance gate remains unmet. Failed campaigns are retained and incomplete cells have no aggregate quality result.",
            "",
        ]
        for row in failed:
            error = row.get("error", "Unknown failure").splitlines()[-1]
            lines.append(
                f"- {row['workload']} / {row['backend']} / seed {row['seed']}: "
                f"{row.get('allocated_evaluations', '?')} evaluations allocated; {error}"
            )
    lines += [
        "",
        "## Acceptance gates",
        "",
        *[
            f"- {key}: "
            + (
                "pass"
                if value
                else (
                    "not established (incomplete campaign set)"
                    if failed
                    and key not in ("all_declared_cases_complete", "fixed_evaluation_budgets")
                    else "FAIL"
                )
            )
            for key, value in summary["gates"].items()
        ],
        "",
        "## Limits",
        "",
        *[f"- {text}" for text in summary["limitations"]],
        "",
        "Full per-seed scores, observed values, CPU time, failure/repeat rates, phase counts, paired differences, source hashes, and environment versions are in summary.json.",
        "",
    ]
    return "\n".join(lines)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--summarize-only", action="store_true")
    parser.add_argument("--budget", type=int, default=12)
    parser.add_argument("--initialization", type=int, default=4)
    parser.add_argument("--seeds", default=",".join(map(str, SEEDS)))
    parser.add_argument("--backends", default=",".join(BACKENDS))
    parser.add_argument("--workloads", default=",".join(workloads.WORKLOADS))
    parser.add_argument("--workers", type=int, default=2)
    parser.add_argument("--evaluator-seconds", type=float, default=3600)
    parser.add_argument("--write-summary", type=Path)
    parser.add_argument("--write-report", type=Path)
    args = parser.parse_args()
    try:
        args.seeds = [int(value) for value in args.seeds.split(",")]
        args.backends = args.backends.split(",")
        args.workloads = args.workloads.split(",")
        if (
            not 1 <= args.initialization < args.budget
            or args.workers < 1
            or not math.isfinite(args.evaluator_seconds)
            or args.evaluator_seconds <= 0
        ):
            raise ValueError(
                "Require 1 <= initialization < budget, positive workers and finite positive evaluator cost"
            )
        for values, allowed in ((args.backends, BACKENDS), (args.workloads, workloads.WORKLOADS)):
            if not values or len(set(values)) != len(values) or set(values) - set(allowed):
                raise ValueError("Unknown, empty, or repeated backend/workload")
        if (
            not args.seeds
            or len(set(args.seeds)) != len(args.seeds)
            or any(seed < 0 or seed >= 2**32 for seed in args.seeds)
        ):
            raise ValueError("Seeds must be distinct integers in [0, 2**32)")
    except ValueError as exc:
        parser.error(str(exc))
    return args


def main() -> None:
    args = parse_args()
    output = args.output_dir.resolve()
    summary_path = (args.write_summary or output / "summary.json").resolve()
    report_path = (args.write_report or output / "report.md").resolve()
    protected = {ROOT / "benchmarks/summary.json", ROOT / "benchmarks/case_study.md"}
    if summary_path in protected or report_path in protected:
        raise ValueError("Existing golden benchmark evidence must not be overwritten")
    output.mkdir(parents=True, exist_ok=True)
    with (output / ".lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        manifest_path = output / "manifest.json"
        if args.summarize_only:
            plan = read(manifest_path)["protocol"]
        else:
            plan = protocol(args)
            required = {"torch", "gpytorch", "botorch"} if "gp" in args.backends else set()
            if set(args.backends) & {"ax", "ax_sobol"}:
                required.update(NUMERICAL_PACKAGES)
            if any(plan["versions"][name] is None for name in required):
                raise ValueError(
                    "Selected backends require the compatible optional optimizer stack"
                )
            if manifest_path.exists():
                if not args.resume or read(manifest_path)["protocol"] != plan:
                    raise ValueError(
                        "Use --resume with the exact original protocol/source/environment, or a fresh output directory"
                    )
            else:
                if any(path.name != ".lock" for path in output.iterdir()):
                    raise ValueError("A new evidence directory must be empty")
                git_commit = subprocess.check_output(
                    ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True
                ).strip()
                write(
                    manifest_path,
                    {
                        "protocol": plan,
                        "created_at": datetime.now(timezone.utc).isoformat(),
                        "source_commit_at_start": git_commit,
                    },
                )
        jobs = [
            (workload, backend, seed)
            for workload in plan["workloads"]
            for backend in plan["backends"]
            for seed in plan["seeds"]
        ]
        random.Random(20261024).shuffle(jobs)
        if args.summarize_only:
            results = [
                read(output / "runs" / workload / backend / str(seed) / "result.json")
                for workload, backend, seed in jobs
                if (output / "runs" / workload / backend / str(seed) / "result.json").exists()
            ]
        else:

            def run(job: tuple[str, str, int]) -> JSON:
                result = run_case(output, *job, plan)
                print(
                    json.dumps(
                        {key: result[key] for key in ("workload", "backend", "seed", "status")}
                    ),
                    flush=True,
                )
                return result

            with ThreadPoolExecutor(max_workers=args.workers) as executor:
                results = list(executor.map(run, jobs))
        summary = summarize(
            plan,
            publication_results(
                sorted(results, key=lambda row: (row["workload"], row["backend"], row["seed"]))
            ),
        )
        manifest = read(manifest_path)
        summary["provenance"] = {
            "source_commit_at_start": manifest["source_commit_at_start"],
            "started_at": manifest["created_at"],
            "source_identification": "working-tree SHA256 hashes in protocol; commit identifies the baseline",
            "analysis_source_hashes": source_hashes(),
        }
        write(summary_path, summary)
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(report(summary))
        print(
            json.dumps(
                {"passed": summary["passed"], "cases": len(results), "summary": str(summary_path)}
            ),
            flush=True,
        )
        if not summary["passed"]:
            raise SystemExit(1)


if __name__ == "__main__":
    main()
