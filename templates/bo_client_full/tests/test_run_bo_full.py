from __future__ import annotations

import importlib.util
import json
import os
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
    payload = _parse_json_output(stdout)
    assert isinstance(payload, dict)
    assert "trial_id" in payload
    return payload


def _parse_json_output(stdout: str) -> object:
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


def _parse_suggestion_bundle(stdout: str) -> dict:
    payload = _parse_json_output(stdout)
    assert isinstance(payload, dict)
    assert "suggestions" in payload
    return payload


def _parse_jsonl_suggestions(stdout: str) -> list[dict]:
    lines = [line for line in stdout.splitlines() if line.strip()]
    return [json.loads(line) for line in lines]


def _latest_log_record(template_copy: Path) -> dict:
    lines = [
        line
        for line in (template_copy / "state" / "acquisition_log.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
        if line.strip()
    ]
    assert lines
    return json.loads(lines[-1])


def _latest_decision(template_copy: Path) -> dict:
    return _latest_log_record(template_copy)["decision"]


def _assert_constraint_status(decision: dict, *, enabled: bool, phase: str) -> dict:
    status = decision["constraint_status"]
    assert status["enabled"] is enabled
    assert status["phase"] == phase
    assert isinstance(status["requested"], int)
    assert isinstance(status["accepted"], int)
    assert isinstance(status["attempted"], int)
    assert isinstance(status["rejected"], int)
    assert isinstance(status["feasible_ratio"], float)
    assert isinstance(status["reject_counts"], dict)
    assert status["rejected"] == status["attempted"] - status["accepted"]
    return status


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


def _write_constraints(project_root: Path, payload: dict) -> None:
    (project_root / "constraints.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")


def _write_weighted_sum_objective_schema(project_root: Path) -> None:
    (project_root / "objective_schema.json").write_text(
        json.dumps(
            {
                "primary_objective": {"name": "loss", "direction": "minimize"},
                "secondary_objectives": [{"name": "throughput", "direction": "maximize"}],
                "scalarization": {
                    "policy": "weighted_sum",
                    "weights": {"loss": 1.0, "throughput": 1.0},
                },
            },
            indent=2,
        ),
        encoding="utf-8",
    )


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


def test_suggest_count_creates_batch_bundle_and_pending_state(template_copy: Path) -> None:
    out = run_cmd(template_copy, "suggest", "--count", "2", "--json-only")
    bundle = _parse_suggestion_bundle(out.stdout)
    suggestions = bundle["suggestions"]

    assert bundle["count"] == 2
    assert [item["trial_id"] for item in suggestions] == [1, 2]

    state = json.loads((template_copy / "state" / "bo_state.json").read_text(encoding="utf-8"))
    assert [item["trial_id"] for item in state["pending"]] == [1, 2]
    assert state["next_trial_id"] == 3


def test_suggest_jsonl_output_emits_one_suggestion_per_line(template_copy: Path) -> None:
    out = run_cmd(template_copy, "suggest", "--count", "2", "--jsonl")
    suggestions = _parse_jsonl_suggestions(out.stdout)

    assert [item["trial_id"] for item in suggestions] == [1, 2]
    assert "Objective direction:" not in out.stdout

    state = json.loads((template_copy / "state" / "bo_state.json").read_text(encoding="utf-8"))
    assert [item["trial_id"] for item in state["pending"]] == [1, 2]


def test_suggest_rejects_batch_when_max_pending_trials_would_be_exceeded(
    template_copy: Path,
) -> None:
    cfg_path = template_copy / "bo_config.json"
    cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
    cfg["max_pending_trials"] = 2
    cfg_path.write_text(json.dumps(cfg, indent=2), encoding="utf-8")

    first = run_cmd(template_copy, "suggest", "--count", "2", "--json-only")
    bundle = _parse_suggestion_bundle(first.stdout)
    assert bundle["count"] == 2

    out = run_cmd(template_copy, "suggest")
    assert (
        "No suggestion generated: max_pending_trials=2 would be exceeded "
        "(current_pending=2, requested_count=1)." in out.stdout
    )

    state = json.loads((template_copy / "state" / "bo_state.json").read_text(encoding="utf-8"))
    assert [item["trial_id"] for item in state["pending"]] == [1, 2]
    assert state["next_trial_id"] == 3


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
    assert decision["surrogate_backend"] == "rbf_proxy"
    assert isinstance(decision["predicted_mean"], float)
    assert isinstance(decision["predicted_std"], float)
    assert isinstance(decision["acquisition_score"], float)
    status = _assert_constraint_status(decision, enabled=False, phase="candidate-pool")
    assert status["accepted"] == status["requested"]
    assert status["warning"] is None


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
    assert decision["surrogate_backend"] == "rbf_proxy"
    status = _assert_constraint_status(decision, enabled=False, phase="candidate-pool")
    assert status["accepted"] == status["requested"]


def test_suggest_applies_constraints_to_initial_random_and_surrogate_pool(
    template_copy: Path,
) -> None:
    cfg_path = template_copy / "bo_config.json"
    cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
    cfg["initial_random_trials"] = 1
    cfg["candidate_pool_size"] = 100
    cfg_path.write_text(json.dumps(cfg, indent=2), encoding="utf-8")
    _write_constraints(
        template_copy,
        {
            "bound_tightening": [{"param": "x1", "min": 0.8, "max": 0.9}],
            "linear_inequalities": [
                {
                    "terms": [
                        {"param": "x1", "coefficient": 1.0},
                        {"param": "x2", "coefficient": 1.0},
                    ],
                    "operator": "<=",
                    "rhs": 1.1,
                }
            ],
        },
    )

    first = _parse_suggestion(run_cmd(template_copy, "suggest").stdout)
    assert 0.8 <= first["params"]["x1"] <= 0.9
    assert first["params"]["x1"] + first["params"]["x2"] <= 1.1 + 1e-9

    payload = {
        "trial_id": first["trial_id"],
        "params": first["params"],
        "objectives": {"loss": 0.25},
        "status": "ok",
    }
    path = template_copy / "examples" / "_constraints_seed_result.json"
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    run_cmd(template_copy, "ingest", "--results-file", str(path))

    second = _parse_suggestion(run_cmd(template_copy, "suggest").stdout)
    assert 0.8 <= second["params"]["x1"] <= 0.9
    assert second["params"]["x1"] + second["params"]["x2"] <= 1.1 + 1e-9
    decision = _latest_decision(template_copy)
    assert decision["strategy"] == "surrogate_acquisition"
    assert decision["surrogate_backend"] == "rbf_proxy"
    status = _assert_constraint_status(decision, enabled=True, phase="candidate-pool")
    assert status["requested"] == 100
    assert 1 <= status["accepted"] <= status["requested"]
    assert status["warning"] is None


def test_suggest_hard_fails_when_constraints_eliminate_all_candidates(
    template_copy: Path,
) -> None:
    (template_copy / "parameter_space.json").write_text(
        json.dumps({"parameters": [{"name": "x", "type": "int", "bounds": [0, 0]}]}, indent=2),
        encoding="utf-8",
    )
    cfg_path = template_copy / "bo_config.json"
    cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
    cfg["candidate_pool_size"] = 25
    cfg_path.write_text(json.dumps(cfg, indent=2), encoding="utf-8")
    _write_constraints(template_copy, {"forbidden_combinations": [{"when": {"x": 0}}]})

    out = run_cmd(template_copy, "suggest", expect_ok=False)

    assert out.returncode != 0
    assert (
        "ERROR: constraints eliminated all 25 initial-random attempts "
        "(dominant rejects: forbidden_combinations[0]=25)" in out.stderr
    )
    record = _latest_log_record(template_copy)
    assert record["trial_id"] == 1
    decision = record["decision"]
    assert decision["strategy"] == "initial_random"
    assert decision["surrogate_backend"] is None
    assert (
        decision["constraint_error_reason"]
        == "constraints eliminated all 25 initial-random attempts "
        "(dominant rejects: forbidden_combinations[0]=25)"
    )
    status = _assert_constraint_status(decision, enabled=True, phase="initial-random")
    assert status["requested"] == 1
    assert status["accepted"] == 0
    assert status["attempted"] == 25
    assert status["warning"] is None
    assert status["reject_counts"] == {"forbidden_combinations[0]": 25}


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
    assert "required configured objective present" in out.stderr


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
            "penalty_objective": 5000.0 + idx,
        }
        path = template_copy / "examples" / "_surrogate_non_ok_seed.json"
        path.write_text(json.dumps(failed_payload, indent=2), encoding="utf-8")
        run_cmd(template_copy, "ingest", "--results-file", str(path))

    suggestion = _parse_suggestion(run_cmd(template_copy, "suggest").stdout)
    assert suggestion["trial_id"] == initial + 1
    decision = _latest_decision(template_copy)
    assert decision["strategy"] == "initial_random"
    assert decision["surrogate_backend"] is None
    assert decision["fallback_reason"] == "no_usable_observations"
    status = _assert_constraint_status(decision, enabled=False, phase="fallback-random")
    assert status["accepted"] == status["requested"] == 1


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
            "penalty_objective": 6000.0 + idx,
        }
        path = template_copy / "examples" / "_surrogate_mixed_failed_seed.json"
        path.write_text(json.dumps(failed_payload, indent=2), encoding="utf-8")
        run_cmd(template_copy, "ingest", "--results-file", str(path))

    final_seed = _parse_suggestion(run_cmd(template_copy, "suggest").stdout)
    ok_payload = {
        "trial_id": final_seed["trial_id"],
        "params": final_seed["params"],
        "objectives": {"loss": 0.2},
        "status": "ok",
    }
    path = template_copy / "examples" / "_surrogate_mixed_ok_seed.json"
    path.write_text(json.dumps(ok_payload, indent=2), encoding="utf-8")
    run_cmd(template_copy, "ingest", "--results-file", str(path))

    suggestion = _parse_suggestion(run_cmd(template_copy, "suggest").stdout)
    assert suggestion["trial_id"] == initial + 1
    decision = _latest_decision(template_copy)
    assert decision["strategy"] == "surrogate_acquisition"
    assert decision["surrogate_backend"] in {"rbf_proxy", "botorch_gp"}
    status = _assert_constraint_status(decision, enabled=False, phase="candidate-pool")
    assert status["accepted"] == status["requested"]


