from __future__ import annotations

import json
import shutil
import subprocess
import sys
import time
from pathlib import Path

import pytest


def run_cmd(
    project_root: Path, *args: str, expect_ok: bool = True
) -> subprocess.CompletedProcess[str]:
    cmd = [sys.executable, "run_bo.py", *args]
    out = subprocess.run(cmd, cwd=project_root, capture_output=True, text=True)
    if expect_ok and out.returncode != 0:
        raise AssertionError(
            f"Command failed: {' '.join(cmd)}\nSTDOUT:\n{out.stdout}\nSTDERR:\n{out.stderr}"
        )
    return out


@pytest.fixture
def template_copy(tmp_path: Path) -> Path:
    src = Path(__file__).resolve().parents[1]
    dst = tmp_path / "template"
    subprocess.run(["cp", "-R", str(src), str(dst)], check=True)
    shared_src = src.parent / "_shared"
    if shared_src.exists():
        subprocess.run(["cp", "-R", str(shared_src), str(tmp_path / "_shared")], check=True)
    for p in [
        dst / "state" / "bo_state.json",
        dst / "state" / "observations.csv",
        dst / "state" / "acquisition_log.jsonl",
        dst / "state" / "event_log.jsonl",
        dst / "state" / ".looptimum.lock",
        dst / "state" / "report.json",
        dst / "state" / "report.md",
        dst / "examples" / "_demo_result.json",
    ]:
        if p.exists():
            p.unlink()
    trials_dir = dst / "state" / "trials"
    if trials_dir.exists():
        shutil.rmtree(trials_dir)
    return dst


def _read_state(template_copy: Path) -> dict:
    return json.loads((template_copy / "state" / "bo_state.json").read_text(encoding="utf-8"))


def _read_manifest(template_copy: Path, trial_id: int) -> dict:
    path = template_copy / "state" / "trials" / f"trial_{trial_id}" / "manifest.json"
    return json.loads(path.read_text(encoding="utf-8"))


def _parse_suggestion(stdout: str) -> dict:
    lines = [line for line in stdout.strip().splitlines() if line.strip()]
    return json.loads("\n".join(lines[:-1]))


def _read_events(template_copy: Path) -> list[dict]:
    path = template_copy / "state" / "event_log.jsonl"
    lines = [line.strip() for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    return [json.loads(line) for line in lines]


def test_cancel_moves_pending_to_killed_observation_and_manifest(template_copy: Path) -> None:
    suggestion = _parse_suggestion(run_cmd(template_copy, "suggest").stdout)
    out = run_cmd(template_copy, "cancel", "--trial-id", str(suggestion["trial_id"]))
    assert "Canceled trial_id=1" in out.stdout

    state = _read_state(template_copy)
    assert len(state["pending"]) == 0
    assert len(state["observations"]) == 1
    obs = state["observations"][0]
    assert obs["status"] == "killed"
    assert obs["terminal_reason"] == "canceled"

    manifest = _read_manifest(template_copy, suggestion["trial_id"])
    assert manifest["status"] == "killed"
    assert manifest["terminal_reason"] == "canceled"

    events = _read_events(template_copy)
    assert any(e["event"] == "trial_canceled" for e in events)


def test_heartbeat_updates_pending_and_manifest(template_copy: Path) -> None:
    suggestion = _parse_suggestion(run_cmd(template_copy, "suggest").stdout)
    run_cmd(
        template_copy,
        "heartbeat",
        "--trial-id",
        str(suggestion["trial_id"]),
        "--heartbeat-note",
        "running",
        "--heartbeat-meta-json",
        '{"worker":"full-node"}',
    )

    state = _read_state(template_copy)
    pending = state["pending"][0]
    assert pending["heartbeat_count"] == 1
    assert pending["heartbeat_note"] == "running"
    assert pending["heartbeat_meta"] == {"worker": "full-node"}
    assert isinstance(pending["last_heartbeat_at"], float)

    manifest = _read_manifest(template_copy, suggestion["trial_id"])
    assert manifest["heartbeat_count"] == 1
    assert manifest["heartbeat_note"] == "running"
    assert manifest["heartbeat_meta"] == {"worker": "full-node"}


def test_retire_stale_command_retires_pending_trial(template_copy: Path) -> None:
    suggestion = _parse_suggestion(run_cmd(template_copy, "suggest").stdout)
    state_path = template_copy / "state" / "bo_state.json"
    state = json.loads(state_path.read_text(encoding="utf-8"))
    state["pending"][0]["suggested_at"] = time.time() - 3600
    state_path.write_text(json.dumps(state, indent=2), encoding="utf-8")

    out = run_cmd(template_copy, "retire", "--stale", "--max-age-seconds", "60")
    assert "Retired 1 pending trial(s)" in out.stdout

    state_after = _read_state(template_copy)
    assert len(state_after["pending"]) == 0
    assert len(state_after["observations"]) == 1
    obs = state_after["observations"][0]
    assert obs["trial_id"] == suggestion["trial_id"]
    assert obs["status"] == "killed"
    assert obs["terminal_reason"] == "retired_stale"


def test_status_adds_phase5_fields_compatibly(template_copy: Path) -> None:
    payload = json.loads(run_cmd(template_copy, "status").stdout)
    for key in ("observations", "pending", "next_trial_id", "best"):
        assert key in payload
    for key in ("stale_pending", "observations_by_status", "paths"):
        assert key in payload
    assert "event_log_file" in payload["paths"]
    assert "trials_dir" in payload["paths"]
    assert "botorch_feature_flag" in payload
