from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest


def run_cmd(project_root: Path, *args: str, expect_ok: bool = True) -> subprocess.CompletedProcess[str]:
    cmd = [sys.executable, "run_bo.py", *args]
    out = subprocess.run(cmd, cwd=project_root, capture_output=True, text=True)
    if expect_ok and out.returncode != 0:
        raise AssertionError(f"Command failed: {' '.join(cmd)}\nSTDOUT:\n{out.stdout}\nSTDERR:\n{out.stderr}")
    return out


@pytest.fixture
def template_copy(tmp_path: Path) -> Path:
    src = Path(__file__).resolve().parents[1]
    dst = tmp_path / "template"
    subprocess.run(["cp", "-R", str(src), str(dst)], check=True)
    for p in [
        dst / "state" / "bo_state.json",
        dst / "state" / "observations.csv",
        dst / "state" / "acquisition_log.jsonl",
        dst / "examples" / "_demo_result.json",
    ]:
        if p.exists():
            p.unlink()
    return dst


def test_status_initial(template_copy: Path) -> None:
    out = run_cmd(template_copy, "status")
    payload = json.loads(out.stdout)
    assert payload["observations"] == 0
    assert payload["pending"] == 0
    assert payload["next_trial_id"] == 1
    assert payload["best"] is None


def test_suggest_then_ingest(template_copy: Path) -> None:
    s = run_cmd(template_copy, "suggest")
    lines = [line for line in s.stdout.strip().splitlines() if line.strip()]
    suggestion = json.loads("\n".join(lines[:-1]))
    assert suggestion["trial_id"] == 1
    assert set(suggestion["params"].keys()) == {"x1", "x2"}

    result = {
        "trial_id": suggestion["trial_id"],
        "params": suggestion["params"],
        "objectives": {"loss": 0.05},
        "status": "ok",
    }
    result_path = template_copy / "examples" / "_test_result.json"
    result_path.write_text(json.dumps(result, indent=2), encoding="utf-8")

    run_cmd(template_copy, "ingest", "--results-file", str(result_path))
    st = run_cmd(template_copy, "status")
    payload = json.loads(st.stdout)
    assert payload["observations"] == 1
    assert payload["pending"] == 0
    assert payload["next_trial_id"] == 2
    assert payload["best"]["trial_id"] == 1


def test_ingest_rejects_param_mismatch(template_copy: Path) -> None:
    s = run_cmd(template_copy, "suggest")
    lines = [line for line in s.stdout.strip().splitlines() if line.strip()]
    suggestion = json.loads("\n".join(lines[:-1]))

    bad = {
        "trial_id": suggestion["trial_id"],
        "params": {"x1": 0.0, "x2": 0.0},
        "objectives": {"loss": 0.4},
        "status": "ok",
    }
    bad_path = template_copy / "examples" / "_bad_result.json"
    bad_path.write_text(json.dumps(bad, indent=2), encoding="utf-8")

    out = run_cmd(template_copy, "ingest", "--results-file", str(bad_path), expect_ok=False)
    assert out.returncode != 0
    assert "params do not match" in out.stderr


def test_ingest_rejects_missing_primary_objective(template_copy: Path) -> None:
    s = run_cmd(template_copy, "suggest")
    lines = [line for line in s.stdout.strip().splitlines() if line.strip()]
    suggestion = json.loads("\n".join(lines[:-1]))

    bad = {
        "trial_id": suggestion["trial_id"],
        "params": suggestion["params"],
        "objectives": {"not_loss": 0.4},
        "status": "ok",
    }
    bad_path = template_copy / "examples" / "_bad_result_missing_obj.json"
    bad_path.write_text(json.dumps(bad, indent=2), encoding="utf-8")

    out = run_cmd(template_copy, "ingest", "--results-file", str(bad_path), expect_ok=False)
    assert out.returncode != 0
    assert "missing primary objective" in out.stderr


def test_demo_runs(template_copy: Path) -> None:
    run_cmd(template_copy, "demo", "--steps", "2")
    st = run_cmd(template_copy, "status")
    payload = json.loads(st.stdout)
    assert payload["observations"] == 2
    assert payload["pending"] == 0


def test_demo_stops_cleanly_when_budget_exhausted(template_copy: Path) -> None:
    run_cmd(template_copy, "demo", "--steps", "45")
    st = run_cmd(template_copy, "status")
    payload = json.loads(st.stdout)
    cfg = json.loads((template_copy / "bo_config.yaml").read_text(encoding="utf-8"))
    assert payload["observations"] == cfg["max_trials"]
    assert payload["pending"] == 0
