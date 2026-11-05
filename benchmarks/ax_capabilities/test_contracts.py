"""Independent mathematical/budget checks; no optional optimizer imports."""

from __future__ import annotations

import copy
from pathlib import Path
from typing import Any

import pytest

from benchmarks.ax_capabilities import workloads as W
from benchmarks.ax_capabilities.run import protocol, same_parameters


def test_preregistered_matrix_caps_calls_workers_and_initialization() -> None:
    plan = protocol(
        budget=24, initialization=6, seeds=list(W.SEEDS), selected=list(W.WORKLOADS), workers=2
    )
    assert plan["maximum_evaluation_slots"] == 960
    assert plan["full_preregistered_matrix"] is True
    for budget, initialization, workers in ((25, 6, 2), (24, 24, 2), (24, 6, 3)):
        with pytest.raises(ValueError):
            protocol(
                budget=budget,
                initialization=initialization,
                seeds=[17],
                selected=[W.WORKLOADS[0]],
                workers=workers,
            )


def test_paired_noise_changes_sem_metadata_without_changing_the_observed_draw() -> None:
    point = {"x": 0.3, "y": 0.7}
    known = W.measure(point, "noisy_scalar", "reported_sem", 17, 1)
    unknown = W.measure(point, "noisy_scalar", "unknown_sem", 17, 1)
    assert known["payload"]["objectives"] == unknown["payload"]["objectives"]
    assert "objective_sems" not in unknown["payload"]
    assert known["payload"]["objective_sems"]["loss"] == pytest.approx(0.038)
    assert "simulator_truth" not in known["payload"]


@pytest.mark.parametrize("workload", W.WORKLOADS)
def test_seeded_uniform_baseline_obeys_all_typed_active_and_parameter_rules(workload: str) -> None:
    blocked: set[str] = set()
    for ordinal in range(1, 9):
        point, attempts = W.random_candidate(workload, 17, ordinal, blocked)
        assert W.valid(point, workload) and 1 <= attempts <= 4096
        assert W.random_candidate(workload, 17, ordinal, blocked)[0] == point
        blocked.add(W.CODEC.key(point))
    assert len(blocked) == 8


def test_analytic_feasible_optimum_and_small_tradeoff_hypervolume() -> None:
    scalar = {"x": 0.65, "y": 0.0499999999999999}
    measurement = W.measure(scalar, "measured_scalar", "random", 17, 1)
    assert measurement["simulator_truth"]["loss"] == pytest.approx(0.045)
    metrics = W.metrics(
        [
            {
                "ordinal": 1,
                "params": scalar,
                "evaluation_status": "completed",
                "measurement": measurement,
            }
        ],
        "measured_scalar",
    )
    assert metrics["feasible_simple_regret"] == pytest.approx(0)
    points = [{"x": 0.0, "y": 0.0}, {"x": 0.8, "y": 0.0}]
    rows = [
        {
            "ordinal": i,
            "params": p,
            "evaluation_status": "completed",
            "measurement": W.measure(p, "pareto_tradeoff", "random", 17, i),
        }
        for i, p in enumerate(points, 1)
    ]
    assert W.metrics(rows, "pareto_tradeoff")["feasible_hypervolume"] == pytest.approx(
        0.26
    )  # 1*.1 + .2*.9 - .2*.1


def test_restore_comparison_never_equates_distinct_typed_choices() -> None:
    mapping = W.codec("typed_conditional")
    a: W.JSON = {"kind": 1.0, "x": 0.2, "y": 0.3, "count": 1}
    b = copy.deepcopy(a)
    b["x"] += 1e-8
    assert same_parameters(a, b, mapping)
    b["kind"] = "1"
    assert not same_parameters(a, b, mapping)


def test_failed_case_retained_and_missing_or_null_restore_is_a_false_gate(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from benchmarks.ax_capabilities import run

    plan = protocol(budget=4, initialization=2, seeds=[17], selected=["noisy_scalar"], workers=1)
    calls: list[int] = []

    def fail_prepare(*args: Any) -> None:
        calls.append(1)
        raise RuntimeError("bounded pre-restore failure")

    monkeypatch.setattr(run, "prepare_controller", fail_prepare)
    results = [
        run.run_case(tmp_path, "noisy_scalar", arm, 17, plan) for arm in W.arms("noisy_scalar")
    ]
    results[0]["restart"] = None
    result_path = tmp_path / "runs/noisy_scalar/reported_sem/17/result.json"
    run.write(result_path, results[0])
    summary = run.summarize(tmp_path, plan, results)
    assert summary["slots_consumed"] == 0
    assert summary["hard_gates"]["seeded_restore"] is False
    assert summary["hard_gates"]["all_cases_complete"] is False
    assert run.run_case(tmp_path, "noisy_scalar", "reported_sem", 17, plan) == results[0]
    assert len(calls) == 2


def test_evaluation_failure_consumes_one_slot_without_replacement_or_rerun(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from benchmarks.ax_capabilities import run

    plan = protocol(budget=4, initialization=2, seeds=[17], selected=["measured_scalar"], workers=1)
    original = W.measure
    calls: list[int] = []

    def fail_one(point: W.JSON, workload: str, arm: str, seed: int, ordinal: int) -> W.JSON:
        calls.append(ordinal)
        if ordinal == 2:
            raise RuntimeError("bounded synthetic evaluation failure")
        return original(point, workload, arm, seed, ordinal)

    monkeypatch.setattr(W, "measure", fail_one)
    result = run.run_case(tmp_path, "measured_scalar", "random", 17, plan)
    assert calls == [1, 2, 3, 4]
    assert result["metrics"]["evaluation_slots_attempted"] == 4
    assert result["metrics"]["evaluations_completed"] == 3
    assert result["metrics"]["evaluation_failures"] == 1
    assert run.run_case(tmp_path, "measured_scalar", "random", 17, plan) == result
    assert calls == [1, 2, 3, 4]


def test_a_later_failure_preserves_a_completed_restore_checkpoint(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from benchmarks.ax_capabilities import run

    plan = protocol(budget=4, initialization=2, seeds=[17], selected=["noisy_scalar"], workers=1)
    checkpoint = {
        "ordinal": 3,
        "trial_id_agrees": True,
        "parameters_agree": True,
        "absolute_float_tolerance": 1e-7,
        "shadow_evaluations": 0,
    }

    def fail_after_checkpoint(controller: Path, *args: Any) -> None:
        run.write(controller.parent / "restart.json", checkpoint)
        raise RuntimeError("failure after a completed restore checkpoint")

    monkeypatch.setattr(run, "prepare_controller", fail_after_checkpoint)
    results = [
        run.run_case(tmp_path, "noisy_scalar", arm, 17, plan) for arm in W.arms("noisy_scalar")
    ]
    assert all(row["status"] == "failed" and row["restart"] == checkpoint for row in results)
    summary = run.summarize(tmp_path, plan, results)
    assert summary["hard_gates"]["seeded_restore"] is True
    assert summary["hard_gates"]["all_cases_complete"] is False
    assert summary["slots_consumed"] == 0


def test_independent_loss_sweep_volume_matches_manual_union() -> None:
    from benchmarks.ax_capabilities.audit import volume

    assert volume([(8, 3), (6, 1), (9, 1), (11, 100), (0, -1), (8, 3)], 10, 0) == 8