def test_botorch_backend_falls_back_when_usable_observations_insufficient(
    template_copy: Path,
) -> None:
    cfg_path = template_copy / "bo_config.json"
    cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
    cfg["initial_random_trials"] = 1
    cfg["feature_flags"]["enable_botorch_gp"] = True
    cfg["surrogate"]["botorch_min_fit_observations"] = 2
    cfg_path.write_text(json.dumps(cfg, indent=2), encoding="utf-8")

    suggestion = _parse_suggestion(run_cmd(template_copy, "suggest").stdout)
    ok_payload = {
        "trial_id": suggestion["trial_id"],
        "params": suggestion["params"],
        "objectives": {"loss": 0.35},
        "status": "ok",
    }
    path = template_copy / "examples" / "_botorch_insufficient_seed.json"
    path.write_text(json.dumps(ok_payload, indent=2), encoding="utf-8")
    run_cmd(template_copy, "ingest", "--results-file", str(path))

    next_suggestion = _parse_suggestion(run_cmd(template_copy, "suggest").stdout)
    assert next_suggestion["trial_id"] == 2
    decision = _latest_decision(template_copy)
    assert decision["strategy"] == "initial_random"
    assert decision["surrogate_backend"] is None
    assert decision["fallback_reason"].startswith("insufficient_usable_observations_for_botorch_gp")
    status = _assert_constraint_status(decision, enabled=False, phase="fallback-random")
    assert status["accepted"] == status["requested"] == 1


