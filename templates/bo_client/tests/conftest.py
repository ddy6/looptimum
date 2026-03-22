from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest


def run_cmd(
    project_root: Path,
    *args: str,
    expect_ok: bool = True,
    env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    cmd = [sys.executable, "run_bo.py", *args]
    run_env = dict(os.environ)
    if env:
        run_env.update(env)
    out = subprocess.run(cmd, cwd=project_root, capture_output=True, text=True, env=run_env)
    if expect_ok and out.returncode != 0:
        raise AssertionError(
            f"Command failed: {' '.join(cmd)}\nSTDOUT:\n{out.stdout}\nSTDERR:\n{out.stderr}"
        )
    return out


def parse_json_output(stdout: str) -> object:
    text = stdout.strip()
    if not text:
        raise AssertionError("Expected non-empty stdout payload.")
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        lines = [line for line in text.splitlines() if line.strip()]
        if len(lines) < 2:
            raise
        return json.loads("\n".join(lines[:-1]))


def parse_suggestion(stdout: str) -> dict:
    payload = parse_json_output(stdout)
    assert isinstance(payload, dict)
    assert "trial_id" in payload
    return payload


def parse_suggestion_bundle(stdout: str) -> dict:
    payload = parse_json_output(stdout)
    assert isinstance(payload, dict)
    assert "suggestions" in payload
    return payload


def parse_jsonl_suggestions(stdout: str) -> list[dict]:
    lines = [line for line in stdout.splitlines() if line.strip()]
    return [json.loads(line) for line in lines]


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
