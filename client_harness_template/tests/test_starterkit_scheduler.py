from __future__ import annotations

import importlib
import json
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
HARNESS_DIR = REPO_ROOT / "client_harness_template"
if str(HARNESS_DIR) not in sys.path:
    sys.path.insert(0, str(HARNESS_DIR))

starterkit_airflow = importlib.import_module("starterkit_airflow")
starterkit_scheduler = importlib.import_module("starterkit_scheduler")
starterkit_slurm = importlib.import_module("starterkit_slurm")


def test_load_suggestions_from_bundle_json(tmp_path: Path) -> None:
    path = tmp_path / "suggestions.json"
    path.write_text(
        json.dumps(
            {
                "count": 2,
                "suggestions": [
                    {"trial_id": 1, "params": {"x": 0.1}},
                    {"trial_id": 2, "params": {"x": 0.2}, "lease_token": "lease-2"},
                ],
            },
            indent=2,
        ),
        encoding="utf-8",
    )

    suggestions = starterkit_scheduler.load_suggestions_from_file(path)

    assert [item["trial_id"] for item in suggestions] == [1, 2]
    assert starterkit_scheduler.lease_token_for_suggestion(suggestions[1]) == "lease-2"


def test_load_suggestions_from_raw_suggest_stdout(tmp_path: Path) -> None:
    path = tmp_path / "suggest_stdout.txt"
    path.write_text(
        json.dumps({"trial_id": 7, "params": {"x": 0.7}}, indent=2)
        + "\nObjective direction: minimize (loss)\n",
        encoding="utf-8",
    )

    suggestions = starterkit_scheduler.load_suggestions_from_file(path)

    assert suggestions == [{"trial_id": 7, "params": {"x": 0.7}}]


def test_select_suggestion_requires_disambiguation_for_multi_entry_payload() -> None:
    suggestions = [
        {"trial_id": 1, "params": {"x": 0.1}},
        {"trial_id": 2, "params": {"x": 0.2}},
    ]

    with pytest.raises(ValueError, match="provide worker_index or trial_id"):
        starterkit_scheduler.select_suggestion(suggestions)


def test_scheduler_command_builders_include_batch_and_lease_flags() -> None:
    project_root = Path("/tmp/campaign")
    run_bo_script = project_root / "run_bo.py"
    queue_worker_script = HARNESS_DIR / "starterkit_queue_worker.py"
    run_one_eval_script = HARNESS_DIR / "run_one_eval.py"
    objective_schema = project_root / "objective_schema.json"

    suggest_command = starterkit_scheduler.build_suggest_jsonl_command(
        project_root=project_root,
        run_bo_script=run_bo_script,
        count=3,
        python_executable="python3",
    )
    worker_command = starterkit_scheduler.build_queue_worker_command(
        suggestions_file=project_root / "suggestions.jsonl",
        project_root=project_root,
        queue_worker_script=queue_worker_script,
        python_executable="python3",
        worker_index=1,
        work_dir=project_root / "worker_runs",
        run_bo_script=run_bo_script,
        run_one_eval_script=run_one_eval_script,
        objective_schema=objective_schema,
        print_plan=True,
    )
    ingest_command = starterkit_scheduler.build_ingest_command(
        project_root=project_root,
        run_bo_script=run_bo_script,
        results_file=project_root / "result.json",
        python_executable="python3",
        lease_token="lease-1",
    )

    assert suggest_command[-2:] == ["--jsonl", "--fail-fast"]
    assert "--worker-index" in worker_command
    assert "--objective-schema" in worker_command
    assert "--print-plan" in worker_command
    assert "--lease-token" in ingest_command


def test_render_airflow_dag_preserves_single_controller_pattern() -> None:
    dag_text = starterkit_airflow.render_airflow_dag(
        dag_id="looptimum_batch",
        project_root=Path("/campaign"),
        suggestions_file=Path("/campaign/state/suggestions.jsonl"),
        count=2,
        work_dir=Path("/campaign/state/worker_runs"),
        python_executable="python3",
    )

    assert "schedule=None" in dag_text
    assert "catchup=False" in dag_text
    assert "max_active_runs=1" in dag_text
    assert "controller_suggest" in dag_text
    assert "starterkit_queue_worker.py" in dag_text
    assert "--worker-index 0" in dag_text
    assert "--worker-index 1" in dag_text


def test_render_slurm_array_script_includes_array_worker_index() -> None:
    script_text = starterkit_slurm.render_slurm_array_script(
        project_root=Path("/campaign"),
        suggestions_file=Path("/campaign/state/suggestions.jsonl"),
        count=4,
        work_dir=Path("/campaign/state/worker_runs"),
        python_executable="python3",
    )

    assert "#!/usr/bin/env bash" in script_text
    assert "SLURM_ARRAY_TASK_ID" in script_text
    assert "starterkit_queue_worker.py" in script_text
    assert '--worker-index "${SLURM_ARRAY_TASK_ID}"' in script_text
