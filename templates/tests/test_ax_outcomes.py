"""Observed feasibility, exact hypervolume, and genuine vector Ax acquisition."""

from __future__ import annotations

import copy
import importlib.util
import json
import os
import shutil

import pytest
from test_ax_integration import campaign, invoke, state
from test_ax_measurements import OBJECTIVES, config

AVAILABLE = importlib.util.find_spec("ax") is not None
if os.environ.get("LOOPTIMUM_REQUIRE_AX_TESTS") == "1" and not AVAILABLE:
    raise RuntimeError("Required Ax outcome lane did not install the Ax extra")


def observed(trial_id, loss, gain, resource=0.5, status="ok"):
    return {
        "trial_id": trial_id,
        "status": status,
        "params": {"x": 0.5},
        "objectives": {"loss": loss, "gain": gain},
        **({"measurements": {"resource": resource}} if status == "ok" else {}),
    }


def test_inclusive_feasibility_and_best_feasible_do_not_change_legacy_best_ranking():
    cfg = config(pareto=True)
    rows = [
        observed(1, 0, 9, 2),
        observed(2, 8, 3, 1),
        observed(3, 6, 1),
        observed(4, None, None, status="failed"),
    ]
    before = copy.deepcopy(rows)
    result = OBJECTIVES.outcome_summary(rows, cfg)
    assert result["best_feasible"]["trial_id"] == 3
    assert result["outcome_feasibility_counts"] == {"feasible": 2, "infeasible": 1, "unknown": 1}
    assert result["outcome_constraint_status"][0]["constraints"][0]["violation"] == 1
    assert result["outcome_constraint_status"][1]["constraints"][0]["violation"] == 0
    assert result["outcome_constraint_status"][3]["feasible"] is None
    assert set(result["feasible_pareto_front"]["trial_ids"]) == {2, 3}
    assert result["scalar_summary_role"] == "summary_only"
    assert rows == before


def test_no_feasible_or_missing_outcomes_never_select_an_infeasible_best():
    cfg = config(pareto=True)
    missing = observed(2, 1, 1)
    missing.pop("measurements")
    result = OBJECTIVES.outcome_summary([observed(1, 0, 9, 2), missing], cfg)
    assert result["best_feasible"] is None
    assert result["feasible_hypervolume"] == 0
    assert result["outcome_feasibility_counts"] == {"feasible": 0, "infeasible": 1, "unknown": 1}


def test_hypervolume_manual_mixed_direction_boxes_duplicates_and_bad_reference_regions():
    cfg = config(pareto=True)
    cfg["pareto_reference"] = {"loss": 10, "gain": 0}
    rows = [
        observed(1, 8, 3),
        observed(2, 6, 1),
        observed(3, 9, 1),
        observed(4, 8, 3),
        observed(5, 11, 100),
        observed(6, 0, -1),
        observed(7, 10, 10),
    ]
    assert OBJECTIVES.feasible_hypervolume(rows, cfg) == 8  # 2*3 + 4*1 - 2*1
    assert OBJECTIVES.outcome_summary(rows, cfg)["feasible_hypervolume"] == 8
    cfg["pareto_reference"] = {"loss": 10, "gain": 0, "cost": 10}
    cfg["objectives"].append({"name": "cost", "direction": "minimize"})
    cfg["objective_names"].append("cost")
    a, b = observed(1, 8, 3), observed(2, 6, 1)
    a["objectives"]["cost"], b["objectives"]["cost"] = 6, 8
    assert OBJECTIVES.feasible_hypervolume([a, b], cfg) == 28  # 24+8-4


def test_hypervolume_detects_arithmetic_overflow_and_v1_has_no_new_report_fields():
    cfg = config(pareto=True)
    cfg["pareto_reference"] = {"loss": 1e308, "gain": -1e308}
    with pytest.raises(ValueError, match="overflow"):
        OBJECTIVES.feasible_hypervolume([observed(1, -1e308, 1e308)], cfg)
    assert OBJECTIVES.outcome_summary([], {"ax_contract_version": 1}) == {}
    assert OBJECTIVES.outcome_markdown({}) == []


def v2_campaign(tmp_path, variant="bo_client", *, pareto=False):
    project = campaign(tmp_path, variant)
    settings = json.loads((project / "bo_config.json").read_text())
    settings["optimizer"]["ax"].update(
        contract_version=2, acquisition="pareto" if pareto else "scalar"
    )
    (project / "bo_config.json").write_text(json.dumps(settings))
    raw = {
        "primary_objective": {"name": "loss", "direction": "minimize"},
        "measurement_metrics": ["resource"],
        "outcome_constraints": [{"metric": "resource", "op": "<=", "bound": 0.75}],
    }
    if pareto:
        raw.update(
            secondary_objectives=[{"name": "gain", "direction": "maximize"}],
            pareto_reference={"loss": 2, "gain": -1},
        )
    (project / "objective_schema.json").write_text(json.dumps(raw))
    return project


