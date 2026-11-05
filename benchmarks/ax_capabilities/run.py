"""Bounded, resumable capability evidence through fresh portable Ax controllers."""

from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import os
import platform
import shutil
import statistics
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

from benchmarks.ax_capabilities import workloads as W
from benchmarks.backend_comparison.measure_command import execute

JSON = dict[str, Any]
ROOT = Path(__file__).resolve().parents[2]
CAMPAIGN_SECONDS = 600
WORKER_SECONDS = 120
NUMERICAL_TOLERANCE = 1e-7


def read(path: Path) -> JSON:
    value = json.loads(path.read_text())
    if not isinstance(value, dict):
        raise ValueError(f"Expected a JSON object: {path}")
    return value


def write(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n")
    temporary.replace(path)


def digest(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    ).hexdigest()


def source_hashes() -> dict[str, str]:
    files = [
        *Path(__file__).parent.glob("*.py"),
        *(ROOT / "templates/_shared").glob("*.py"),
        *(ROOT / "templates/_shared/schemas").glob("*.json"),
        ROOT / "templates/bo_client/run_bo.py",
        ROOT / "templates/bo_client/bo_config.json",
        ROOT / "benchmarks/backend_comparison/measure_command.py",
    ]
    return {
        str(path.relative_to(ROOT)): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(files)
    }


def protocol(
    *, budget: int, initialization: int, seeds: list[int], selected: list[str], workers: int
) -> JSON:
    if not 1 <= initialization < budget <= 24 or not 1 <= workers <= 2:
        raise ValueError("Require 1 <= initialization < budget <= 24 and one or two workers")
    if not seeds or len(set(seeds)) != len(seeds) or not set(seeds) <= set(W.SEEDS):
        raise ValueError("Seeds must be a unique nonempty subset of the preregistered five")
    if not selected or len(set(selected)) != len(selected) or not set(selected) <= set(W.WORKLOADS):
        raise ValueError("Select a unique nonempty subset of the four preregistered workloads")
    return {
        "protocol_version": 1,
        "budget": budget,
        "initialization": initialization,
        "seeds": seeds,
        "workloads": selected,
        "workers": workers,
        "maximum_evaluation_slots": len(seeds) * len(selected) * 2 * budget,
        "campaign_seconds": CAMPAIGN_SECONDS,
        "worker_seconds": WORKER_SECONDS,
        "numerical_tolerance": NUMERICAL_TOLERANCE,
        "definitions": {name: W.definition(name) for name in selected},
        "source_hashes": source_hashes(),
        "versions": W.shared("optimizer_backend").dependency_versions(),
        "python": platform.python_version(),
        "platform": platform.platform(),
        "random_baseline": "stdlib uniform conditional sampling with exact typed/linear/forbidden feasibility, no model; all objective and measurement information retained",
        "noise": "paired trial-indexed standardized Gaussian draws; simulator truth is never ingested",
        "full_preregistered_matrix": budget == 24
        and initialization == 6
        and seeds == list(W.SEEDS)
        and selected == list(W.WORKLOADS),
    }


def same_parameters(left: JSON, right: JSON, mapping: JSON) -> bool:
    if set(left) != set(right):
        return False
    kinds = {p["name"]: p["type"] for p in mapping["definitions"]}
    return all(
        abs(left[k] - right[k]) <= NUMERICAL_TOLERANCE
        if kinds[k] == "float"
        else W.CODEC.key(left[k]) == W.CODEC.key(right[k])
        for k in left
    )


def invoke(
    controller: Path, directory: Path, label: str, args: list[str], started_at: float
) -> str:
    remaining = CAMPAIGN_SECONDS - (time.time() - started_at)
    if remaining <= 0:
        raise TimeoutError("Campaign reached its 600-second wall limit")
    result = execute(
        [sys.executable, "run_bo.py", *args], controller, min(remaining, WORKER_SECONDS + 10)
    )
    # CPU/RSS in execute() are process-global child counters. Only its wall time,
    # exit and process-group timeout are used by this concurrent runner.
    result = {
        key: result[key] for key in ("returncode", "timed_out", "wall_seconds", "stdout", "stderr")
    }
    write(directory / "commands" / f"{label}.json", result)
    if result["timed_out"] or result["returncode"]:
        raise RuntimeError(f"Controller command {label} failed: {result['stderr'][-2000:]}")
    return str(result["stdout"])


def prepare_controller(controller: Path, workload: str, seed: int, plan: JSON) -> dict[str, str]:
    # The existing portable copier rejects nonempty destinations and carries
    # the same explicit runtime/schema inventory used by installed examples.
    copied = execute(
        [
            sys.executable,
            str(ROOT / "templates/_shared/vendor_copy.py"),
            str(ROOT / "templates/bo_client"),
            str(controller),
        ],
        ROOT,
        30,
    )
    if copied["returncode"] or copied["timed_out"]:
        raise ValueError(f"Portable copy failed: {copied['stderr'][-2000:]}")
    cfg = read(controller / "bo_config.json")
    cfg.update(
        seed=seed,
        max_trials=plan["budget"],
        max_pending_trials=1,
        max_pending_age_seconds=None,
        worker_leases={"enabled": True},
    )
    cfg["optimizer"] = {
        "backend": "ax",
        "ax": {
            "contract_version": 2,
            "acquisition": W.definition(workload)["acquisition"],
            "initialization_budget": plan["initialization"],
            "generation_timeout_seconds": WORKER_SECONDS,
        },
    }
    spec = W.definition(workload)
    write(controller / "bo_config.json", cfg)
    write(controller / "parameter_space.json", spec["parameter_space"])
    write(controller / "objective_schema.json", spec["objective_schema"])
    if spec["constraints"]:
        write(controller / "constraints.json", spec["constraints"])
    return {
        path.name: hashlib.sha256(path.read_bytes()).hexdigest()
        for path in controller.glob("*.json")
    }


def run_case(output: Path, workload: str, arm: str, seed: int, plan: JSON) -> JSON:
    directory = output / "runs" / workload / arm / str(seed)
    result_path = directory / "result.json"
    if result_path.exists():
        return read(result_path)  # Failed evidence is never silently rerun.
    directory.mkdir(parents=True, exist_ok=True)
    prepared = directory / "prepared.json"
    controller = directory / "controller"
    is_ax = arm != "random"
    trials: list[JSON] = []
    result: JSON = {
        "workload": workload,
        "arm": arm,
        "seed": seed,
        "status": "failed",
        "invalid_public_candidates": 0,
    }
    started_at = time.time()
    restart: JSON | None = None
    try:
        if prepared.exists():
            receipt = read(prepared)
            if receipt["protocol_digest"] != digest(plan):
                raise ValueError("Case protocol differs; preserve evidence")
            started_at = receipt["started_at"]
            expected_configs = receipt["configuration_hashes"]
        else:
            expected_configs = prepare_controller(controller, workload, seed, plan) if is_ax else {}
            write(
                prepared,
                {
                    "protocol_digest": digest(plan),
                    "started_at": started_at,
                    "configuration_hashes": expected_configs,
                },
            )
        if is_ax and any(
            not (controller / name).exists()
            or hashlib.sha256((controller / name).read_bytes()).hexdigest() != sha
            for name, sha in expected_configs.items()
        ):
            raise ValueError("Campaign configuration drift; preserve evidence")
        for ordinal in range(1, plan["budget"] + 1):
            path = directory / "trials" / f"{ordinal:03d}.json"
            if path.exists():
                trial = read(path)
                if trial["evaluation_status"] == "started":
                    raise ValueError("Uncertain prior evaluation effect; never repeat the slot")
            else:
                if time.time() - started_at >= CAMPAIGN_SECONDS:
                    raise TimeoutError("Campaign reached its 600-second wall limit")
                if is_ax:
                    state_path = controller / "state/bo_state.json"
                    canonical = (
                        read(state_path)
                        if state_path.exists()
                        else {"observations": [], "pending": []}
                    )
                    if canonical["pending"] or len(canonical["observations"]) != ordinal - 1:
                        raise ValueError(
                            "Unreceipted prior allocation; preserve evidence without regenerating"
                        )
                    restore_at = max(plan["initialization"] + 1, plan["budget"] // 2 + 1)
                    shadow = directory / "restore-check"
                    if ordinal == restore_at:
                        if shadow.exists():
                            raise ValueError(
                                "Unfinished restore check; preserve uncertain generation cost"
                            )
                        restore_source_sha256 = hashlib.sha256(state_path.read_bytes()).hexdigest()
                        shutil.copytree(controller, shadow)
                    suggestion = json.loads(
                        invoke(
                            controller,
                            directory,
                            f"{ordinal:03d}-suggest",
                            ["suggest", "--json-only"],
                            started_at,
                        )
                    )
                    point = suggestion["params"]
                    decisions = [
                        json.loads(line)
                        for line in (controller / "state/acquisition_log.jsonl")
                        .read_text()
                        .splitlines()
                    ]
                    decision = decisions[-1]["decision"]
                    phase = decision["generation_node"]
                    if ordinal > plan["initialization"] and phase != "MBM":
                        raise ValueError(f"Modeled generation was not observed: {phase}")
                    if ordinal == restore_at:
                        twin = json.loads(
                            invoke(
                                shadow,
                                directory,
                                f"{ordinal:03d}-restore-suggest",
                                ["suggest", "--json-only"],
                                started_at,
                            )
                        )
                        restart = {
                            "ordinal": ordinal,
                            "source_state_sha256": restore_source_sha256,
                            "trial_id_agrees": twin["trial_id"] == suggestion["trial_id"],
                            "parameters_agree": same_parameters(
                                point, twin["params"], W.codec(workload)
                            ),
                            "absolute_float_tolerance": NUMERICAL_TOLERANCE,
                            "shadow_evaluations": 0,
                        }
                        write(directory / "restart.json", restart)
                        if not restart["trial_id_agrees"] or not restart["parameters_agree"]:
                            raise ValueError("Seeded restore differed beyond the fixed tolerance")
                else:
                    point, attempts = W.random_candidate(
                        workload, seed, ordinal, {W.CODEC.key(row["params"]) for row in trials}
                    )
                    suggestion = {"trial_id": ordinal, "params": point}
                    phase, decision = "uniform_random", {"attempts": attempts}
                    restart = {
                        "ordinal": ordinal,
                        "stateless_seeded_replay": W.random_candidate(
                            workload, seed, ordinal, {W.CODEC.key(row["params"]) for row in trials}
                        )[0]
                        == point,
                        "shadow_evaluations": 0,
                    }
                if suggestion["trial_id"] != ordinal or not W.valid(point, workload):
                    result["invalid_public_candidates"] += 1
                    raise ValueError("Invalid candidate or partial/nonmonotonic public allocation")
                if time.time() - started_at >= CAMPAIGN_SECONDS:
                    raise TimeoutError("Campaign reached wall limit before objective invocation")
                trial = {
                    "ordinal": ordinal,
                    "params": point,
                    "generation_phase": phase,
                    "decision": decision,
                    "evaluation_status": "started",
                    "started_at": time.time(),
                }
                write(path, trial)  # Charge the slot before calling the evaluator.
                try:
                    trial["measurement"] = W.measure(point, workload, arm, seed, ordinal)
                    trial["evaluation_status"] = "completed"
                except Exception as exc:
                    trial["evaluation_status"] = "failed"
                    trial["error"] = f"{type(exc).__name__}: {exc}"
                    trial["measurement"] = {
                        "payload": {
                            "status": "failed",
                            "objectives": {
                                name: None
                                for name in W.OBJECTIVES.normalize_objective_schema(
                                    W.definition(workload)["objective_schema"],
                                    contract_version=2,
                                    acquisition=W.definition(workload)["acquisition"],
                                )["objective_names"]
                            },
                        }
                    }
                trial["evaluation_seconds"] = time.time() - trial["started_at"]
                trial["parameter_feasibility"] = W.CODEC.feasible(W.codec(workload), point)
                trial["campaign_wall_seconds"] = time.time() - started_at
                write(path, trial)
            if is_ax:
                canonical = read(controller / "state/bo_state.json")
                prior_observation = next(
                    (row for row in canonical["observations"] if row["trial_id"] == ordinal), None
                )
                if prior_observation is not None:
                    if W.CODEC.key(prior_observation["params"]) != W.CODEC.key(
                        trial["params"]
                    ) or any(
                        prior_observation.get(k) != v
                        for k, v in trial["measurement"]["payload"].items()
                    ):
                        raise ValueError(
                            "Canonical observation and charged benchmark receipt disagree"
                        )
                else:
                    pending = next(
                        row for row in canonical["pending"] if row["trial_id"] == ordinal
                    )
                    payload = {
                        "schema_version": "0.4.0",
                        "trial_id": ordinal,
                        "params": trial["params"],
                        **trial["measurement"]["payload"],
                    }
                    write(directory / "payload.json", payload)
                    invoke(
                        controller,
                        directory,
                        f"{ordinal:03d}-ingest",
                        [
                            "ingest",
                            "--results-file",
                            str(directory / "payload.json"),
                            "--lease-token",
                            pending["lease_token"],
                        ],
                        started_at,
                    )
            trials.append(trial)
        if is_ax:
            canonical = read(controller / "state/bo_state.json")
            if (
                canonical["pending"]
                or len(canonical["observations"]) != plan["budget"]
                or canonical["next_trial_id"] != plan["budget"] + 1
            ):
                raise ValueError("Canonical budget/pending accounting disagrees")
        result.update(
            status="completed",
            restart=read(directory / "restart.json")
            if (directory / "restart.json").exists()
            else restart,
        )
    except Exception as exc:
        result["error"] = f"{type(exc).__name__}: {exc}"
    # Include already charged slots even if ingest or final verification failed.
    trials = [read(path) for path in sorted((directory / "trials").glob("*.json"))]
    result.update(
        metrics=W.metrics(trials, workload),
        wall_seconds=time.time() - started_at,
        modeled_generations=sum(row["generation_phase"] == "MBM" for row in trials),
        initialization_evaluations=sum(row["ordinal"] <= plan["initialization"] for row in trials),
        generation_attempts=sum(
            row["decision"].get("ax_generation_attempts", row["decision"].get("attempts", 0))
            for row in trials
        ),
    )
    write(result_path, result)
    return result


def summarize(output: Path, plan: JSON, results: list[JSON]) -> JSON:
    paired: list[JSON] = []
    for name in plan["workloads"]:
        left, right = W.arms(name)
        key = "feasible_hypervolume" if name == "pareto_tradeoff" else "feasible_simple_regret"
        values = []
        for seed in plan["seeds"]:
            a, b = (
                next(
                    row
                    for row in results
                    if row["workload"] == name and row["arm"] == arm and row["seed"] == seed
                )
                for arm in (left, right)
            )
            av, bv = a["metrics"][key], b["metrics"][key]
            difference = (
                ((av - bv) if name == "pareto_tradeoff" else (bv - av))
                if a["status"] == b["status"] == "completed" and av is not None and bv is not None
                else None
            )
            values.append(
                {
                    "seed": seed,
                    left: av,
                    right: bv,
                    "difference_positive_favors_first_arm": difference,
                }
            )
        differences = [
            row["difference_positive_favors_first_arm"]
            for row in values
            if row["difference_positive_favors_first_arm"] is not None
        ]
        paired.append(
            {
                "workload": name,
                "arms": [left, right],
                "metric": key,
                "per_seed": values,
                "median_paired_difference": statistics.median(differences) if differences else None,
                "range_paired_difference": [min(differences), max(differences)]
                if differences
                else None,
            }
        )
    counts = sum(row["metrics"]["evaluation_slots_attempted"] for row in results)
    recomputed = all(
        read(output / "runs" / row["workload"] / row["arm"] / str(row["seed"]) / "result.json")[
            "metrics"
        ]
        == W.metrics(
            [
                read(path)
                for path in sorted(
                    (
                        output / "runs" / row["workload"] / row["arm"] / str(row["seed"]) / "trials"
                    ).glob("*.json")
                )
            ],
            row["workload"],
        )
        for row in results
    )
    complete = all(
        row["status"] == "completed"
        and row["metrics"]["evaluation_slots_attempted"] == plan["budget"]
        for row in results
    )
    return {
        "protocol": plan,
        "results": results,
        "paired": paired,
        "slots_consumed": counts,
        "hard_gates": {
            "all_cases_complete": complete,
            "fixed_budget": complete and counts == plan["maximum_evaluation_slots"],
            "counts_and_metrics_recompute": recomputed,
            "no_unexplained_evaluation_failures": all(
                row["metrics"]["evaluation_failures"] == 0 for row in results
            ),
            "no_unconfigured_repeats": all(row["metrics"]["repeats"] == 0 for row in results),
            "no_invalid_public_candidates": all(
                row["invalid_public_candidates"] == 0 for row in results
            ),
            "modeled_generation_observed": all(
                row["modeled_generations"] > 0 for row in results if row["arm"] != "random"
            ),
            "seeded_restore": all(
                (row.get("restart") or {}).get(
                    "parameters_agree",
                    (row.get("restart") or {}).get("stateless_seeded_replay", False),
                )
                for row in results
            ),
            "campaign_wall_limits": all(row["wall_seconds"] <= CAMPAIGN_SECONDS for row in results),
        },
        "limitations": "Synthetic CPU evidence; five paired seeds in the full matrix. Uniform feasible random has no model and retains the same outcome information. No superiority claim follows from correctness or a partial run. Restore checks add generation-only cost and zero objective calls.",
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--budget", type=int, default=24)
    parser.add_argument("--initialization", type=int, default=6)
    parser.add_argument("--seeds", default=",".join(map(str, W.SEEDS)))
    parser.add_argument("--workloads", default=",".join(W.WORKLOADS))
    parser.add_argument("--workers", type=int, default=2)
    args = parser.parse_args()
    for key in ("PYTHONPATH", "PYTHONHOME", "PYTHONUSERBASE"):
        os.environ.pop(key, None)
    os.environ.update(PYTHONNOUSERSITE="1", PYTHONDONTWRITEBYTECODE="1")
    plan = protocol(
        budget=args.budget,
        initialization=args.initialization,
        seeds=[int(seed) for seed in args.seeds.split(",")],
        selected=args.workloads.split(","),
        workers=args.workers,
    )
    output = args.output.resolve()
    existed = output.exists() and any(output.iterdir())
    output.mkdir(parents=True, exist_ok=True)
    with (output / ".runner.lock").open("a+") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        manifest = output / "manifest.json"
        if existed:
            if not args.resume or not manifest.exists() or read(manifest)["protocol"] != plan:
                raise ValueError(
                    "Use a fresh output directory or --resume with exact source/environment/protocol hashes"
                )
        else:
            write(manifest, {"protocol": plan, "created_at": time.time()})
        jobs = [
            (name, arm, seed)
            for name in plan["workloads"]
            for arm in W.arms(name)
            for seed in plan["seeds"]
        ]
        with ThreadPoolExecutor(max_workers=args.workers) as pool:
            results = list(
                pool.map(lambda job: run_case(output, job[0], job[1], job[2], plan), jobs)
            )
        summary = summarize(output, plan, results)
        write(output / "summary.json", summary)
        lines = [
            "# Ax capability evidence",
            "",
            f"Evaluation slots consumed: {summary['slots_consumed']}/{plan['maximum_evaluation_slots']}.",
            "",
            summary["limitations"],
            "",
            "| Workload | Median paired difference (positive favors first arm) | Range |",
            "| --- | --- | --- |",
        ]
        lines.extend(
            f"| {row['workload']} ({'/'.join(row['arms'])}) | {row['median_paired_difference']} | {row['range_paired_difference']} |"
            for row in summary["paired"]
        )
        lines.extend(
            [
                "",
                "Hard gates: `" + json.dumps(summary["hard_gates"], sort_keys=True) + "`.",
                "",
                "Per-seed metrics and all failed/incomplete cases are retained in summary.json; raw attempts and command receipts remain under runs/.",
            ]
        )
        (output / "readout.md").write_text("\n".join(lines) + "\n")
        print(
            json.dumps(
                {"slots_consumed": summary["slots_consumed"], "hard_gates": summary["hard_gates"]},
                sort_keys=True,
            )
        )
        if not all(summary["hard_gates"].values()):
            raise SystemExit(1)


if __name__ == "__main__":
    main()
