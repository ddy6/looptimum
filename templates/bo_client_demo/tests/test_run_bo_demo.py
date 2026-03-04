from __future__ import annotations

import json
import shutil
import subprocess
import sys
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


def _parse_suggestion(stdout: str) -> dict:
    lines = [line for line in stdout.strip().splitlines() if line.strip()]
    return json.loads("\n".join(lines[:-1]))


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
    assert "params mismatch for pending trial_id" in out.stderr
    assert "$.params.x1 differs" in out.stderr


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
    assert "field=$.objectives.loss" in out.stderr
    assert "required primary objective present" in out.stderr


def test_duplicate_ingest_identical_replay_is_noop(template_copy: Path) -> None:
    s = run_cmd(template_copy, "suggest")
    lines = [line for line in s.stdout.strip().splitlines() if line.strip()]
    suggestion = json.loads("\n".join(lines[:-1]))
    payload = {
        "trial_id": suggestion["trial_id"],
        "params": suggestion["params"],
        "objectives": {"loss": 0.07},
        "status": "ok",
    }
    path = template_copy / "examples" / "_dup_result.json"
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    run_cmd(template_copy, "ingest", "--results-file", str(path))
    before = json.loads(run_cmd(template_copy, "status").stdout)
    replay = run_cmd(template_copy, "ingest", "--results-file", str(path))
    assert "No-op:" in replay.stdout
    after = json.loads(run_cmd(template_copy, "status").stdout)
    assert after == before


def test_duplicate_ingest_conflicting_replay_is_rejected_with_diff(template_copy: Path) -> None:
    suggestion = _parse_suggestion(run_cmd(template_copy, "suggest").stdout)
    payload = {
        "trial_id": suggestion["trial_id"],
        "params": suggestion["params"],
        "objectives": {"loss": 0.07},
        "status": "ok",
    }
    path = template_copy / "examples" / "_dup_result_conflict.json"
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    run_cmd(template_copy, "ingest", "--results-file", str(path))
    payload["objectives"]["loss"] = 0.2
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    out = run_cmd(template_copy, "ingest", "--results-file", str(path), expect_ok=False)
    assert out.returncode != 0
    assert "conflicting duplicate ingest" in out.stderr
    assert "$.objectives.loss differs" in out.stderr


def test_non_ok_timeout_null_objective_is_accepted(template_copy: Path) -> None:
    s = run_cmd(template_copy, "suggest")
    lines = [line for line in s.stdout.strip().splitlines() if line.strip()]
    suggestion = json.loads("\n".join(lines[:-1]))
    payload = {
        "trial_id": suggestion["trial_id"],
        "params": suggestion["params"],
        "objectives": {"loss": None},
        "status": "timeout",
        "penalty_objective": 1234.0,
    }
    path = template_copy / "examples" / "_timeout_result.json"
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    run_cmd(template_copy, "ingest", "--results-file", str(path))
    state = json.loads((template_copy / "state" / "bo_state.json").read_text(encoding="utf-8"))
    obs = state["observations"][0]
    assert obs["status"] == "timeout"
    assert obs["objectives"]["loss"] is None
    assert obs["penalty_objective"] == 1234.0
    assert state["best"] is None


def test_non_ok_killed_null_objective_is_accepted(template_copy: Path) -> None:
    suggestion = _parse_suggestion(run_cmd(template_copy, "suggest").stdout)
    payload = {
        "trial_id": suggestion["trial_id"],
        "params": suggestion["params"],
        "objectives": {"loss": None},
        "status": "killed",
        "penalty_objective": 555.0,
    }
    path = template_copy / "examples" / "_killed_result.json"
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    run_cmd(template_copy, "ingest", "--results-file", str(path))
    state = json.loads((template_copy / "state" / "bo_state.json").read_text(encoding="utf-8"))
    obs = state["observations"][0]
    assert obs["status"] == "killed"
    assert obs["objectives"]["loss"] is None
    assert obs["penalty_objective"] == 555.0
    assert state["best"] is None


