from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
COPY = REPO / "templates/_shared/vendor_copy.py"


def _source(tmp_path: Path) -> Path:
    source = tmp_path / "source"
    shutil.copytree(REPO / "templates/bo_client", source)
    cfg = json.loads((source / "bo_config.json").read_text())
    paths = {
        "state_file": "custom/live.json",
        "observations_csv": "custom/observed.csv",
        "event_log_file": "logs/events.jsonl",
        "acquisition_log_file": "logs/acquisition.jsonl",
        "trials_dir": "records/trials",
        "optimizer_dir": "private_optimizer",
        "import_reports_dir": "imports",
        "report_json_file": "reports/current.json",
        "report_md_file": "reports/current.md",
        "lock_file": "locks/active.lock",
    }
    cfg["paths"].update(paths)
    (source / "bo_config.json").write_text(json.dumps(cfg))
    for key, value in paths.items():
        path = source / value
        if key.endswith("_dir"):
            path = path / "history.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text('{"history_marker": true}')
    archive = source / "custom/reset_archives/old/history.json"
    archive.parent.mkdir(parents=True)
    archive.write_text('{"history_marker": true}')
    # Evaluator artifacts may contain Python source; they are still history.
    (source / "records/trials/evaluator.py").write_text('# "history_marker": true\n')
    return source


def test_fresh_copy_omits_all_configured_histories_and_runs_elsewhere(tmp_path: Path) -> None:
    source = _source(tmp_path)
    destination = tmp_path / "copy"
    copied = subprocess.run(
        [sys.executable, str(COPY), str(source), str(destination)], capture_output=True, text=True
    )
    assert copied.returncode == 0, copied.stderr
    for path in destination.rglob("*"):
        if path.is_file():
            assert b'"history_marker": true' not in path.read_bytes(), path
    source.rename(tmp_path / "source-unavailable")
    result = subprocess.run(
        [
            sys.executable,
            "-S",
            str(destination / "run_bo.py"),
            "--project-root",
            str(destination),
            "suggest",
            "--json-only",
        ],
        cwd=tmp_path,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["trial_id"] == 1
    state = json.loads((destination / "custom/live.json").read_text())
    assert state["observations"] == [] and len(state["pending"]) == 1


@pytest.mark.parametrize(
    "kind", ["absolute", "outside", "root", "source", "source-child", "symlink"]
)
def test_unsafe_fresh_copy_paths_fail_before_destination_changes(tmp_path: Path, kind: str) -> None:
    source = _source(tmp_path)
    cfg_path = source / "bo_config.json"
    cfg = json.loads(cfg_path.read_text())
    if kind == "symlink":
        (source / "history_alias").symlink_to(source / "custom", target_is_directory=True)
    else:
        cfg["paths"]["state_file"] = {
            "absolute": str(source / "custom/live.json"),
            "outside": "../outside.json",
            "root": ".",
            "source": "run_bo.py",
            "source-child": "run_bo.py/state.json",
        }[kind]
    cfg_path.write_text(json.dumps(cfg))
    destination = tmp_path / "copy"
    result = subprocess.run(
        [sys.executable, str(COPY), str(source), str(destination)], capture_output=True, text=True
    )
    assert result.returncode != 0
    assert not destination.exists()
