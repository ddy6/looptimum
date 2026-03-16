from __future__ import annotations

import importlib.util
import json
from pathlib import Path

OBJECTIVE_PATH = Path(__file__).resolve().parents[1] / "evaluator" / "objective.py"
SPEC = importlib.util.spec_from_file_location("client_objective", OBJECTIVE_PATH)
assert SPEC is not None and SPEC.loader is not None
OBJECTIVE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(OBJECTIVE)


def _write_case_source(case_dir: Path) -> None:
    system_dir = case_dir / "system"
    system_dir.mkdir(parents=True, exist_ok=True)
    region_lines = "\n".join(
        f"        {name} {{ level (1 1); }}"
        for name in (*OBJECTIVE.NON_PIPE_TARGET_REGIONS, OBJECTIVE.PIPE_REGION)
    )
    (system_dir / "snappyHexMeshDict").write_text(
        (
            "castellatedMeshControls\n"
            "{\n"
            "    nCellsBetweenLevels 2;\n"
            "    resolveFeatureAngle 30;\n"
            "}\n"
            "snapControls\n"
            "{\n"
            "    nSmoothPatch 7;\n"
            "    tolerance 1;\n"
            "    nFeatureSnapIter 7;\n"
            "}\n"
            "refinementSurfaces\n"
            "{\n"
            "    region.stl\n"
            "    {\n"
            "        regions\n"
            "        {\n"
            f"{region_lines}\n"
            "        }\n"
            "    }\n"
            "}\n"
            "refinementRegions\n"
            "{\n"
            "    region\n"
            "    {\n"
            "        mode distance;\n"
            "        levels\n"
            "        (\n"
            "            (0.004 2)\n"
            "            (0.008 1)\n"
            "        );\n"
            "    }\n"
            "}\n"
        ),
        encoding="utf-8",
    )


def test_compute_mesh_loss_uses_thresholded_cell_penalty_and_low_weight_faces() -> None:
    metrics = {
        "total_cells": 260000,
        "N_faces_nonOrtho_gt_70": 50,
        "N_warpedFaces": 3,
        "N_underdeterminedCells": 8,
        "N_lowWeightFaces": 2,
    }

    score, terms = OBJECTIVE._compute_mesh_loss(metrics=metrics)

    assert terms == {
        "underdetermined_term": 400.0,
        "low_weight_term": 20000.0,
        "non_ortho_term": 25.0,
        "warped_faces_term": 6.0,
        "cells_term": 21000.0,
    }
    assert score == 41431.0


def test_compute_acceptance_flags_match_threshold_spec() -> None:
    metrics = {
        "total_cells": 250000,
        "N_faces_nonOrtho_gt_70": 99,
        "N_warpedFaces": 4,
        "N_underdeterminedCells": 9,
        "N_lowWeightFaces": 0,
    }

    flags = OBJECTIVE._compute_acceptance_flags(metrics)

    assert flags == {
        "accept_underdetermined_lt_10": True,
        "accept_low_weight_eq_0": True,
        "accept_non_ortho_lt_100": True,
        "accept_warped_lt_5": True,
        "accept_total_cells_lte_250k": True,
    }


def test_parse_checkmesh_status_recognizes_failed_checks() -> None:
    status = OBJECTIVE._parse_checkmesh_status("Failed 3 mesh checks.\n")

    assert status == {"mesh_ok": False, "failed_checks": 3}


def test_compute_checkmesh_status_penalty_scales_with_failed_checks() -> None:
    assert OBJECTIVE._compute_checkmesh_status_penalty({"mesh_ok": True, "failed_checks": 0}) == 0.0
    assert (
        OBJECTIVE._compute_checkmesh_status_penalty({"mesh_ok": False, "failed_checks": 3})
        == 30000.0
    )
    assert (
        OBJECTIVE._compute_checkmesh_status_penalty({"mesh_ok": False, "failed_checks": None})
        == 10000.0
    )