def ingest_v2(project, suggestion, *, pareto=False, resource=0.5):
    x, y = suggestion["params"]["x"], suggestion["params"]["y"]
    objectives = {"loss": (x - 0.2) ** 2 + (y - 0.7) ** 2}
    if pareto:
        objectives["gain"] = x + y
    payload = {
        "schema_version": "0.4.0",
        "trial_id": suggestion["trial_id"],
        "params": suggestion["params"],
        "status": "ok",
        "objectives": objectives,
        "objective_sems": {name: 0.01 for name in objectives},
        "measurements": {"resource": resource},
        "measurement_sems": {"resource": 0.02},
    }
    (project / "result.json").write_text(json.dumps(payload))
    invoke(
        project,
        "ingest",
        "--results-file",
        "result.json",
        "--lease-token",
        suggestion["lease_token"],
        lean=True,
    )
    return payload


@pytest.mark.skipif(not AVAILABLE, reason="optional Ax stack is not installed")
@pytest.mark.parametrize("variant", ["bo_client", "bo_client_full"])
def test_real_pareto_no_feasible_modeling_reports_and_seeded_restore(tmp_path, variant):
    project = v2_campaign(tmp_path, variant, pareto=True)
    initial = json.loads(invoke(project, "suggest", "--count", "2", "--json-only").stdout)[
        "suggestions"
    ]
    for suggestion in reversed(initial):
        ingest_v2(project, suggestion, pareto=True, resource=1.2)
    empty = json.loads(invoke(project, "status", lean=True).stdout)
    assert empty["best"] is not None and empty["best_feasible"] is None
    assert empty["feasible_hypervolume"] == 0
    modeled = json.loads(invoke(project, "suggest", "--json-only").stdout)
    decisions = [
        json.loads(line)
        for line in (project / "state/acquisition_log.jsonl").read_text().splitlines()
    ]
    assert decisions[-1]["decision"]["generation_node"] == "MBM"
    payload = ingest_v2(project, modeled, pareto=True, resource=0.75)
    snapshot = json.loads((project / state(project)["optimizer"]["snapshot"]["path"]).read_text())
    # This is the actual public Ax serialized optimization configuration.
    optimization = snapshot["ax"]["experiment"]["optimization_config"]
    assert optimization["__type"] == "MultiObjectiveOptimizationConfig"
    assert optimization["objective"]["expression"] == "-m0, m1"
    assert len(optimization["objective_thresholds"]) == 2
    assert len(optimization["outcome_constraints"]) == 1
    assert [
        (item["metric"]["name"], item["op"]["name"], item["bound"])
        for item in optimization["objective_thresholds"]
    ] == [("m0", "LEQ", 2.0), ("m1", "GEQ", -1.0)]
    assert "score" not in json.dumps(optimization)
    invoke(project, "report", lean=True)
    report = json.loads((project / "state/report.json").read_text())
    assert report["best_feasible"]["trial_id"] == modeled["trial_id"]
    assert report["outcome_feasibility_counts"] == {"feasible": 1, "infeasible": 2, "unknown": 0}
    trace_row = next(
        row for row in report["objective_trace"] if row["trial_id"] == modeled["trial_id"]
    )
    assert trace_row["objective_sems"] == payload["objective_sems"]
    assert "summary_only" in (project / "state/report.md").read_text()
    twin = tmp_path / "restored"
    shutil.copytree(project, twin)
    a = json.loads(invoke(project, "suggest", "--json-only").stdout)
    b = json.loads(invoke(twin, "suggest", "--json-only").stdout)
    assert a["trial_id"] == b["trial_id"] == 4
    assert a["params"] == pytest.approx(b["params"], abs=1e-7, rel=0)
    invoke(project, "validate", "--strict", lean=True)


@pytest.mark.skipif(not AVAILABLE, reason="optional Ax stack is not installed")
def test_real_format1_upgrade_reprojects_canonical_history_and_keeps_backup(tmp_path):
    from test_ax_integration import ingest

    project = campaign(tmp_path)
    first = json.loads(invoke(project, "suggest", "--count", "2", "--json-only").stdout)[
        "suggestions"
    ]
    for i, suggestion in enumerate(first):
        ingest(project, suggestion, 0.1 + i * 0.2)
    before = (project / "state/bo_state.json").read_bytes()
    settings = json.loads((project / "bo_config.json").read_text())
    settings["optimizer"]["ax"].update(contract_version=2)
    (project / "bo_config.json").write_text(json.dumps(settings))
    result = json.loads(invoke(project, "rebuild-optimizer", "--reason", "explicit opt-in").stdout)
    backup = project / result["rebuild"]["backup_directory"]
    assert (backup / "state-before.json").read_bytes() == before
    rebuilt = state(project)
    assert rebuilt["schema_version"] == "0.5.0"
    assert rebuilt["observations"] == json.loads(before)["observations"]
    candidate = json.loads(invoke(project, "suggest", "--json-only").stdout)
    assert candidate["trial_id"] == 3
    decisions = [
        json.loads(line)
        for line in (project / "state/acquisition_log.jsonl").read_text().splitlines()
    ]
    assert decisions[-1]["decision"]["generation_node"] == "MBM"
