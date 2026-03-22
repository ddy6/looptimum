from __future__ import annotations

import json
import shlex
import sys
from pathlib import Path
from typing import Any, Sequence

DEFAULT_WORKER_RUN_DIRNAME = "starterkit_worker_runs"


def _require_suggestion_shape(payload: Any, *, field_name: str) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise ValueError(f"{field_name} must be a JSON object")
    if "trial_id" not in payload:
        raise ValueError(f"{field_name} missing trial_id")
    if "params" not in payload:
        raise ValueError(f"{field_name} missing params")
    trial_id = payload["trial_id"]
    if not isinstance(trial_id, int) or isinstance(trial_id, bool) or trial_id < 1:
        raise ValueError(f"{field_name}.trial_id must be an integer >= 1")
    if not isinstance(payload["params"], dict):
        raise ValueError(f"{field_name}.params must be an object")
    return dict(payload)


def _normalize_suggestion_collection(payload: dict[str, Any]) -> list[dict[str, Any]]:
    suggestions = payload.get("suggestions")
    if suggestions is None:
        return [_require_suggestion_shape(payload, field_name="suggestion")]
    if not isinstance(suggestions, list) or not suggestions:
        raise ValueError("suggestion bundle must contain a non-empty suggestions list")
    return [
        _require_suggestion_shape(item, field_name=f"suggestions[{index}]")
        for index, item in enumerate(suggestions)
    ]


def load_suggestions_from_file(path: Path) -> list[dict[str, Any]]:
    text = path.read_text(encoding="utf-8")

    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        payload = None
    if isinstance(payload, dict):
        return _normalize_suggestion_collection(payload)

    lines = [line for line in text.splitlines() if line.strip()]
    if not lines:
        raise ValueError(f"No suggestion payloads found in {path}")

    jsonl_payloads: list[dict[str, Any]] = []
    jsonl_valid = True
    for index, line in enumerate(lines, start=1):
        try:
            entry = json.loads(line)
        except json.JSONDecodeError:
            jsonl_valid = False
            break
        jsonl_payloads.append(
            _require_suggestion_shape(entry, field_name=f"jsonl suggestion line {index}")
        )
    if jsonl_valid:
        return jsonl_payloads

    for end in range(len(lines), 0, -1):
        try:
            payload = json.loads("\n".join(lines[:end]))
        except json.JSONDecodeError:
            continue
        if isinstance(payload, dict):
            return _normalize_suggestion_collection(payload)
    raise ValueError(f"Could not parse suggestion payloads from {path}")


def select_suggestion(
    suggestions: Sequence[dict[str, Any]],
    *,
    worker_index: int | None = None,
    trial_id: int | None = None,
) -> dict[str, Any]:
    if worker_index is not None and trial_id is not None:
        raise ValueError("worker_index and trial_id are mutually exclusive")

    if trial_id is not None:
        for suggestion in suggestions:
            if int(suggestion["trial_id"]) == int(trial_id):
                return dict(suggestion)
        raise ValueError(f"trial_id {trial_id} not found in suggestion collection")

    if worker_index is not None:
        if worker_index < 0 or worker_index >= len(suggestions):
            raise ValueError(
                f"worker_index {worker_index} out of range for {len(suggestions)} suggestion(s)"
            )
        return dict(suggestions[worker_index])

    if len(suggestions) != 1:
        raise ValueError(
            "suggestion collection contains multiple entries; provide worker_index or trial_id"
        )
    return dict(suggestions[0])


def lease_token_for_suggestion(suggestion: dict[str, Any]) -> str | None:
    raw = suggestion.get("lease_token")
    if raw is None:
        return None
    if not isinstance(raw, str) or not raw.strip():
        raise ValueError("lease_token must be a non-empty string when present")
    return raw.strip()


def render_shell_command(command: Sequence[str]) -> str:
    return shlex.join([str(part) for part in command])