def test_edit_snappy_dict_updates_pipe_mode_and_refinement_modes(tmp_path: Path) -> None:
    snappy_dict = tmp_path / "snappyHexMeshDict"
    _write_case_source(tmp_path)
    source_dict = tmp_path / "system" / "snappyHexMeshDict"
    snappy_dict.write_text(source_dict.read_text(encoding="utf-8"), encoding="utf-8")

    OBJECTIVE._edit_snappy_dict(
        snappy_dict,
        {
            "castellatedMeshControls.nCellsBetweenLevels": 3,
            "refinementSurfaces.pipe_level_mode": 1,
            "refinementRegions.distance_mode": 2,
            "snapControls.nSmoothPatch": 7,
            "snapControls.tolerance_mode": 3,
        },
    )

    text = snappy_dict.read_text(encoding="utf-8")
    assert "nCellsBetweenLevels 3;" in text
    assert "nSmoothPatch 7;" in text
    assert "tolerance 1;" in text
    assert "nFeatureSnapIter 10;" in text
    assert "resolveFeatureAngle 30;" in text
    assert "(0.004 2)" not in text
    assert "(0.008 1)" not in text
    assert "(0.00025 2)" in text
    assert "(0.00075 1)" in text
    assert f"{OBJECTIVE.PIPE_REGION} {{ level (1 1); }}" in text
    for name in OBJECTIVE.NON_PIPE_TARGET_REGIONS:
        assert f"{name} {{ level (2 2); }}" in text


def test_compute_solver_smoke_penalty_for_incomplete_run() -> None:
    penalty = OBJECTIVE._compute_solver_smoke_penalty(
        {
            "attempted": True,
            "reached_end": False,
            "end_time": 0.4,
            "time_reached": 0.35,
        }
    )

    assert penalty == 550000.0


def test_evaluate_adds_solver_smoke_penalty_below_threshold(tmp_path: Path, monkeypatch) -> None:
    source_case = tmp_path / "source_case"
    run_root = tmp_path / "runs"
    _write_case_source(source_case)

    monkeypatch.setattr(OBJECTIVE, "SOURCE_CASE_DIR", source_case)
    monkeypatch.setattr(OBJECTIVE, "RUN_ROOT_DIR", run_root)
    monkeypatch.setenv("LOOPTIMUM_TRIAL_ID", "9")

    def fake_run_command(cmd: list[str], *, cwd: Path, log_path: Path) -> tuple[int, float]:
        log_path.parent.mkdir(parents=True, exist_ok=True)
        if cmd[0] == "checkMesh":
            log_path.write_text(
                (
                    "Mesh has 240000 cells\n"
                    "*Number of severely non-orthogonal (> 70 degrees) faces: 0\n"
                    "*There are 0 faces with ratio between projected and actual area < 0.8\n"
                    "Cells with small determinant (< 0.001) found, number of cells: 0\n"
                    "Faces with small interpolation weight (< 0.05) found, number of faces: 0\n"
                    "Mesh OK.\n"
                ),
                encoding="utf-8",
            )
        else:
            log_path.write_text("ok\n", encoding="utf-8")
        return 0, 0.1

    smoke_calls: list[Path] = []

    def fake_run_solver_smoke_test(trial_dir: Path) -> dict[str, object]:
        smoke_calls.append(trial_dir)
        return {
            "attempted": True,
            "reached_end": False,
            "end_time": 0.4,
            "time_reached": 0.35,
        }

    monkeypatch.setattr(OBJECTIVE, "_run_command", fake_run_command)
    monkeypatch.setattr(OBJECTIVE, "_run_solver_smoke_test", fake_run_solver_smoke_test)

    result = OBJECTIVE.evaluate(
        {
            "castellatedMeshControls.nCellsBetweenLevels": 1,
            "refinementSurfaces.pipe_level_mode": 1,
            "refinementRegions.distance_mode": 1,
            "snapControls.nSmoothPatch": 7,
            "snapControls.tolerance_mode": 3,
        }
    )

    assert result == {"status": "ok", "objective": 550000.0}
    assert len(smoke_calls) == 1

    summary_path = next(run_root.glob("mesh_trial_*/metrics_summary.json"))
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    assert summary["mesh_loss"] == 0.0
    assert summary["objective_loss"] == 550000.0
    assert summary["score_terms"]["solver_smoke_term"] == 550000.0
    assert summary["solver_smoke"]["attempted"] is True
    assert summary["solver_smoke"]["trial_id"] == 9
    assert summary["solver_smoke"]["time_reached"] == 0.35


