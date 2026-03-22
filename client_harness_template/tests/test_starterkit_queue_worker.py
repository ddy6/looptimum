from __future__ import annotations

import importlib
import json
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
HARNESS_DIR = REPO_ROOT / "client_harness_template"
if str(HARNESS_DIR) not in sys.path:
    sys.path.insert(0, str(HARNESS_DIR))

starterkit_queue_worker = importlib.import_module("starterkit_queue_worker")


def _write_fake_project_root(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    (path / "objective_schema.json").write_text(
        json.dumps(
            {
                "primary_objective": {"name": "loss", "direction": "minimize"},
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    (path / "objective.py").write_text(
        "def evaluate(params):\n    return float(params['x']) + 1.0\n",
        encoding="utf-8",
    )
    (path / "run_bo.py").write_text(
        "from __future__ import annotations\n"
        "import argparse\n"
        "import json\n"
        "from pathlib import Path\n"
        "\n"
        "def main() -> None:\n"
        "    parser = argparse.ArgumentParser()\n"
        "    parser.add_argument('command')\n"
        "    parser.add_argument('--project-root', default='.')\n"
        "    parser.add_argument('--results-file', required=True)\n"
        "    parser.add_argument('--lease-token', default=None)\n"
        "    parser.add_argument('--fail-fast', action='store_true')\n"
        "    args = parser.parse_args()\n"
        "    result = json.loads(Path(args.results_file).read_text(encoding='utf-8'))\n"
        "    payload = {\n"
        "        'command': args.command,\n"
        "        'lease_token': args.lease_token,\n"
        "        'result': result,\n"
        "    }\n"
        "    target = Path(args.project_root) / 'ingest_record.json'\n"
        "    target.write_text(json.dumps(payload, indent=2) + '\\n', encoding='utf-8')\n"
        "    print(json.dumps({'status': 'ok', 'trial_id': result['trial_id']}))\n"
        "\n"
        "if __name__ == '__main__':\n"
        "    main()\n",
        encoding="utf-8",
    )


def test_build_worker_plan_includes_selected_trial_and_lease_token(tmp_path: Path) -> None:
    project_root = tmp_path / "campaign"
    _write_fake_project_root(project_root)
    suggestions_path = tmp_path / "suggestions.jsonl"
    suggestions_path.write_text(
        json.dumps({"trial_id": 1, "params": {"x": 0.1}})
        + "\n"
        + json.dumps({"trial_id": 2, "params": {"x": 0.5}, "lease_token": "lease-2"})
        + "\n",
        encoding="utf-8",
    )

    plan = starterkit_queue_worker.build_worker_plan(
        suggestions_file=suggestions_path,
        project_root=project_root,
        work_dir=tmp_path / "worker_runs",
        worker_index=1,
        trial_id=None,
        run_bo_script=project_root / "run_bo.py",
        run_one_eval_script=HARNESS_DIR / "run_one_eval.py",
        objective_schema=project_root / "objective_schema.json",
        objective_module=project_root / "objective.py",
        executor="local",
        aws_config=None,
        python_executable=sys.executable,
        selected_suggestion_file=None,
        result_file=None,
    )

    assert plan["trial_id"] == 2
    assert plan["lease_token"] == "lease-2"
    assert plan["suggestion"]["trial_id"] == 2
    assert "--lease-token" in plan["commands"]["ingest"]


def test_queue_worker_executes_run_one_eval_and_ingest(tmp_path: Path) -> None:
    project_root = tmp_path / "campaign"
    _write_fake_project_root(project_root)
    suggestions_path = tmp_path / "suggestions.json"
    suggestions_path.write_text(
        json.dumps(
            {
                "count": 2,
                "suggestions": [
                    {"trial_id": 1, "params": {"x": 0.25}},
                    {"trial_id": 2, "params": {"x": 0.5}, "lease_token": "lease-2"},
                ],
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    work_dir = tmp_path / "worker_runs"

    completed = subprocess.run(
        [
            sys.executable,
            str(HARNESS_DIR / "starterkit_queue_worker.py"),
            str(suggestions_path),
            "--project-root",
            str(project_root),
            "--worker-index",
            "1",
            "--work-dir",
            str(work_dir),
            "--run-bo-script",
            str(project_root / "run_bo.py"),
            "--run-one-eval-script",
            str(HARNESS_DIR / "run_one_eval.py"),
            "--objective-schema",
            str(project_root / "objective_schema.json"),
            "--objective-module",
            str(project_root / "objective.py"),
        ],
        check=True,
        capture_output=True,
        text=True,
    )

    summary = json.loads(completed.stdout)
    suggestion_payload = json.loads(
        (work_dir / "trial_2" / "suggestion.json").read_text(encoding="utf-8")
    )
    result_payload = json.loads((work_dir / "trial_2" / "result.json").read_text(encoding="utf-8"))
    ingest_record = json.loads((project_root / "ingest_record.json").read_text(encoding="utf-8"))

    assert summary["status"] == "executed"
    assert summary["trial_id"] == 2
    assert summary["lease_token"] == "lease-2"
    assert suggestion_payload["trial_id"] == 2
    assert result_payload["objectives"] == {"loss": 1.5}
    assert ingest_record["lease_token"] == "lease-2"
    assert ingest_record["result"]["trial_id"] == 2