@pytest.mark.skipif(
    os.getenv("RUN_GP_TESTS") != "1" or importlib.util.find_spec("botorch") is None,
    reason="set RUN_GP_TESTS=1 and install botorch to run BoTorch backend tests",
)
def test_suggest_supports_mixed_search_space_with_botorch_backend(template_copy: Path) -> None:
    (template_copy / "parameter_space.json").write_text(
        json.dumps(_mixed_parameter_space(), indent=2), encoding="utf-8"
    )
    cfg_path = template_copy / "bo_config.json"
    cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
    cfg["initial_random_trials"] = 2
    cfg["feature_flags"]["enable_botorch_gp"] = True
    cfg["surrogate"]["botorch_min_fit_observations"] = 2
    cfg_path.write_text(json.dumps(cfg, indent=2), encoding="utf-8")

    for idx in range(2):
        suggestion = _parse_suggestion(run_cmd(template_copy, "suggest").stdout)
        payload = {
            "trial_id": suggestion["trial_id"],
            "params": suggestion["params"],
            "objectives": {"loss": 0.4 - 0.05 * idx},
            "status": "ok",
        }
        path = template_copy / "examples" / "_mixed_botorch_seed.json"
        path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        run_cmd(template_copy, "ingest", "--results-file", str(path))

    suggestion = _parse_suggestion(run_cmd(template_copy, "suggest").stdout)
    assert suggestion["trial_id"] == 3
    assert isinstance(suggestion["params"]["use_bn"], bool)
    assert suggestion["params"]["optimizer"] in {"adam", "sgd", "rmsprop"}

    decision = _latest_decision(template_copy)
    assert decision["strategy"] == "surrogate_acquisition"
    assert decision["surrogate_backend"] == "botorch_gp"
    status = _assert_constraint_status(decision, enabled=False, phase="candidate-pool")
    assert status["accepted"] == status["requested"]