def test_evaluate_skips_solver_smoke_at_or_above_threshold(tmp_path: Path, monkeypatch) -> None:
    source_case = tmp_path / "source_case"
    run_root = tmp_path / "runs"
    _write_case_source(source_case)

    monkeypatch.setattr(OBJECTIVE, "SOURCE_CASE_DIR", source_case)
    monkeypatch.setattr(OBJECTIVE, "RUN_ROOT_DIR", run_root)
    monkeypatch.setenv("LOOPTIMUM_TRIAL_ID", "9")

    def fake_run_command(cmd: list[str], *, cwd: Path, log_path: Path) -> tuple[int, float]:
        log_path.parent.mkdir(parents=True, exist_ok=True)
        if cmd[0] == "checkMesh":
            log_path.write_text(
                (
                    "Mesh has 260000 cells\n"
                    "*Number of severely non-orthogonal (> 70 degrees) faces: 0\n"
                    "*There are 0 faces with ratio between projected and actual area < 0.8\n"
                    "Cells with small determinant (< 0.001) found, number of cells: 0\n"
                    "Faces with small interpolation weight (< 0.05) found, number of faces: 0\n"
                    "Mesh OK.\n"
                ),
                encoding="utf-8",
            )
        else:
            log_path.write_text("ok\n", encoding="utf-8")
        return 0, 0.1

    def fail_if_called(trial_dir: Path) -> dict[str, object]:
        raise AssertionError(f"solver smoke should have been skipped for {trial_dir}")

    monkeypatch.setattr(OBJECTIVE, "_run_command", fake_run_command)
    monkeypatch.setattr(OBJECTIVE, "_run_solver_smoke_test", fail_if_called)

    result = OBJECTIVE.evaluate(
        {
            "castellatedMeshControls.nCellsBetweenLevels": 1,
            "refinementSurfaces.pipe_level_mode": 2,
            "refinementRegions.distance_mode": 2,
            "snapControls.nSmoothPatch": 7,
            "snapControls.tolerance_mode": 2,
        }
    )

    assert result == {"status": "ok", "objective": 21000.0}

    summary_path = next(run_root.glob("mesh_trial_*/metrics_summary.json"))
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    assert summary["mesh_loss"] == 21000.0
    assert summary["objective_loss"] == 21000.0
    assert summary["score_terms"]["solver_smoke_term"] == 0.0
    assert summary["solver_smoke"]["attempted"] is False
    assert summary["solver_smoke"]["skip_reason"] == "total_cells >= 250000"
    assert summary["solver_smoke"]["trial_id"] == 9


