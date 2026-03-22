#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

from starterkit_scheduler import (
    DEFAULT_WORKER_RUN_DIRNAME,
    build_ingest_command,
    build_run_one_eval_command,
    default_worker_artifact_dir,
    lease_token_for_suggestion,
    load_suggestions_from_file,
    render_shell_command,
    select_suggestion,
    write_selected_suggestion,
)


def _require_existing_path(path: Path, *, field_name: str) -> Path:
    resolved = path.resolve()
    if not resolved.exists():
        raise ValueError(f"{field_name} not found: {resolved}")
    return resolved


def build_worker_plan(
    *,
    suggestions_file: Path,
    project_root: Path,
    work_dir: Path,
    worker_index: int | None,
    trial_id: int | None,
    run_bo_script: Path | None,
    run_one_eval_script: Path | None,
    objective_schema: Path | None,
    objective_module: Path | None,
    executor: str,
    aws_config: Path | None,
    python_executable: str | Path,
    selected_suggestion_file: Path | None,
    result_file: Path | None,
) -> dict[str, Any]:
    resolved_project_root = _require_existing_path(project_root, field_name="project root")
    resolved_suggestions = _require_existing_path(suggestions_file, field_name="suggestions file")
    resolved_run_bo = _require_existing_path(
        run_bo_script if run_bo_script is not None else resolved_project_root / "run_bo.py",
        field_name="run_bo script",
    )
    resolved_run_one_eval = _require_existing_path(
        run_one_eval_script
        if run_one_eval_script is not None
        else Path(__file__).resolve().with_name("run_one_eval.py"),
        field_name="run_one_eval script",
    )
    resolved_objective_schema = _require_existing_path(
        objective_schema
        if objective_schema is not None
        else resolved_project_root / "objective_schema.json",
        field_name="objective schema",
    )
    resolved_objective_module = (
        _require_existing_path(objective_module, field_name="objective module")
        if objective_module is not None
        else None
    )
    resolved_aws_config = (
        _require_existing_path(aws_config, field_name="aws config")
        if aws_config is not None
        else None
    )

    suggestions = load_suggestions_from_file(resolved_suggestions)
    suggestion = select_suggestion(suggestions, worker_index=worker_index, trial_id=trial_id)
    selected_trial_id = int(suggestion["trial_id"])
    lease_token = lease_token_for_suggestion(suggestion)

    artifact_dir = default_worker_artifact_dir(work_dir.resolve(), trial_id=selected_trial_id)
    selected_path = (
        selected_suggestion_file.resolve()
        if selected_suggestion_file is not None
        else artifact_dir / "suggestion.json"
    )
    result_path = result_file.resolve() if result_file is not None else artifact_dir / "result.json"

    run_one_eval_command = build_run_one_eval_command(
        suggestion_file=selected_path,
        result_file=result_path,
        objective_schema=resolved_objective_schema,
        run_one_eval_script=resolved_run_one_eval,
        python_executable=python_executable,
        objective_module=resolved_objective_module,
        executor=executor,
        aws_config=resolved_aws_config,
    )
    ingest_command = build_ingest_command(
        project_root=resolved_project_root,
        run_bo_script=resolved_run_bo,
        results_file=result_path,
        python_executable=python_executable,
        lease_token=lease_token,
    )

    return {
        "trial_id": selected_trial_id,
        "lease_token": lease_token,
        "suggestion": suggestion,
        "paths": {
            "project_root": str(resolved_project_root),
            "suggestions_file": str(resolved_suggestions),
            "selected_suggestion_file": str(selected_path),
            "result_file": str(result_path),
            "work_dir": str(work_dir.resolve()),
            "run_bo_script": str(resolved_run_bo),
            "run_one_eval_script": str(resolved_run_one_eval),
            "objective_schema": str(resolved_objective_schema),
            "objective_module": str(resolved_objective_module)
            if resolved_objective_module is not None
            else None,
            "aws_config": str(resolved_aws_config) if resolved_aws_config is not None else None,
        },
        "commands": {
            "run_one_eval": run_one_eval_command,
            "ingest": ingest_command,
        },
        "shell_commands": {
            "run_one_eval": render_shell_command(run_one_eval_command),
            "ingest": render_shell_command(ingest_command),
        },
    }