def default_worker_artifact_dir(base_dir: Path, *, trial_id: int) -> Path:
    if trial_id < 1:
        raise ValueError("trial_id must be >= 1")
    return base_dir / f"trial_{int(trial_id)}"


def write_selected_suggestion(path: Path, suggestion: dict[str, Any]) -> Path:
    normalized = _require_suggestion_shape(suggestion, field_name="selected suggestion")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(normalized, indent=2) + "\n", encoding="utf-8")
    return path


def build_suggest_jsonl_command(
    *,
    project_root: Path,
    run_bo_script: Path,
    count: int,
    python_executable: str | Path = sys.executable,
    fail_fast: bool = True,
) -> list[str]:
    if count < 1:
        raise ValueError("count must be >= 1")
    command = [
        str(python_executable),
        str(run_bo_script),
        "suggest",
        "--project-root",
        str(project_root),
        "--count",
        str(int(count)),
        "--jsonl",
    ]
    if fail_fast:
        command.append("--fail-fast")
    return command


def build_run_one_eval_command(
    *,
    suggestion_file: Path,
    result_file: Path,
    objective_schema: Path,
    run_one_eval_script: Path,
    python_executable: str | Path = sys.executable,
    objective_module: Path | None = None,
    executor: str = "local",
    aws_config: Path | None = None,
) -> list[str]:
    command = [
        str(python_executable),
        str(run_one_eval_script),
        str(suggestion_file),
        str(result_file),
        "--objective-schema",
        str(objective_schema),
        "--executor",
        executor,
    ]
    if objective_module is not None:
        command.extend(["--objective-module", str(objective_module)])
    if aws_config is not None:
        command.extend(["--aws-config", str(aws_config)])
    return command


def build_ingest_command(
    *,
    project_root: Path,
    run_bo_script: Path,
    results_file: Path,
    python_executable: str | Path = sys.executable,
    lease_token: str | None = None,
    fail_fast: bool = True,
) -> list[str]:
    command = [
        str(python_executable),
        str(run_bo_script),
        "ingest",
        "--project-root",
        str(project_root),
        "--results-file",
        str(results_file),
    ]
    if lease_token is not None:
        command.extend(["--lease-token", lease_token])
    if fail_fast:
        command.append("--fail-fast")
    return command


def build_queue_worker_command(
    *,
    suggestions_file: Path,
    project_root: Path,
    queue_worker_script: Path,
    python_executable: str | Path = sys.executable,
    worker_index: int | None = None,
    trial_id: int | None = None,
    work_dir: Path | None = None,
    run_bo_script: Path | None = None,
    run_one_eval_script: Path | None = None,
    objective_schema: Path | None = None,
    objective_module: Path | None = None,
    executor: str = "local",
    aws_config: Path | None = None,
    print_plan: bool = False,
) -> list[str]:
    command = [
        str(python_executable),
        str(queue_worker_script),
        str(suggestions_file),
        "--project-root",
        str(project_root),
    ]
    if worker_index is not None:
        command.extend(["--worker-index", str(int(worker_index))])
    if trial_id is not None:
        command.extend(["--trial-id", str(int(trial_id))])
    if work_dir is not None:
        command.extend(["--work-dir", str(work_dir)])
    if run_bo_script is not None:
        command.extend(["--run-bo-script", str(run_bo_script)])
    if run_one_eval_script is not None:
        command.extend(["--run-one-eval-script", str(run_one_eval_script)])
    if objective_schema is not None:
        command.extend(["--objective-schema", str(objective_schema)])
    if objective_module is not None:
        command.extend(["--objective-module", str(objective_module)])
    if executor != "local":
        command.extend(["--executor", executor])
    if aws_config is not None:
        command.extend(["--aws-config", str(aws_config)])
    if print_plan:
        command.append("--print-plan")
    return command


def build_slurm_array_submit_command(*, script_path: Path, count: int) -> list[str]:
    if count < 1:
        raise ValueError("count must be >= 1")
    return ["sbatch", "--array", f"0-{int(count) - 1}", str(script_path)]
