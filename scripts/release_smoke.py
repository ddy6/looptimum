#!/usr/bin/env python3
"""Release smoke checks for quickstart workflows across template variants."""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
TEMPLATES_SRC = REPO_ROOT / "templates"
TINY_LOOP_SCRIPT = (
    REPO_ROOT / "examples" / "toy_objectives" / "03_tiny_quadratic_loop" / "run_tiny_loop.py"
)

VARIANTS = ["bo_client_demo", "bo_client", "bo_client_full"]


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Run release smoke checks for quickstart commands across template variants "
            "in temporary copies."
        )
    )
    parser.add_argument(
        "--demo-steps",
        type=int,
        default=3,
        help="Number of steps for per-variant demo smoke (default: 3).",
    )
    parser.add_argument(
        "--tiny-loop-steps",
        type=int,
        default=4,
        help="Number of steps for tiny objective smoke (default: 4).",
    )
    parser.add_argument(
        "--keep-temp-dir",
        action="store_true",
        help="Keep the temporary workspace for debugging.",
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


def _prepare_temp_templates(temp_root: Path) -> Path:
    temp_templates = temp_root / "templates"
    ignore = shutil.ignore_patterns(
        "__pycache__",
        "*.pyc",
        ".DS_Store",
        ".looptimum.lock",
        "bo_state.json",
        "observations.csv",
        "acquisition_log.jsonl",
        "event_log.jsonl",
        "report.json",
        "report.md",
    )
    shutil.copytree(TEMPLATES_SRC, temp_templates, ignore=ignore)
    return temp_templates


def _clean_state(project_root: Path) -> None:
    state_dir = project_root / "state"
    state_dir.mkdir(parents=True, exist_ok=True)
    for child in state_dir.iterdir():
        if child.name == ".gitkeep":
            continue
        if child.is_dir():
            shutil.rmtree(child)
        else:
            child.unlink()


def _require_keys(payload: dict[str, Any], keys: list[str], *, context: str) -> None:
    for key in keys:
        if key not in payload:
            raise RuntimeError(f"Missing key '{key}' in {context}: {payload}")


def _status_payload(raw: str, *, context: str) -> dict[str, Any]:
    payload = json.loads(raw)
    _require_keys(
        payload,
        ["observations", "pending", "next_trial_id", "best", "stale_pending", "paths"],
        context=context,
    )
    return payload


def _smoke_core_flow(project_root: Path, *, demo_steps: int, include_botorch_flag: bool) -> None:
    run_bo = project_root / "run_bo.py"

    _clean_state(project_root)
    _status_payload(
        _run(
            [sys.executable, str(run_bo), "status", "--project-root", str(project_root)],
            cwd=REPO_ROOT,
        ),
        context=f"{project_root.name} initial status",
    )
    _run(
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
    _run(
        [
            sys.executable,
            str(run_bo),
            "ingest",
            "--project-root",
            str(project_root),
            "--results-file",
            str(project_root / "examples" / "example_results.json"),
        ],
        cwd=REPO_ROOT,
    )
    status_after_ingest = _status_payload(
        _run(
            [sys.executable, str(run_bo), "status", "--project-root", str(project_root)],
            cwd=REPO_ROOT,
        ),
        context=f"{project_root.name} status after ingest",
    )
    if int(status_after_ingest["observations"]) < 1:
        raise RuntimeError(f"{project_root.name}: expected at least one observation after ingest")

    _clean_state(project_root)
    _run(
        [
            sys.executable,
            str(run_bo),
            "demo",
            "--project-root",
            str(project_root),
            "--steps",
            str(demo_steps),
        ],
        cwd=REPO_ROOT,
    )
    status_after_demo = _status_payload(
        _run(
            [sys.executable, str(run_bo), "status", "--project-root", str(project_root)],
            cwd=REPO_ROOT,
        ),
        context=f"{project_root.name} status after demo",
    )
    if int(status_after_demo["observations"]) < demo_steps:
        raise RuntimeError(
            f"{project_root.name}: expected at least {demo_steps} observations after demo,"
            f" got {status_after_demo['observations']}"
        )

    if include_botorch_flag:
        _clean_state(project_root)
        _run(
            [
                sys.executable,
                str(run_bo),
                "suggest",
                "--project-root",
                str(project_root),
                "--enable-botorch-gp",
            ],
            cwd=REPO_ROOT,
        )


def _smoke_ops_flow(project_root: Path) -> None:
    run_bo = project_root / "run_bo.py"
    state_dir = project_root / "state"
    _clean_state(project_root)

    suggestion_1 = json.loads(
        _run(
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
    )
    trial_1 = int(suggestion_1["trial_id"])
    _run(
        [
            sys.executable,
            str(run_bo),
            "heartbeat",
            "--project-root",
            str(project_root),
            "--trial-id",
            str(trial_1),
            "--heartbeat-note",
            "release smoke heartbeat",
        ],
        cwd=REPO_ROOT,
    )
    _run(
        [
            sys.executable,
            str(run_bo),
            "cancel",
            "--project-root",
            str(project_root),
            "--trial-id",
            str(trial_1),
        ],
        cwd=REPO_ROOT,
    )

    suggestion_2 = json.loads(
        _run(
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
    )
    trial_2 = int(suggestion_2["trial_id"])
    _run(
        [
            sys.executable,
            str(run_bo),
            "retire",
            "--project-root",
            str(project_root),
            "--trial-id",
            str(trial_2),
        ],
        cwd=REPO_ROOT,
    )

    _run(
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
    _run(
        [
            sys.executable,
            str(run_bo),
            "retire",
            "--project-root",
            str(project_root),
            "--stale",
        ],
        cwd=REPO_ROOT,
    )
    _run(
        [
            sys.executable,
            str(run_bo),
            "report",
            "--project-root",
            str(project_root),
            "--top-n",
            "5",
        ],
        cwd=REPO_ROOT,
    )
    _run(
        [sys.executable, str(run_bo), "validate", "--project-root", str(project_root)],
        cwd=REPO_ROOT,
    )
    doctor_payload = json.loads(
        _run(
            [
                sys.executable,
                str(run_bo),
                "doctor",
                "--project-root",
                str(project_root),
                "--json",
            ],
            cwd=REPO_ROOT,
        )
    )
    _require_keys(
        doctor_payload,
        ["generated_at", "python_version", "platform", "project_root", "status"],
        context=f"{project_root.name} doctor",
    )

    if not (state_dir / "report.json").exists():
        raise RuntimeError(f"{project_root.name}: missing report.json after report command")
    if not (state_dir / "report.md").exists():
        raise RuntimeError(f"{project_root.name}: missing report.md after report command")


def _smoke_variant(variant_name: str, project_root: Path, *, demo_steps: int) -> None:
    include_botorch_flag = variant_name == "bo_client_full"
    print(f"[smoke] core flow: {variant_name}")
    _smoke_core_flow(
        project_root,
        demo_steps=demo_steps,
        include_botorch_flag=include_botorch_flag,
    )
    print(f"[smoke] ops flow: {variant_name}")
    _smoke_ops_flow(project_root)
    print(f"[smoke] variant passed: {variant_name}")


def _smoke_tiny_loop(tiny_steps: int) -> None:
    print("[smoke] tiny loop")
    _run(
        [sys.executable, str(TINY_LOOP_SCRIPT), "--steps", str(tiny_steps)],
        cwd=REPO_ROOT,
    )
    print("[smoke] tiny loop passed")


def main() -> None:
    args = _parse_args()
    if args.demo_steps < 1:
        raise SystemExit("--demo-steps must be >= 1")
    if args.tiny_loop_steps < 1:
        raise SystemExit("--tiny-loop-steps must be >= 1")

    temp_root = Path(tempfile.mkdtemp(prefix="looptimum_release_smoke_"))
    print(f"[smoke] temp root: {temp_root}")

    try:
        temp_templates = _prepare_temp_templates(temp_root)
        for variant_name in VARIANTS:
            _smoke_variant(
                variant_name,
                temp_templates / variant_name,
                demo_steps=args.demo_steps,
            )
        _smoke_tiny_loop(args.tiny_loop_steps)
    finally:
        if args.keep_temp_dir:
            print(f"[smoke] kept temp root: {temp_root}")
        else:
            shutil.rmtree(temp_root, ignore_errors=True)

    print("[smoke] all release smoke checks passed")


if __name__ == "__main__":
    main()
