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


def _latest_decision(template_copy: Path) -> dict:
    lines = [
        line
        for line in (template_copy / "state" / "acquisition_log.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
        if line.strip()
    ]
    assert lines
    payload = json.loads(lines[-1])
    return payload["decision"]


def _mixed_parameter_space() -> dict:
    return {
        "parameters": [
            {"name": "lr", "type": "float", "bounds": [0.0001, 0.1], "scale": "log"},
            {"name": "layers", "type": "int", "bounds": [1, 8]},
            {"name": "use_bn", "type": "bool"},
            {"name": "optimizer", "type": "categorical", "choices": ["adam", "sgd", "rmsprop"]},
        ]
    }


def _conditional_parameter_space() -> dict:
    return {
        "parameters": [
            {
                "name": "momentum",
                "type": "float",
                "bounds": [0.0, 0.99],
                "when": {"gate": 1},
            },
            {"name": "x", "type": "float", "bounds": [0.0, 1.0]},
            {"name": "gate", "type": "int", "bounds": [0, 1]},
        ]
    }


def test_status_initial(template_copy: Path) -> None:
    out = run_cmd(template_copy, "status")
    payload = json.loads(out.stdout)
    assert payload["observations"] == 0
    assert payload["pending"] == 0
    assert payload["next_trial_id"] == 1
    assert payload["best"] is None


def test_deterministic_first_suggestion_under_fixed_seed(
    template_copy: Path, tmp_path: Path
) -> None:
    src = Path(__file__).resolve().parents[1]
    second_copy = tmp_path / "template_two"
    subprocess.run(["cp", "-R", str(src), str(second_copy)], check=True)
    shared_src = src.parent / "_shared"
    if shared_src.exists() and not (tmp_path / "_shared").exists():
        subprocess.run(["cp", "-R", str(shared_src), str(tmp_path / "_shared")], check=True)
    for p in [
        second_copy / "state" / "bo_state.json",
        second_copy / "state" / "observations.csv",
        second_copy / "state" / "acquisition_log.jsonl",
        second_copy / "state" / "event_log.jsonl",
        second_copy / "state" / ".looptimum.lock",
        second_copy / "state" / "report.json",
        second_copy / "state" / "report.md",
        second_copy / "examples" / "_demo_result.json",
    ]:
        if p.exists():
            p.unlink()
    trials_dir = second_copy / "state" / "trials"
    if trials_dir.exists():
        shutil.rmtree(trials_dir)

    first = _parse_suggestion(run_cmd(template_copy, "suggest").stdout)
    second = _parse_suggestion(run_cmd(second_copy, "suggest").stdout)
    assert first["trial_id"] == second["trial_id"] == 1
    assert first["params"] == second["params"]


def test_suggest_supports_mixed_search_space_with_surrogate_scoring(
    template_copy: Path, tmp_path: Path
) -> None:
    src = Path(__file__).resolve().parents[1]
    second_copy = tmp_path / "template_two"
    subprocess.run(["cp", "-R", str(src), str(second_copy)], check=True)
    shared_src = src.parent / "_shared"
    if shared_src.exists() and not (tmp_path / "_shared").exists():
        subprocess.run(["cp", "-R", str(shared_src), str(tmp_path / "_shared")], check=True)
    for p in [
        second_copy / "state" / "bo_state.json",
        second_copy / "state" / "observations.csv",
        second_copy / "state" / "acquisition_log.jsonl",
        second_copy / "state" / "event_log.jsonl",
        second_copy / "state" / ".looptimum.lock",
        second_copy / "state" / "report.json",
        second_copy / "state" / "report.md",
        second_copy / "examples" / "_demo_result.json",
    ]:
        if p.exists():
            p.unlink()
    trials_dir = second_copy / "state" / "trials"
    if trials_dir.exists():
        shutil.rmtree(trials_dir)

    mixed_cfg = _mixed_parameter_space()
    for project_root in [template_copy, second_copy]:
        (project_root / "parameter_space.json").write_text(
            json.dumps(mixed_cfg, indent=2), encoding="utf-8"
        )
        cfg_path = project_root / "bo_config.json"
        cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
        cfg["initial_random_trials"] = 1
        cfg_path.write_text(json.dumps(cfg, indent=2), encoding="utf-8")

    first = _parse_suggestion(run_cmd(template_copy, "suggest").stdout)
    second = _parse_suggestion(run_cmd(second_copy, "suggest").stdout)
    assert first["trial_id"] == second["trial_id"] == 1
    assert first["params"] == second["params"]
    assert 0.0001 <= first["params"]["lr"] <= 0.1
    assert 1 <= first["params"]["layers"] <= 8
    assert isinstance(first["params"]["use_bn"], bool)
    assert first["params"]["optimizer"] in {"adam", "sgd", "rmsprop"}

    result = {
        "trial_id": first["trial_id"],
        "params": first["params"],
        "objectives": {"loss": 0.4},
        "status": "ok",
    }
    result_path = template_copy / "examples" / "_mixed_search_space_seed.json"
    result_path.write_text(json.dumps(result, indent=2), encoding="utf-8")
    run_cmd(template_copy, "ingest", "--results-file", str(result_path))

    state = json.loads((template_copy / "state" / "bo_state.json").read_text(encoding="utf-8"))
    assert state["observations"][0]["params"] == first["params"]

    next_suggestion = _parse_suggestion(run_cmd(template_copy, "suggest").stdout)
    assert next_suggestion["trial_id"] == 2
    assert isinstance(next_suggestion["params"]["use_bn"], bool)
    assert next_suggestion["params"]["optimizer"] in {"adam", "sgd", "rmsprop"}

    decision = _latest_decision(template_copy)
    assert decision["strategy"] == "surrogate_acquisition"
    assert isinstance(decision["predicted_mean"], float)
    assert isinstance(decision["predicted_std"], float)
    assert isinstance(decision["acquisition_score"], float)


def test_suggest_supports_conditional_param_activation_and_omission(
    template_copy: Path, tmp_path: Path
) -> None:
    src = Path(__file__).resolve().parents[1]
    active_copy = tmp_path / "template_active"
    subprocess.run(["cp", "-R", str(src), str(active_copy)], check=True)
    shared_src = src.parent / "_shared"
    if shared_src.exists() and not (tmp_path / "_shared").exists():
        subprocess.run(["cp", "-R", str(shared_src), str(tmp_path / "_shared")], check=True)
    for p in [
        active_copy / "state" / "bo_state.json",
        active_copy / "state" / "observations.csv",
        active_copy / "state" / "acquisition_log.jsonl",
        active_copy / "state" / "event_log.jsonl",
        active_copy / "state" / ".looptimum.lock",
        active_copy / "state" / "report.json",
        active_copy / "state" / "report.md",
        active_copy / "examples" / "_demo_result.json",
    ]:
        if p.exists():
            p.unlink()
    trials_dir = active_copy / "state" / "trials"
    if trials_dir.exists():
        shutil.rmtree(trials_dir)

    for project_root, seed in [(template_copy, 0), (active_copy, 4)]:
        (project_root / "parameter_space.json").write_text(
            json.dumps(_conditional_parameter_space(), indent=2), encoding="utf-8"
        )
        cfg_path = project_root / "bo_config.json"
        cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
        cfg["initial_random_trials"] = 1
        cfg["seed"] = seed
        cfg_path.write_text(json.dumps(cfg, indent=2), encoding="utf-8")

    inactive = _parse_suggestion(run_cmd(template_copy, "suggest").stdout)
    assert inactive["params"]["gate"] == 0
    assert set(inactive["params"]) == {"gate", "x"}
    assert "momentum" not in inactive["params"]
    inactive_state = json.loads(
        (template_copy / "state" / "bo_state.json").read_text(encoding="utf-8")
    )
    assert inactive_state["pending"][0]["params"] == inactive["params"]

    active = _parse_suggestion(run_cmd(active_copy, "suggest").stdout)
    assert active["params"]["gate"] == 1
    assert set(active["params"]) == {"gate", "momentum", "x"}
    assert 0.0 <= active["params"]["momentum"] <= 0.99

    result = {
        "trial_id": inactive["trial_id"],
        "params": inactive["params"],
        "objectives": {"loss": 0.3},
        "status": "ok",
    }
    result_path = template_copy / "examples" / "_conditional_seed_result.json"
    result_path.write_text(json.dumps(result, indent=2), encoding="utf-8")
    run_cmd(template_copy, "ingest", "--results-file", str(result_path))

    next_suggestion = _parse_suggestion(run_cmd(template_copy, "suggest").stdout)
    assert next_suggestion["trial_id"] == 2
    assert next_suggestion["params"]["gate"] in {0, 1}
    if next_suggestion["params"]["gate"] == 0:
        assert set(next_suggestion["params"]) == {"gate", "x"}
        assert "momentum" not in next_suggestion["params"]
    else:
        assert set(next_suggestion["params"]) == {"gate", "momentum", "x"}
        assert 0.0 <= next_suggestion["params"]["momentum"] <= 0.99

    decision = _latest_decision(template_copy)
    assert decision["strategy"] == "surrogate_acquisition"


def test_ingest_canonicalizes_inactive_conditional_params_and_duplicate_replay(
    template_copy: Path,
) -> None:
    (template_copy / "parameter_space.json").write_text(
        json.dumps(_conditional_parameter_space(), indent=2), encoding="utf-8"
    )
    cfg_path = template_copy / "bo_config.json"
    cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
    cfg["seed"] = 0
    cfg["initial_random_trials"] = 1
    cfg_path.write_text(json.dumps(cfg, indent=2), encoding="utf-8")

    suggestion = _parse_suggestion(run_cmd(template_copy, "suggest").stdout)
    assert suggestion["params"]["gate"] == 0
    assert set(suggestion["params"]) == {"gate", "x"}

    payload = {
        "trial_id": suggestion["trial_id"],
        "params": {**suggestion["params"], "momentum": 0.44},
        "objectives": {"loss": 0.18},
        "status": "ok",
    }
    path = template_copy / "examples" / "_conditional_ingest_extra.json"
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    run_cmd(template_copy, "ingest", "--results-file", str(path))
    state = json.loads((template_copy / "state" / "bo_state.json").read_text(encoding="utf-8"))
    observation = state["observations"][0]
    assert observation["params"] == suggestion["params"]
    artifact_payload = json.loads(
        (template_copy / observation["artifact_path"]).read_text(encoding="utf-8")
    )
    assert artifact_payload["params"] == suggestion["params"]

    replay = run_cmd(template_copy, "ingest", "--results-file", str(path))
    assert "No-op:" in replay.stdout


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


def test_non_ok_numeric_primary_objective_is_rejected(template_copy: Path) -> None:
    suggestion = _parse_suggestion(run_cmd(template_copy, "suggest").stdout)
    payload = {
        "trial_id": suggestion["trial_id"],
        "params": suggestion["params"],
        "objectives": {"loss": 1e12},
        "status": "failed",
    }
    path = template_copy / "examples" / "_failed_sentinel_result.json"
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    out = run_cmd(template_copy, "ingest", "--results-file", str(path), expect_ok=False)
    assert out.returncode != 0
    assert "field=$.objectives.loss" in out.stderr
    assert "null for non-ok status" in out.stderr


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


def test_suggest_surrogate_falls_back_with_only_non_ok_observations(template_copy: Path) -> None:
    cfg = json.loads((template_copy / "bo_config.json").read_text(encoding="utf-8"))
    initial = int(cfg["initial_random_trials"])

    for idx in range(initial):
        suggestion = _parse_suggestion(run_cmd(template_copy, "suggest").stdout)
        failed_payload = {
            "trial_id": suggestion["trial_id"],
            "params": suggestion["params"],
            "objectives": {"loss": None},
            "status": "timeout",
            "penalty_objective": 3000.0 + idx,
        }
        path = template_copy / "examples" / "_surrogate_non_ok_seed.json"
        path.write_text(json.dumps(failed_payload, indent=2), encoding="utf-8")
        run_cmd(template_copy, "ingest", "--results-file", str(path))

    suggestion = _parse_suggestion(run_cmd(template_copy, "suggest").stdout)
    assert suggestion["trial_id"] == initial + 1
    decision = _latest_decision(template_copy)
    assert decision["strategy"] == "initial_random"
    assert decision["fallback_reason"] == "no_usable_observations"


def test_suggest_surrogate_ignores_non_ok_rows_when_usable_rows_exist(template_copy: Path) -> None:
    cfg = json.loads((template_copy / "bo_config.json").read_text(encoding="utf-8"))
    initial = int(cfg["initial_random_trials"])

    for idx in range(max(0, initial - 1)):
        suggestion = _parse_suggestion(run_cmd(template_copy, "suggest").stdout)
        failed_payload = {
            "trial_id": suggestion["trial_id"],
            "params": suggestion["params"],
            "objectives": {"loss": None},
            "status": "timeout",
            "penalty_objective": 4000.0 + idx,
        }
        path = template_copy / "examples" / "_surrogate_mixed_failed_seed.json"
        path.write_text(json.dumps(failed_payload, indent=2), encoding="utf-8")
        run_cmd(template_copy, "ingest", "--results-file", str(path))

    final_seed = _parse_suggestion(run_cmd(template_copy, "suggest").stdout)
    ok_payload = {
        "trial_id": final_seed["trial_id"],
        "params": final_seed["params"],
        "objectives": {"loss": 0.25},
        "status": "ok",
    }
    path = template_copy / "examples" / "_surrogate_mixed_ok_seed.json"
    path.write_text(json.dumps(ok_payload, indent=2), encoding="utf-8")
    run_cmd(template_copy, "ingest", "--results-file", str(path))

    suggestion = _parse_suggestion(run_cmd(template_copy, "suggest").stdout)
    assert suggestion["trial_id"] == initial + 1
    decision = _latest_decision(template_copy)
    assert decision["strategy"] == "surrogate_acquisition"


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
