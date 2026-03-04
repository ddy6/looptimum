#!/usr/bin/env python3
"""Run a tiny end-to-end Looptimum loop with a deterministic noisy quadratic."""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[3]
TEMPLATES_SRC = REPO_ROOT / "templates"
RUN_ONE_EVAL = REPO_ROOT / "client_harness_template" / "run_one_eval.py"
OBJECTIVE_MODULE = Path(__file__).resolve().with_name("objective.py")


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run suggest/evaluate/ingest demo loop using tiny quadratic objective."
    )
    parser.add_argument(
        "--steps",
        type=int,
        default=6,
        help="Number of suggest/evaluate/ingest iterations (default: 6).",
    )
    parser.add_argument(
        "--write-acquisition-log",
        default=None,
        help="Optional output path for copied acquisition log JSONL.",
    )
    parser.add_argument(
        "--keep-temp-dir",
        action="store_true",
        help="Keep the temporary run directory instead of deleting it.",
    )
    return parser.parse_args()


def _run(cmd: list[str], *, cwd: Path) -> str:
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


def _prepare_temp_project(temp_root: Path) -> Path:
    temp_templates = temp_root / "templates"
    ignore = shutil.ignore_patterns(
        "__pycache__",
        "*.pyc",
        ".DS_Store",
        "bo_state.json",
        "acquisition_log.jsonl",
        "event_log.jsonl",
        "observations.csv",
        "report.json",
        "report.md",
        ".looptimum.lock",
    )
    shutil.copytree(TEMPLATES_SRC, temp_templates, ignore=ignore)
    run_project = temp_templates / "bo_client_demo"

    # Ensure truly clean state in case local state artifacts were present.
    state_dir = run_project / "state"
    state_dir.mkdir(parents=True, exist_ok=True)
    for child in state_dir.iterdir():
        if child.name == ".gitkeep":
            continue
        if child.is_dir():
            shutil.rmtree(child)
        else:
            child.unlink()
    return run_project


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def _run_loop(run_project: Path, steps: int) -> dict[str, Any]:
    run_bo = run_project / "run_bo.py"
    artifacts = run_project / "state" / "tiny_loop_artifacts"
    artifacts.mkdir(parents=True, exist_ok=True)

    for idx in range(steps):
        suggest_stdout = _run(
            [
                sys.executable,
                str(run_bo),
                "suggest",
                "--project-root",
                str(run_project),
                "--json-only",
            ],
            cwd=REPO_ROOT,
        )
        suggestion = json.loads(suggest_stdout)
        trial_id = int(suggestion["trial_id"])

        suggestion_path = artifacts / f"suggestion_trial_{trial_id}.json"
        result_path = artifacts / f"result_trial_{trial_id}.json"
        _write_json(suggestion_path, suggestion)

        _run(
            [
                sys.executable,
                str(RUN_ONE_EVAL),
                str(suggestion_path),
                str(result_path),
                "--objective-module",
                str(OBJECTIVE_MODULE),
                "--objective-name",
                "loss",
            ],
            cwd=REPO_ROOT,
        )
        _run(
            [
                sys.executable,
                str(run_bo),
                "ingest",
                "--project-root",
                str(run_project),
                "--results-file",
                str(result_path),
            ],
            cwd=REPO_ROOT,
        )
        print(f"[tiny_loop] completed trial {idx + 1}/{steps} (trial_id={trial_id})")

    status_stdout = _run(
        [sys.executable, str(run_bo), "status", "--project-root", str(run_project)],
        cwd=REPO_ROOT,
    )
    return json.loads(status_stdout)


def main() -> None:
    args = _parse_args()
    if args.steps < 1:
        raise SystemExit("--steps must be >= 1")

    temp_root = Path(tempfile.mkdtemp(prefix="looptimum_tiny_quadratic_"))
    run_project = temp_root / "templates" / "bo_client_demo"

    try:
        run_project = _prepare_temp_project(temp_root)
        print(f"[tiny_loop] temp project: {run_project}")
        status_payload = _run_loop(run_project, args.steps)

        if args.write_acquisition_log:
            src = run_project / "state" / "acquisition_log.jsonl"
            dst = Path(args.write_acquisition_log).resolve()
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(src, dst)
            print(f"[tiny_loop] wrote acquisition log: {dst}")

        print("[tiny_loop] final status:")
        print(json.dumps(status_payload, indent=2))
    finally:
        if args.keep_temp_dir:
            print(f"[tiny_loop] kept temp dir: {temp_root}")
        else:
            shutil.rmtree(temp_root, ignore_errors=True)


if __name__ == "__main__":
    main()
