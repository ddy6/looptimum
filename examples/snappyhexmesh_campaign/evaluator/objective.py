#!/usr/bin/env python3
"""Sanitized one-trial snappyHexMesh evaluator for Looptimum.

This public example preserves the scoring and parsing structure from the
campaign case study while replacing private paths and domain-specific region
labels with placeholders.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

PROJECT_ROOT_DIR = Path(__file__).resolve().parents[1]
SOURCE_CASE_DIR = Path(
    os.environ.get("LOOPTIMUM_SNAPPY_TEMPLATE_CASE_DIR", "/path/to/reference_case")
)
RUN_ROOT_DIR = Path(os.environ.get("LOOPTIMUM_SNAPPY_RUN_ROOT", "/tmp/looptimum_mesh_runs"))
FAILURE_PENALTY_OBJECTIVE = float(os.environ.get("LOOPTIMUM_SNAPPY_FAILURE_PENALTY", "1e9"))
CELL_COUNT_THRESHOLD = 250_000
CHECKMESH_FAILED_CHECK_PENALTY = float(
    os.environ.get("LOOPTIMUM_CHECKMESH_FAILED_CHECK_PENALTY", "10000")
)
SOLVER_SMOKE_END_TIME = float(os.environ.get("LOOPTIMUM_SOLVER_SMOKE_END_TIME", "0.4"))
SOLVER_SMOKE_BASE_PENALTY = float(os.environ.get("LOOPTIMUM_SOLVER_SMOKE_BASE_PENALTY", "500000"))
SOLVER_SMOKE_SHORTFALL_WEIGHT = float(
    os.environ.get("LOOPTIMUM_SOLVER_SMOKE_SHORTFALL_WEIGHT", "1000000")
)
RESUME_PINGER_PATH = Path(
    os.environ.get("LOOPTIMUM_RESUME_PINGER_PATH", "/path/to/resumePinger.py")
)
TRIAL_ID_ENV_VAR = "LOOPTIMUM_TRIAL_ID"

# Current baseline keeps non-focus surfaces at the stable `(2 2)` level.
FIXED_NON_PIPE_REGION_LEVEL = (2, 2)
FIXED_FEATURE_SNAP_ITER = 10
PIPE_REGION_LEVEL_MODES: dict[int, tuple[int, int]] = {
    1: (1, 1),
    2: (2, 2),
}
REFINEMENT_REGION_DISTANCE_MODES: dict[int, tuple[tuple[float, int], ...]] = {
    1: ((0.00025, 1),),
    2: ((0.00025, 2), (0.00075, 1)),
    3: ((0.0005, 2), (0.0015, 1)),
    4: ((0.00075, 2), (0.0025, 1)),
}
TOLERANCE_MODES: dict[int, float] = {
    1: 0.15,
    2: 0.5,
    3: 1.0,
}
NON_PIPE_TARGET_REGIONS = (
    "region_01",
    "region_02",
    "region_03",
    "region_04",
    "region_05",
    "region_06",
    "region_07",
    "region_08",
    "region_09",
)
PIPE_REGION = "focus_region"

CRITICAL_METRIC_PATTERNS = {
    "N_faces_nonOrtho_gt_70": r"\*Number of severely non-orthogonal \(> 70 degrees\) faces:\s*(\d+)",
    "N_warpedFaces": r"\*There are\s*(\d+)\s*faces with ratio between projected and actual area < 0\.8",
    "N_underdeterminedCells": r"Cells with small determinant \(< 0\.001\) found, number of cells:\s*(\d+)",
    "N_lowWeightFaces": r"Faces with small interpolation weight \(< 0\.05\) found, number of faces:\s*(\d+)",
}
TOTAL_CELLS_PATTERNS = (r"Mesh has\s+(\d+)\s+cells", r"cells:\s*(\d+)")


def _load_initial_random_trials(config_path: Path) -> int:
    try:
        payload = json.loads(config_path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return 4
    value = payload.get("initial_random_trials", 4)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return 4
    return max(0, int(value))


INITIAL_RANDOM_TRIALS = _load_initial_random_trials(PROJECT_ROOT_DIR / "project" / "bo_config.json")


def _failure_payload(reason: str) -> dict[str, Any]:
    return {
        "status": "failed",
        "objective": None,
        "penalty_objective": FAILURE_PENALTY_OBJECTIVE,
        "terminal_reason": reason,
        "failure_reason": reason,
    }


def _require_int(params: dict[str, Any], key: str) -> int:
    value = params.get(key)
    if isinstance(value, bool):
        raise ValueError(f"parameter {key} must be an integer, got bool")
    if not isinstance(value, (int, float)):
        raise ValueError(f"parameter {key} must be numeric")
    return int(value)


def _require_float(params: dict[str, Any], key: str) -> float:
    value = params.get(key)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"parameter {key} must be numeric")
    return float(value)


def _build_trial_dir(run_root: Path) -> Path:
    run_root.mkdir(parents=True, exist_ok=True)
    timestamp = time.strftime("%Y%m%d_%H%M%S")
    suffix = f"{os.getpid()}_{time.time_ns() % 1_000_000_000}"
    return run_root / f"mesh_trial_{timestamp}_{suffix}"


def _copy_source_case(source: Path, trial_dir: Path) -> None:
    if not source.exists() or not source.is_dir():
        raise FileNotFoundError(f"source case directory not found: {source}")
    if trial_dir.exists():
        raise RuntimeError(f"trial directory already exists unexpectedly: {trial_dir}")

    # Keep copy lightweight while preserving required case inputs.
    ignore = shutil.ignore_patterns(".git", "log.*", "dynamicCode", "postProcessing", "processor*")
    shutil.copytree(source, trial_dir, symlinks=True, ignore=ignore)


def _replace_single(text: str, pattern: str, replacement: str, description: str) -> str:
    out, count = re.subn(pattern, replacement, text, flags=re.M | re.S)
    if count != 1:
        raise RuntimeError(f"expected exactly one replacement for {description}, found {count}")
    return out


def _replace_region_level(text: str, region_name: str, level_a: int, level_b: int) -> str:
    pattern = (
        rf"(?m)^(\s*{re.escape(region_name)}\s*\{{\s*level\s*)"
        rf"\(\s*\d+\s+\d+\s*\)"
        rf"(\s*;.*)$"
    )
    replacement = rf"\1({level_a} {level_b})\2"
    out, count = re.subn(pattern, replacement, text, count=1)
    if count != 1:
        raise RuntimeError(f"expected exactly one refinement line match for region '{region_name}'")
    return out


def _replace_refinement_region_levels(text: str, levels: tuple[tuple[float, int], ...]) -> str:
    pattern = re.compile(
        r"(?ms)(refinementRegions\s*\{.*?\bregion\s*\{.*?\blevels\s*)"
        r"\(\s*(?:\(\s*[^()]+\s*\)\s*)+\)"
        r"(\s*;)"
    )

    def repl(match: re.Match[str]) -> str:
        formatted_levels = "".join(
            f"\n               ({distance:.12g} {level})" for distance, level in levels
        )
        return f"{match.group(1)}({formatted_levels}\n            ){match.group(2)}"

    out, count = pattern.subn(repl, text, count=1)
    if count != 1:
        raise RuntimeError("expected exactly one refinementRegions.levels block")
    return out


def _braces_balanced(text: str) -> bool:
    depth = 0
    for ch in text:
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth < 0:
                return False
    return depth == 0


def _edit_snappy_dict(snappy_dict_path: Path, params: dict[str, Any]) -> None:
    text = snappy_dict_path.read_text(encoding="utf-8")

    n_cells_between_levels = _require_int(params, "castellatedMeshControls.nCellsBetweenLevels")
    n_smooth_patch = _require_int(params, "snapControls.nSmoothPatch")
    tolerance_mode = _require_int(params, "snapControls.tolerance_mode")
    pipe_level_mode = _require_int(params, "refinementSurfaces.pipe_level_mode")
    refinement_distance_mode = _require_int(params, "refinementRegions.distance_mode")

    if not (1 <= n_cells_between_levels <= 3):
        raise ValueError(
            "castellatedMeshControls.nCellsBetweenLevels must be within [1, 3], "
            f"got {n_cells_between_levels}"
        )
    if not (5 <= n_smooth_patch <= 7):
        raise ValueError(f"snapControls.nSmoothPatch must be within [5, 7], got {n_smooth_patch}")
    if tolerance_mode not in TOLERANCE_MODES:
        raise ValueError(
            "snapControls.tolerance_mode must be one of "
            f"{sorted(TOLERANCE_MODES)}, got {tolerance_mode}"
        )
    if pipe_level_mode not in PIPE_REGION_LEVEL_MODES:
        raise ValueError(
            "refinementSurfaces.pipe_level_mode must be one of "
            f"{sorted(PIPE_REGION_LEVEL_MODES)}, got {pipe_level_mode}"
        )
    if refinement_distance_mode not in REFINEMENT_REGION_DISTANCE_MODES:
        raise ValueError(
            "refinementRegions.distance_mode must be one of "
            f"{sorted(REFINEMENT_REGION_DISTANCE_MODES)}, got {refinement_distance_mode}"
        )

    non_pipe_level_a, non_pipe_level_b = FIXED_NON_PIPE_REGION_LEVEL
    pipe_level_a, pipe_level_b = PIPE_REGION_LEVEL_MODES[pipe_level_mode]
    refinement_levels = REFINEMENT_REGION_DISTANCE_MODES[refinement_distance_mode]
    tolerance = TOLERANCE_MODES[tolerance_mode]

    text = _replace_single(
        text,
        r"(?ms)(castellatedMeshControls\s*\{.*?\bnCellsBetweenLevels\s+)(\d+)(;)",
        rf"\g<1>{n_cells_between_levels}\g<3>",
        "castellatedMeshControls.nCellsBetweenLevels",
    )
    text = _replace_single(
        text,
        r"(?ms)(snapControls\s*\{.*?\bnSmoothPatch\s+)(\d+)(;)",
        rf"\g<1>{n_smooth_patch}\g<3>",
        "snapControls.nSmoothPatch",
    )
    text = _replace_single(
        text,
        r"(?ms)(snapControls\s*\{.*?\btolerance\s+)([^;\n]+)(;)",
        rf"\g<1>{tolerance:.12g}\g<3>",
        "snapControls.tolerance",
    )
    text = _replace_single(
        text,
        r"(?ms)(snapControls\s*\{.*?\bnFeatureSnapIter\s+)(\d+)(;)",
        rf"\g<1>{FIXED_FEATURE_SNAP_ITER}\g<3>",
        "snapControls.nFeatureSnapIter",
    )
    text = _replace_refinement_region_levels(text, refinement_levels)

    for region in NON_PIPE_TARGET_REGIONS:
        text = _replace_region_level(
            text,
            region_name=region,
            level_a=non_pipe_level_a,
            level_b=non_pipe_level_b,
        )
    text = _replace_region_level(
        text,
        region_name=PIPE_REGION,
        level_a=pipe_level_a,
        level_b=pipe_level_b,
    )

    if not _braces_balanced(text):
        raise RuntimeError("snappyHexMeshDict braces became unbalanced after edits")

    snappy_dict_path.write_text(text, encoding="utf-8")


def _run_command(cmd: list[str], *, cwd: Path, log_path: Path) -> tuple[int, float]:
    start = time.monotonic()
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("w", encoding="utf-8") as log_fh:
        log_fh.write(f"# cwd: {cwd}\n")
        log_fh.write(f"# cmd: {' '.join(cmd)}\n")
        log_fh.flush()
        proc = subprocess.run(
            cmd,
            cwd=str(cwd),
            stdout=log_fh,
            stderr=subprocess.STDOUT,
            check=False,
        )
        log_fh.flush()
        os.fsync(log_fh.fileno())
    elapsed = float(time.monotonic() - start)
    return int(proc.returncode), elapsed


def _parse_optional_int(pattern: str, text: str) -> int | None:
    m = re.search(pattern, text, flags=re.M | re.S)
    if not m:
        return None
    try:
        return int(m.group(1))
    except ValueError:
        try:
            return int(float(m.group(1)))
        except ValueError:
            return None


def _parse_checkmesh_metrics(log_text: str) -> tuple[dict[str, int], list[str]]:
    metrics: dict[str, int] = {}
    parse_errors: list[str] = []

    total_cells = None
    for pattern in TOTAL_CELLS_PATTERNS:
        total_cells = _parse_optional_int(pattern, log_text)
        if total_cells is not None:
            break
    if total_cells is None:
        parse_errors.append("total_cells")
    else:
        metrics["total_cells"] = total_cells

    severe_non_ortho = _parse_optional_int(
        CRITICAL_METRIC_PATTERNS["N_faces_nonOrtho_gt_70"], log_text
    )
    if severe_non_ortho is None:
        if "severely non-orthogonal" in log_text:
            parse_errors.append("N_faces_nonOrtho_gt_70")
        else:
            severe_non_ortho = 0
    metrics["N_faces_nonOrtho_gt_70"] = int(severe_non_ortho)

    warped_faces = _parse_optional_int(CRITICAL_METRIC_PATTERNS["N_warpedFaces"], log_text)
    if warped_faces is None:
        if "ratio between projected and actual area < 0.8" in log_text:
            parse_errors.append("N_warpedFaces")
        else:
            warped_faces = 0
    metrics["N_warpedFaces"] = int(warped_faces)

    underdetermined = _parse_optional_int(
        CRITICAL_METRIC_PATTERNS["N_underdeterminedCells"], log_text
    )
    if underdetermined is None:
        if re.search(r"small determinant\s*\(<\s*0\.001\)", log_text):
            parse_errors.append("N_underdeterminedCells")
        else:
            underdetermined = 0
    metrics["N_underdeterminedCells"] = int(underdetermined)

    low_weight_faces = _parse_optional_int(CRITICAL_METRIC_PATTERNS["N_lowWeightFaces"], log_text)
    if low_weight_faces is None:
        if re.search(r"small interpolation weight\s*\(<\s*0\.05\)", log_text):
            parse_errors.append("N_lowWeightFaces")
        else:
            low_weight_faces = 0
    metrics["N_lowWeightFaces"] = int(low_weight_faces)

    return metrics, sorted(set(parse_errors))


def _parse_checkmesh_status(log_text: str) -> dict[str, Any]:
    failed_checks = _parse_optional_int(r"Failed\s+(\d+)\s+mesh checks\.", log_text)
    mesh_ok = re.search(r"(?m)^\s*Mesh OK\.\s*$", log_text) is not None
    if mesh_ok and failed_checks is None:
        failed_checks = 0
    return {
        "mesh_ok": bool(mesh_ok and (failed_checks is None or int(failed_checks) == 0)),
        "failed_checks": int(failed_checks) if failed_checks is not None else None,
    }


def _current_trial_id() -> int | None:
    raw = os.environ.get(TRIAL_ID_ENV_VAR, "").strip()
    if not raw:
        return None
    try:
        trial_id = int(raw)
    except ValueError:
        return None
    if trial_id < 1:
        return None
    return trial_id


def _compute_acceptance_flags(metrics: dict[str, int]) -> dict[str, bool]:
    return {
        "accept_underdetermined_lt_10": int(metrics["N_underdeterminedCells"]) < 10,
        "accept_low_weight_eq_0": int(metrics["N_lowWeightFaces"]) == 0,
        "accept_non_ortho_lt_100": int(metrics["N_faces_nonOrtho_gt_70"]) < 100,
        "accept_warped_lt_5": int(metrics["N_warpedFaces"]) < 5,
        "accept_total_cells_lte_250k": int(metrics["total_cells"]) <= CELL_COUNT_THRESHOLD,
    }


def _compute_checkmesh_status_penalty(checkmesh_status: dict[str, Any]) -> float:
    if bool(checkmesh_status.get("mesh_ok")):
        return 0.0
    failed_checks = checkmesh_status.get("failed_checks")
    if isinstance(failed_checks, int) and failed_checks > 0:
        return CHECKMESH_FAILED_CHECK_PENALTY * float(failed_checks)
    return CHECKMESH_FAILED_CHECK_PENALTY


def _compute_mesh_loss(metrics: dict[str, int]) -> tuple[float, dict[str, float]]:
    total_cells = int(metrics["total_cells"])
    underdetermined = int(metrics["N_underdeterminedCells"])
    non_ortho = int(metrics["N_faces_nonOrtho_gt_70"])
    warped = int(metrics["N_warpedFaces"])
    low_weight = int(metrics["N_lowWeightFaces"])

    terms = {
        "underdetermined_term": 1000.0 * max(0, underdetermined - 9)
        + 50.0 * float(underdetermined),
        "low_weight_term": 10000.0 * float(low_weight),
        "non_ortho_term": 50.0 * max(0, non_ortho - 99) + 0.5 * float(non_ortho),
        "warped_faces_term": 200.0 * max(0, warped - 4) + 2.0 * float(warped),
    }
    if total_cells > CELL_COUNT_THRESHOLD:
        terms["cells_term"] = 0.1 * float(total_cells - CELL_COUNT_THRESHOLD) + 20000.0
    return float(sum(terms.values())), terms


def _compute_solver_smoke_penalty(solver_smoke: dict[str, Any] | None) -> float:
    if not solver_smoke or not solver_smoke.get("attempted"):
        return 0.0
    if solver_smoke.get("reached_end"):
        return 0.0

    end_time = float(solver_smoke.get("end_time") or SOLVER_SMOKE_END_TIME)
    time_reached = solver_smoke.get("time_reached")
    try:
        reached = max(0.0, float(time_reached))
    except (TypeError, ValueError):
        reached = 0.0

    shortfall = max(0.0, end_time - reached)
    return SOLVER_SMOKE_BASE_PENALTY + SOLVER_SMOKE_SHORTFALL_WEIGHT * shortfall


def _solver_smoke_skip_reason(
    *, trial_id: int | None, total_cells: int, checkmesh_status: dict[str, Any]
) -> str | None:
    if trial_id is None:
        return "trial_id unavailable"
    if trial_id <= INITIAL_RANDOM_TRIALS:
        return f"trial_id <= initial_random_trials ({INITIAL_RANDOM_TRIALS})"
    if total_cells >= CELL_COUNT_THRESHOLD:
        return f"total_cells >= {CELL_COUNT_THRESHOLD}"
    if not bool(checkmesh_status.get("mesh_ok")):
        failed_checks = checkmesh_status.get("failed_checks")
        if isinstance(failed_checks, int):
            return f"checkMesh failed {failed_checks} checks"
        return "checkMesh did not report Mesh OK."
    return None


def _run_solver_smoke_test(trial_dir: Path) -> dict[str, Any]:
    if not RESUME_PINGER_PATH.exists():
        raise FileNotFoundError(f"resumePinger.py not found: {RESUME_PINGER_PATH}")

    summary_path = trial_dir / "solver_smoke_summary.json"
    command = [
        sys.executable,
        str(RESUME_PINGER_PATH),
        "--new",
        "--case-dir",
        str(trial_dir),
        "--smoke-end-time",
        f"{SOLVER_SMOKE_END_TIME:.12g}",
        "--summary-json",
        str(summary_path),
        "--disable-notifications",
        "--disable-snapshots",
    ]
    rc, elapsed = _run_command(
        command, cwd=trial_dir.parent, log_path=trial_dir / "log.resumePinger"
    )
    if not summary_path.exists():
        raise RuntimeError(f"resumePinger did not write solver summary: rc={rc}")

    solver_smoke = json.loads(summary_path.read_text(encoding="utf-8"))
    solver_smoke["attempted"] = True
    solver_smoke["command_exit_code"] = rc
    solver_smoke["command_elapsed_seconds"] = elapsed
    return solver_smoke


def _write_trial_summary(
    trial_dir: Path,
    *,
    params: dict[str, Any],
    status: str,
    runtime_seconds: float,
    command_timings: dict[str, float],
    command_exit_codes: dict[str, int],
    metrics: dict[str, int] | None,
    acceptance_flags: dict[str, bool] | None,
    score_terms: dict[str, float] | None,
    mesh_loss: float | None,
    objective_loss: float | None,
    solver_smoke: dict[str, Any] | None,
    failure_reason: str | None,
) -> None:
    payload = {
        "params": params,
        "status": status,
        "runtime_seconds": runtime_seconds,
        "command_timings": command_timings,
        "command_exit_codes": command_exit_codes,
        "metrics": metrics,
        "acceptance_flags": acceptance_flags,
        "score_terms": score_terms,
        "mesh_loss": mesh_loss,
        "objective_loss": objective_loss,
        "solver_smoke": solver_smoke,
        "failure_reason": failure_reason,
    }
    (trial_dir / "metrics_summary.json").write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )


def evaluate(params: dict[str, Any]) -> float | dict[str, Any]:
    """Run one non-destructive snappyHexMesh trial and return a scalar loss."""
    trial_dir: Path | None = None
    start_wall = time.monotonic()
    command_timings: dict[str, float] = {}
    command_exit_codes: dict[str, int] = {}
    failure_reason: str | None = None

    try:
        trial_dir = _build_trial_dir(RUN_ROOT_DIR)
        _copy_source_case(SOURCE_CASE_DIR, trial_dir)

        snappy_dict_path = trial_dir / "system" / "snappyHexMeshDict"
        if not snappy_dict_path.exists():
            raise FileNotFoundError(f"missing snappyHexMeshDict in copied case: {snappy_dict_path}")

        _edit_snappy_dict(snappy_dict_path, params)

        commands = [
            ("blockMesh", ["blockMesh"], trial_dir / "log.blockMesh"),
            ("snappyHexMesh", ["snappyHexMesh", "-overwrite"], trial_dir / "log.snappyHexMesh"),
            (
                "checkMesh",
                ["checkMesh", "-allGeometry", "-allTopology"],
                trial_dir / "log.checkMesh",
            ),
        ]

        for name, command, log_path in commands:
            rc, elapsed = _run_command(command, cwd=trial_dir, log_path=log_path)
            command_timings[name] = elapsed
            command_exit_codes[name] = rc
            if rc != 0:
                failure_reason = f"{name} exited with code {rc}"
                raise RuntimeError(failure_reason)

        checkmesh_log = (trial_dir / "log.checkMesh").read_text(encoding="utf-8", errors="replace")
        metrics, parse_errors = _parse_checkmesh_metrics(checkmesh_log)
        if parse_errors:
            failure_reason = f"missing required checkMesh metrics: {', '.join(parse_errors)}"
            raise RuntimeError(failure_reason)

        runtime_seconds = float(time.monotonic() - start_wall)
        trial_id = _current_trial_id()
        checkmesh_status = _parse_checkmesh_status(checkmesh_log)
        acceptance_flags = _compute_acceptance_flags(metrics)
        if bool(checkmesh_status["mesh_ok"]):
            acceptance_flags["accept_checkMesh_mesh_ok"] = True
        else:
            acceptance_flags["accept_checkMesh_mesh_ok"] = False
        mesh_loss, score_terms = _compute_mesh_loss(metrics=metrics)
        checkmesh_status_term = _compute_checkmesh_status_penalty(checkmesh_status)
        score_terms["checkmesh_status_term"] = checkmesh_status_term
        mesh_loss += checkmesh_status_term
        solver_smoke = {
            "attempted": False,
            "trial_id": trial_id,
            "initial_random_trials": INITIAL_RANDOM_TRIALS,
            "checkmesh_passed": bool(checkmesh_status["mesh_ok"]),
            "failed_mesh_checks": checkmesh_status["failed_checks"],
            "end_time": SOLVER_SMOKE_END_TIME,
            "time_reached": None,
            "reached_end": False,
        }
        skip_reason = _solver_smoke_skip_reason(
            trial_id=trial_id,
            total_cells=int(metrics["total_cells"]),
            checkmesh_status=checkmesh_status,
        )
        if skip_reason is None:
            solver_smoke = {
                **solver_smoke,
                **_run_solver_smoke_test(trial_dir),
            }
        else:
            solver_smoke["skip_reason"] = skip_reason
        solver_smoke_term = _compute_solver_smoke_penalty(solver_smoke)
        score_terms["solver_smoke_term"] = solver_smoke_term
        objective_loss = mesh_loss + solver_smoke_term
        _write_trial_summary(
            trial_dir,
            params=params,
            status="ok",
            runtime_seconds=runtime_seconds,
            command_timings=command_timings,
            command_exit_codes=command_exit_codes,
            metrics=metrics,
            acceptance_flags=acceptance_flags,
            score_terms=score_terms,
            mesh_loss=mesh_loss,
            objective_loss=objective_loss,
            solver_smoke=solver_smoke,
            failure_reason=None,
        )
        return {"status": "ok", "objective": objective_loss}
    except Exception as exc:
        failure_reason = failure_reason or str(exc) or exc.__class__.__name__
        runtime_seconds = float(time.monotonic() - start_wall)
        if trial_dir is not None:
            trial_dir.mkdir(parents=True, exist_ok=True)
            _write_trial_summary(
                trial_dir,
                params=params,
                status="failed",
                runtime_seconds=runtime_seconds,
                command_timings=command_timings,
                command_exit_codes=command_exit_codes,
                metrics=None,
                acceptance_flags=None,
                score_terms=None,
                mesh_loss=None,
                objective_loss=None,
                solver_smoke=None,
                failure_reason=failure_reason,
            )
        return _failure_payload(failure_reason)