def test_non_ok_sentinel_failed_objective_is_accepted_with_deprecation(template_copy: Path) -> None:
    suggestion = _parse_suggestion(run_cmd(template_copy, "suggest").stdout)
    payload = {
        "trial_id": suggestion["trial_id"],
        "params": suggestion["params"],
        "objectives": {"loss": 1e12},
        "status": "failed",
    }
    path = template_copy / "examples" / "_failed_sentinel_result.json"
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    out = run_cmd(template_copy, "ingest", "--results-file", str(path))
    assert "Deprecated" in out.stderr

    state = json.loads((template_copy / "state" / "bo_state.json").read_text(encoding="utf-8"))
    obs = state["observations"][0]
    assert obs["status"] == "failed"
    assert obs["objectives"]["loss"] is None
    assert obs["penalty_objective"] == 1e12


def test_non_ok_penalty_does_not_affect_best_ranking(template_copy: Path) -> None:
    s1 = run_cmd(template_copy, "suggest")
    lines1 = [line for line in s1.stdout.strip().splitlines() if line.strip()]
    suggestion1 = json.loads("\n".join(lines1[:-1]))
    ok_payload = {
        "trial_id": suggestion1["trial_id"],
        "params": suggestion1["params"],
        "objectives": {"loss": 0.1},
        "status": "ok",
    }
    p1 = template_copy / "examples" / "_best_ok_result.json"
    p1.write_text(json.dumps(ok_payload, indent=2), encoding="utf-8")
    run_cmd(template_copy, "ingest", "--results-file", str(p1))

    s2 = run_cmd(template_copy, "suggest")
    lines2 = [line for line in s2.stdout.strip().splitlines() if line.strip()]
    suggestion2 = json.loads("\n".join(lines2[:-1]))
    failed_payload = {
        "trial_id": suggestion2["trial_id"],
        "params": suggestion2["params"],
        "objectives": {"loss": None},
        "status": "timeout",
        "penalty_objective": -1.0e9,
    }
    p2 = template_copy / "examples" / "_best_timeout_result.json"
    p2.write_text(json.dumps(failed_payload, indent=2), encoding="utf-8")
    run_cmd(template_copy, "ingest", "--results-file", str(p2))

    state = json.loads((template_copy / "state" / "bo_state.json").read_text(encoding="utf-8"))
    assert len(state["observations"]) == 2
    assert state["best"]["trial_id"] == suggestion1["trial_id"]
    assert state["best"]["objective_value"] == 0.1


def test_resume_restores_state_and_trial_ids(template_copy: Path) -> None:
    suggestion = _parse_suggestion(run_cmd(template_copy, "suggest").stdout)
    payload = {
        "trial_id": suggestion["trial_id"],
        "params": suggestion["params"],
        "objectives": {"loss": 0.2},
        "status": "ok",
    }
    path = template_copy / "examples" / "_resume_ingest.json"
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    run_cmd(template_copy, "ingest", "--results-file", str(path))

    status = json.loads(run_cmd(template_copy, "status").stdout)
    assert status["observations"] == 1
    assert status["next_trial_id"] == 2

    second = _parse_suggestion(run_cmd(template_copy, "suggest").stdout)
    assert second["trial_id"] == 2
    status2 = json.loads(run_cmd(template_copy, "status").stdout)
    assert status2["pending"] == 1


def test_demo_runs(template_copy: Path) -> None:
    run_cmd(template_copy, "demo", "--steps", "2")
    st = run_cmd(template_copy, "status")
    payload = json.loads(st.stdout)
    assert payload["observations"] == 2
    assert payload["pending"] == 0
    assert not (template_copy / "examples" / "_demo_result.json").exists()
    assert (template_copy / "state" / "trials" / "trial_1" / "demo_result.json").exists()


def test_demo_stops_cleanly_when_budget_exhausted(template_copy: Path) -> None:
    run_cmd(template_copy, "demo", "--steps", "45")
    st = run_cmd(template_copy, "status")
    payload = json.loads(st.stdout)
    cfg = json.loads((template_copy / "bo_config.json").read_text(encoding="utf-8"))
    assert payload["observations"] == cfg["max_trials"]
    assert payload["pending"] == 0
