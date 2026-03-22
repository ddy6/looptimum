from __future__ import annotations

import shlex
from pathlib import Path
from typing import Any

from starterkit_scheduler import (
    build_queue_worker_command,
    build_suggest_jsonl_command,
    render_shell_command,
)


def build_airflow_shell_commands(
    *,
    project_root: Path,
    suggestions_file: Path,
    count: int,
    work_dir: Path,
    python_executable: str | Path = "python3",
    run_bo_script: Path | None = None,
    queue_worker_script: Path | None = None,
    run_one_eval_script: Path | None = None,
    objective_schema: Path | None = None,
    objective_module: Path | None = None,
    executor: str = "local",
    aws_config: Path | None = None,
) -> dict[str, Any]:
    resolved_run_bo = run_bo_script if run_bo_script is not None else project_root / "run_bo.py"
    resolved_queue_worker = (
        queue_worker_script
        if queue_worker_script is not None
        else Path(__file__).resolve().with_name("starterkit_queue_worker.py")
    )
    resolved_run_one_eval = (
        run_one_eval_script
        if run_one_eval_script is not None
        else Path(__file__).resolve().with_name("run_one_eval.py")
    )
    resolved_objective_schema = (
        objective_schema if objective_schema is not None else project_root / "objective_schema.json"
    )

    controller_command = build_suggest_jsonl_command(
        project_root=project_root,
        run_bo_script=resolved_run_bo,
        count=count,
        python_executable=python_executable,
    )
    controller_shell = (
        f"{render_shell_command(controller_command)} > {shlex.quote(str(suggestions_file))}"
    )

    worker_shells: list[str] = []
    for worker_index in range(count):
        worker_command = build_queue_worker_command(
            suggestions_file=suggestions_file,
            project_root=project_root,
            queue_worker_script=resolved_queue_worker,
            python_executable=python_executable,
            worker_index=worker_index,
            work_dir=work_dir,
            run_bo_script=resolved_run_bo,
            run_one_eval_script=resolved_run_one_eval,
            objective_schema=resolved_objective_schema,
            objective_module=objective_module,
            executor=executor,
            aws_config=aws_config,
        )
        worker_shells.append(render_shell_command(worker_command))

    return {
        "controller_shell": controller_shell,
        "worker_shells": worker_shells,
    }


def render_airflow_dag(
    *,
    dag_id: str,
    project_root: Path,
    suggestions_file: Path,
    count: int,
    work_dir: Path,
    python_executable: str | Path = "python3",
    run_bo_script: Path | None = None,
    queue_worker_script: Path | None = None,
    run_one_eval_script: Path | None = None,
    objective_schema: Path | None = None,
    objective_module: Path | None = None,
    executor: str = "local",
    aws_config: Path | None = None,
) -> str:
    if count < 1:
        raise ValueError("count must be >= 1")

    commands = build_airflow_shell_commands(
        project_root=project_root,
        suggestions_file=suggestions_file,
        count=count,
        work_dir=work_dir,
        python_executable=python_executable,
        run_bo_script=run_bo_script,
        queue_worker_script=queue_worker_script,
        run_one_eval_script=run_one_eval_script,
        objective_schema=objective_schema,
        objective_module=objective_module,
        executor=executor,
        aws_config=aws_config,
    )

    lines = [
        "from __future__ import annotations",
        "",
        "from datetime import datetime",
        "",
        "from airflow import DAG",
        "from airflow.operators.bash import BashOperator",
        "",
        "# Single-controller pattern: only controller_suggest creates the batch.",
        "with DAG(",
        f"    dag_id={dag_id!r},",
        "    start_date=datetime(2024, 1, 1),",
        "    schedule=None,",
        "    catchup=False,",
        "    max_active_runs=1,",
        ") as dag:",
        "    controller_suggest = BashOperator(",
        '        task_id="controller_suggest",',
        f"        bash_command={commands['controller_shell']!r},",
        "        retries=0,",
        "    )",
    ]
    for worker_index, worker_shell in enumerate(commands["worker_shells"]):
        lines.extend(
            [
                "",
                f"    worker_{worker_index} = BashOperator(",
                f'        task_id="worker_{worker_index}",',
                f"        bash_command={worker_shell!r},",
                "        retries=1,",
                "    )",
                f"    controller_suggest >> worker_{worker_index}",
            ]
        )
    lines.append("")
    return "\n".join(lines)