def execute_worker_plan(plan: dict[str, Any]) -> dict[str, Any]:
    selected_path = Path(str(plan["paths"]["selected_suggestion_file"]))
    result_path = Path(str(plan["paths"]["result_file"]))
    suggestion = plan["suggestion"]

    write_selected_suggestion(selected_path, suggestion)
    result_path.parent.mkdir(parents=True, exist_ok=True)
    run_one_eval_completed = subprocess.run(
        plan["commands"]["run_one_eval"],
        check=True,
        capture_output=True,
        text=True,
    )
    ingest_completed = subprocess.run(
        plan["commands"]["ingest"],
        check=True,
        capture_output=True,
        text=True,
    )

    summary: dict[str, Any] = {
        "status": "executed",
        "trial_id": int(plan["trial_id"]),
        "lease_token": plan["lease_token"],
        "selected_suggestion_file": str(selected_path),
        "result_file": str(result_path),
    }
    if run_one_eval_completed.stdout.strip():
        summary["run_one_eval_stdout"] = run_one_eval_completed.stdout.strip()
    if run_one_eval_completed.stderr.strip():
        summary["run_one_eval_stderr"] = run_one_eval_completed.stderr.strip()
    if ingest_completed.stdout.strip():
        summary["ingest_stdout"] = ingest_completed.stdout.strip()
    if ingest_completed.stderr.strip():
        summary["ingest_stderr"] = ingest_completed.stderr.strip()
    return summary


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Starter queue-worker wrapper for suggest -> run_one_eval.py -> ingest"
    )
    parser.add_argument("suggestions_file", help="Path to suggestion JSON, bundle JSON, or JSONL")
    parser.add_argument(
        "--project-root",
        required=True,
        help="Looptimum project root containing run_bo.py and objective_schema.json",
    )
    parser.add_argument(
        "--work-dir",
        default=DEFAULT_WORKER_RUN_DIRNAME,
        help="Directory for per-trial suggestion/result artifacts",
    )
    parser.add_argument("--worker-index", type=int, help="Zero-based index into a batch payload")
    parser.add_argument("--trial-id", type=int, help="Select a trial by trial_id")
    parser.add_argument(
        "--selected-suggestion-file",
        help="Optional path for the one-suggestion JSON written before evaluation",
    )
    parser.add_argument(
        "--result-file",
        help="Optional path for the ingest payload written by run_one_eval.py",
    )
    parser.add_argument("--run-bo-script", help="Override path to run_bo.py")
    parser.add_argument("--run-one-eval-script", help="Override path to run_one_eval.py")
    parser.add_argument("--objective-schema", help="Override path to objective_schema.json")
    parser.add_argument("--objective-module", help="Optional override path to objective.py")
    parser.add_argument(
        "--executor",
        choices=["local", "aws-batch"],
        default="local",
        help="Evaluation executor passed through to run_one_eval.py",
    )
    parser.add_argument("--aws-config", help="Optional AWS Batch config for --executor aws-batch")
    parser.add_argument(
        "--python-executable",
        default=sys.executable,
        help="Python interpreter used for child commands",
    )
    parser.add_argument(
        "--print-plan",
        action="store_true",
        help="Print the worker command plan as JSON instead of executing it",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    plan = build_worker_plan(
        suggestions_file=Path(args.suggestions_file),
        project_root=Path(args.project_root),
        work_dir=Path(args.work_dir),
        worker_index=args.worker_index,
        trial_id=args.trial_id,
        run_bo_script=Path(args.run_bo_script) if args.run_bo_script else None,
        run_one_eval_script=Path(args.run_one_eval_script) if args.run_one_eval_script else None,
        objective_schema=Path(args.objective_schema) if args.objective_schema else None,
        objective_module=Path(args.objective_module) if args.objective_module else None,
        executor=str(args.executor),
        aws_config=Path(args.aws_config) if args.aws_config else None,
        python_executable=str(args.python_executable),
        selected_suggestion_file=Path(args.selected_suggestion_file)
        if args.selected_suggestion_file
        else None,
        result_file=Path(args.result_file) if args.result_file else None,
    )

    if args.print_plan:
        print(json.dumps(plan, indent=2))
        return

    summary = execute_worker_plan(plan)
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