def test_evaluate_skips_solver_smoke_during_initial_random_trials(
    tmp_path: Path, monkeypatch
) -> None:
    source_case = tmp_path / "source_case"
    run_root = tmp_path / "runs"
    _write_case_source(source_case)

    monkeypatch.setattr(OBJECTIVE, "SOURCE_CASE_DIR", source_case)
    monkeypatch.setattr(OBJECTIVE, "RUN_ROOT_DIR", run_root)
    monkeypatch.setenv("LOOPTIMUM_TRIAL_ID", str(OBJECTIVE.INITIAL_RANDOM_TRIALS))

    def fake_run_command(cmd: list[str], *, cwd: Path, log_path: Path) -> tuple[int, float]:
        log_path.parent.mkdir(parents=True, exist_ok=True)
        if cmd[0] == "checkMesh":
            log_path.write_text(
                (
                    "Mesh has 240000 cells\n"
                    "*Number of severely non-orthogonal (> 70 degrees) faces: 0\n"
                    "*There are 0 faces with ratio between projected and actual area < 0.8\n"
                    "Cells with small determinant (< 0.001) found, number of cells: 0\n"
                    "Faces with small interpolation weight (< 0.05) found, number of faces: 0\n"
                    "Mesh OK.\n"
                ),
                encoding="utf-8",
            )
        else:
            log_path.write_text("ok\n", encoding="utf-8")
        return 0, 0.1

    def fail_if_called(trial_dir: Path) -> dict[str, object]:
        raise AssertionError(f"solver smoke should have been skipped for {trial_dir}")

    monkeypatch.setattr(OBJECTIVE, "_run_command", fake_run_command)
    monkeypatch.setattr(OBJECTIVE, "_run_solver_smoke_test", fail_if_called)

    result = OBJECTIVE.evaluate(
        {
            "castellatedMeshControls.nCellsBetweenLevels": 1,
            "refinementSurfaces.pipe_level_mode": 1,
            "refinementRegions.distance_mode": 1,
            "snapControls.nSmoothPatch": 7,
            "snapControls.tolerance_mode": 3,
        }
    )

    assert result == {"status": "ok", "objective": 0.0}

    summary_path = next(run_root.glob("mesh_trial_*/metrics_summary.json"))
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    assert summary["score_terms"]["solver_smoke_term"] == 0.0
    assert summary["solver_smoke"]["attempted"] is False
    assert summary["solver_smoke"]["skip_reason"] == (
        f"trial_id <= initial_random_trials ({OBJECTIVE.INITIAL_RANDOM_TRIALS})"
    )


def test_evaluate_skips_solver_smoke_when_checkmesh_fails(tmp_path: Path, monkeypatch) -> None:
    source_case = tmp_path / "source_case"
    run_root = tmp_path / "runs"
    _write_case_source(source_case)

    monkeypatch.setattr(OBJECTIVE, "SOURCE_CASE_DIR", source_case)
    monkeypatch.setattr(OBJECTIVE, "RUN_ROOT_DIR", run_root)
    monkeypatch.setenv("LOOPTIMUM_TRIAL_ID", "9")

    def fake_run_command(cmd: list[str], *, cwd: Path, log_path: Path) -> tuple[int, float]:
        log_path.parent.mkdir(parents=True, exist_ok=True)
        if cmd[0] == "checkMesh":
            log_path.write_text(
                (
                    "Mesh has 240000 cells\n"
                    "*Number of severely non-orthogonal (> 70 degrees) faces: 0\n"
                    "*There are 0 faces with ratio between projected and actual area < 0.8\n"
                    "Cells with small determinant (< 0.001) found, number of cells: 0\n"
                    "Faces with small interpolation weight (< 0.05) found, number of faces: 0\n"
                    "Failed 3 mesh checks.\n"
                ),
                encoding="utf-8",
            )
        else:
            log_path.write_text("ok\n", encoding="utf-8")
        return 0, 0.1

    def fail_if_called(trial_dir: Path) -> dict[str, object]:
        raise AssertionError(f"solver smoke should have been skipped for {trial_dir}")

    monkeypatch.setattr(OBJECTIVE, "_run_command", fake_run_command)
    monkeypatch.setattr(OBJECTIVE, "_run_solver_smoke_test", fail_if_called)

    result = OBJECTIVE.evaluate(
        {
            "castellatedMeshControls.nCellsBetweenLevels": 1,
            "refinementSurfaces.pipe_level_mode": 1,
            "refinementRegions.distance_mode": 1,
            "snapControls.nSmoothPatch": 7,
            "snapControls.tolerance_mode": 3,
        }
    )

    assert result == {"status": "ok", "objective": 30000.0}

    summary_path = next(run_root.glob("mesh_trial_*/metrics_summary.json"))
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    assert summary["mesh_loss"] == 30000.0
    assert summary["objective_loss"] == 30000.0
    assert summary["score_terms"]["checkmesh_status_term"] == 30000.0
    assert summary["score_terms"]["solver_smoke_term"] == 0.0
    assert summary["solver_smoke"]["attempted"] is False
    assert summary["solver_smoke"]["failed_mesh_checks"] == 3
    assert summary["solver_smoke"]["skip_reason"] == "checkMesh failed 3 checks"
    assert summary["acceptance_flags"]["accept_checkMesh_mesh_ok"] is False
