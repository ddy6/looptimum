"""Recompute benchmark counts and 2D volume independently, with zero evaluator calls."""

from __future__ import annotations

import argparse
import math
from pathlib import Path
from typing import Any

from benchmarks.ax_capabilities import workloads as W
from benchmarks.ax_capabilities.run import read, source_hashes, write

JSON = dict[str, Any]


def volume(
    points: list[tuple[float, float]], loss_reference: float, gain_reference: float
) -> float:
    # Sweep loss from best to worst. Each increasing gain adds a disjoint strip.
    best_gain, total = gain_reference, 0.0
    for loss, gain in sorted(points):
        if loss < loss_reference and gain > best_gain:
            total += (loss_reference - loss) * (gain - best_gain)
            best_gain = gain
    return total


def audit(output: Path, *, require_current_sources: bool = True) -> JSON:
    summary = read(output / "summary.json")
    plan = summary["protocol"]
    errors: list[str] = []
    consumed = 0
    expected_jobs = {
        (name, arm, seed)
        for name in plan["workloads"]
        for arm in W.arms(name)
        for seed in plan["seeds"]
    }
    if {
        (row["workload"], row["arm"], row["seed"]) for row in summary["results"]
    } != expected_jobs or len(summary["results"]) != len(expected_jobs):
        errors.append("Case identities/count disagree with the declared matrix")
    if require_current_sources and plan["source_hashes"] != source_hashes():
        errors.append("Current source hashes differ from the measured source")
    noise_draws: dict[tuple[int, int], float] = {}
    for result in summary["results"]:
        name, arm, seed = result["workload"], result["arm"], result["seed"]
        case = output / "runs" / name / arm / str(seed)
        trials = [read(path) for path in sorted((case / "trials").glob("*.json"))]
        consumed += len(trials)
        if len(trials) > plan["budget"] or [row["ordinal"] for row in trials] != list(
            range(1, len(trials) + 1)
        ):
            errors.append(f"{name}/{arm}/{seed}: invalid charged slot identities")
        if result["status"] != "completed" or len(trials) != plan["budget"]:
            errors.append(f"{name}/{arm}/{seed}: incomplete/failed case retained")
        feasible = []
        for row in trials:
            if not W.valid(row["params"], name):
                errors.append(f"{name}/{arm}/{seed}: invalid public point")
            if row["evaluation_status"] != "completed":
                continue
            measurement = row["measurement"]
            payload = measurement["payload"]
            if any(
                key in payload
                for key in ("simulator_truth", "simulator_sem", "standardized_noise_draw")
            ):
                errors.append("Simulator truth leaked into a model payload")
            expected_mean = (
                measurement["simulator_truth"]["loss"]
                + measurement["simulator_sem"] * measurement["standardized_noise_draw"]
            )
            if not math.isclose(
                payload["objectives"]["loss"], expected_mean, rel_tol=0, abs_tol=1e-14
            ):
                errors.append("Recorded observation disagrees with its paired noise receipt")
            if name == "noisy_scalar":
                key = (seed, row["ordinal"])
                if (
                    key in noise_draws
                    and noise_draws[key] != measurement["standardized_noise_draw"]
                ):
                    errors.append("Paired standardized draws differ")
                noise_draws[key] = measurement["standardized_noise_draw"]
            constraints = plan["definitions"][name]["objective_schema"].get(
                "outcome_constraints", []
            )
            if all(
                payload["measurements"][item["metric"]] <= item["bound"]
                if item["op"] == "<="
                else payload["measurements"][item["metric"]] >= item["bound"]
                for item in constraints
            ):
                feasible.append(row)
        actual: float | None
        if name == "pareto_tradeoff":
            reference = plan["definitions"][name]["objective_schema"]["pareto_reference"]
            actual = volume(
                [
                    (
                        row["measurement"]["payload"]["objectives"]["loss"],
                        row["measurement"]["payload"]["objectives"]["gain"],
                    )
                    for row in feasible
                ],
                reference["loss"],
                reference["gain"],
            )
            expected = result["metrics"]["feasible_hypervolume"]
        else:
            actual = (
                max(
                    0.0,
                    min(row["measurement"]["simulator_truth"]["loss"] for row in feasible)
                    - plan["definitions"][name]["scalar_optimum"],
                )
                if feasible
                else None
            )
            expected = result["metrics"]["feasible_simple_regret"]
        if actual != expected and (
            actual is None
            or expected is None
            or not math.isclose(actual, expected, rel_tol=0, abs_tol=1e-12)
        ):
            errors.append(f"{name}/{arm}/{seed}: independent quality metric mismatch")
        fraction = len(feasible) / len(trials) if trials else 0
        if (
            fraction != result["metrics"]["feasible_fraction"]
            or len(trials) != result["metrics"]["evaluation_slots_attempted"]
        ):
            errors.append(f"{name}/{arm}/{seed}: independent count/feasibility mismatch")
    if consumed != summary["slots_consumed"] or consumed > plan["maximum_evaluation_slots"]:
        errors.append("Aggregate slot accounting mismatch")
    return {
        "passed": not errors,
        "errors": errors,
        "slots_consumed": consumed,
        "cases": len(summary["results"]),
        "evaluator_invocations": 0,
        "method": "raw receipt count, observed inclusive bounds, scalar latent regret, independent loss-sweep 2D hypervolume",
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = audit(args.output)
    write(args.output / "audit.json", result)
    print(result)
    if not result["passed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