@pytest.mark.skipif(
    os.getenv("RUN_GP_TESTS") != "1" or importlib.util.find_spec("botorch") is None,
    reason="set RUN_GP_TESTS=1 and install botorch to run BoTorch backend tests",
)
def test_botorch_backend_respects_constraints(template_copy: Path) -> None:
    cfg_path = template_copy / "bo_config.json"
    cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
    cfg["initial_random_trials"] = 2
    cfg["candidate_pool_size"] = 60
    cfg["feature_flags"]["enable_botorch_gp"] = True
    cfg["surrogate"]["botorch_min_fit_observations"] = 2
    cfg_path.write_text(json.dumps(cfg, indent=2), encoding="utf-8")
    _write_constraints(
        template_copy,
        {
            "bound_tightening": [{"param": "x1", "max": 0.2}],
            "linear_inequalities": [
                {
                    "terms": [
                        {"param": "x1", "coefficient": 1.0},
                        {"param": "x2", "coefficient": 1.0},
                    ],
                    "operator": "<=",
                    "rhs": 0.7,
                }
            ],
        },
    )

    for idx in range(2):
        suggestion = _parse_suggestion(run_cmd(template_copy, "suggest").stdout)
        assert suggestion["params"]["x1"] <= 0.2 + 1e-9
        assert suggestion["params"]["x1"] + suggestion["params"]["x2"] <= 0.7 + 1e-9
        payload = {
            "trial_id": suggestion["trial_id"],
            "params": suggestion["params"],
            "objectives": {"loss": 0.4 - 0.05 * idx},
            "status": "ok",
        }
        path = template_copy / "examples" / "_botorch_constraints_seed.json"
        path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        run_cmd(template_copy, "ingest", "--results-file", str(path))

    suggestion = _parse_suggestion(run_cmd(template_copy, "suggest").stdout)
    assert suggestion["trial_id"] == 3
    assert suggestion["params"]["x1"] <= 0.2 + 1e-9
    assert suggestion["params"]["x1"] + suggestion["params"]["x2"] <= 0.7 + 1e-9
    decision = _latest_decision(template_copy)
    assert decision["strategy"] == "surrogate_acquisition"
    assert decision["surrogate_backend"] == "botorch_gp"
    status = _assert_constraint_status(decision, enabled=True, phase="candidate-pool")
    assert status["requested"] == 60
    assert 1 <= status["accepted"] <= status["requested"]


@pytest.mark.skipif(
    os.getenv("RUN_GP_TESTS") != "1" or importlib.util.find_spec("botorch") is None,
    reason="set RUN_GP_TESTS=1 and install botorch to run BoTorch backend tests",
)
def test_multi_objective_weighted_sum_uses_botorch_and_updates_best(template_copy: Path) -> None:
    _write_weighted_sum_objective_schema(template_copy)

    cfg_path = template_copy / "bo_config.json"
    cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
    cfg["initial_random_trials"] = 2
    cfg["feature_flags"]["enable_botorch_gp"] = True
    cfg["surrogate"]["botorch_min_fit_observations"] = 2
    cfg_path.write_text(json.dumps(cfg, indent=2), encoding="utf-8")

    for trial_id, objective_values in enumerate(
        [
            {"loss": 0.2, "throughput": 1.0},
            {"loss": 0.3, "throughput": 2.0},
        ],
        start=1,
    ):
        suggestion = _parse_suggestion(run_cmd(template_copy, "suggest").stdout)
        assert suggestion["trial_id"] == trial_id
        payload = {
            "trial_id": suggestion["trial_id"],
            "params": suggestion["params"],
            "objectives": objective_values,
            "status": "ok",
        }
        path = template_copy / "examples" / f"_multi_objective_full_seed_{trial_id}.json"
        path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        run_cmd(template_copy, "ingest", "--results-file", str(path))

    suggestion = _parse_suggestion(run_cmd(template_copy, "suggest").stdout)
    assert suggestion["trial_id"] == 3
    decision = _latest_decision(template_copy)
    assert decision["strategy"] == "surrogate_acquisition"
    assert decision["surrogate_backend"] == "botorch_gp"
    assert isinstance(decision["predicted_mean"], float)
    assert isinstance(decision["predicted_std"], float)

    status = json.loads(run_cmd(template_copy, "status").stdout)
    best = status["best"]
    assert best["trial_id"] == 2
    assert best["objective_name"] == "scalarized"
    assert best["scalarization_policy"] == "weighted_sum"
    assert best["objective_vector"] == {"loss": 0.3, "throughput": 2.0}
    assert best["objective_value"] == pytest.approx(-0.85)


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
