from __future__ import annotations

import importlib.util
import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest
from conftest import parse_suggestion, run_cmd


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


def test_status_initial(template_copy) -> None:
    out = run_cmd(template_copy, "status")
    payload = json.loads(out.stdout)
    assert payload["observations"] == 0
    assert payload["pending"] == 0
    assert payload["next_trial_id"] == 1
    assert payload["best"] is None


def test_suggest_returns_in_bounds_params(template_copy) -> None:
    out = run_cmd(template_copy, "suggest")
    suggestion = parse_suggestion(out.stdout)
    bounds_cfg = json.loads((template_copy / "parameter_space.json").read_text(encoding="utf-8"))
    for param in bounds_cfg["parameters"]:
        name = param["name"]
        lo, hi = param["bounds"]
        assert float(lo) <= float(suggestion["params"][name]) <= float(hi)


def test_deterministic_first_suggestion_under_fixed_seed(template_copy, tmp_path) -> None:
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

    first = parse_suggestion(run_cmd(template_copy, "suggest").stdout)
    second = parse_suggestion(run_cmd(second_copy, "suggest").stdout)
    assert first["trial_id"] == second["trial_id"] == 1
    assert first["params"] == second["params"]


def test_suggest_supports_mixed_search_space_and_defers_surrogate_scoring(
    template_copy, tmp_path
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

    first = parse_suggestion(run_cmd(template_copy, "suggest").stdout)
    second = parse_suggestion(run_cmd(second_copy, "suggest").stdout)
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

    next_suggestion = parse_suggestion(run_cmd(template_copy, "suggest").stdout)
    assert next_suggestion["trial_id"] == 2
    assert isinstance(next_suggestion["params"]["use_bn"], bool)
    assert next_suggestion["params"]["optimizer"] in {"adam", "sgd", "rmsprop"}

    decision = _latest_decision(template_copy)
    assert decision["strategy"] == "initial_random"
    assert decision["surrogate_backend"] is None
    assert decision["fallback_reason"] == "search_space_requires_workstream1_model_encoding"
    assert decision["fallback_param"] == "lr"
    assert decision["fallback_param_type"] == "float"
    assert decision["fallback_param_scale"] == "log"


def test_suggest_surrogate_falls_back_with_only_non_ok_observations(template_copy) -> None:
    cfg = json.loads((template_copy / "bo_config.json").read_text(encoding="utf-8"))
    initial = int(cfg["initial_random_trials"])

    for idx in range(initial):
        suggestion = parse_suggestion(run_cmd(template_copy, "suggest").stdout)
        failed_result = {
            "trial_id": suggestion["trial_id"],
            "params": suggestion["params"],
            "objectives": {"loss": None},
            "status": "timeout",
            "penalty_objective": 1000.0 + idx,
        }
        path = template_copy / "examples" / "_non_ok_seed_result.json"
        path.write_text(json.dumps(failed_result, indent=2), encoding="utf-8")
        run_cmd(template_copy, "ingest", "--results-file", str(path))

    suggestion = parse_suggestion(run_cmd(template_copy, "suggest").stdout)
    assert suggestion["trial_id"] == initial + 1
    decision = _latest_decision(template_copy)
    assert decision["strategy"] == "initial_random"
    assert decision["surrogate_backend"] is None
    assert decision["fallback_reason"] == "no_usable_observations"


def test_suggest_surrogate_ignores_non_ok_rows_when_usable_rows_exist(template_copy) -> None:
    cfg = json.loads((template_copy / "bo_config.json").read_text(encoding="utf-8"))
    initial = int(cfg["initial_random_trials"])

    for idx in range(max(0, initial - 1)):
        suggestion = parse_suggestion(run_cmd(template_copy, "suggest").stdout)
        failed_result = {
            "trial_id": suggestion["trial_id"],
            "params": suggestion["params"],
            "objectives": {"loss": None},
            "status": "timeout",
            "penalty_objective": 2000.0 + idx,
        }
        path = template_copy / "examples" / "_mixed_seed_failed_result.json"
        path.write_text(json.dumps(failed_result, indent=2), encoding="utf-8")
        run_cmd(template_copy, "ingest", "--results-file", str(path))

    final_seed_suggestion = parse_suggestion(run_cmd(template_copy, "suggest").stdout)
    ok_result = {
        "trial_id": final_seed_suggestion["trial_id"],
        "params": final_seed_suggestion["params"],
        "objectives": {"loss": 0.3},
        "status": "ok",
    }
    path = template_copy / "examples" / "_mixed_seed_ok_result.json"
    path.write_text(json.dumps(ok_result, indent=2), encoding="utf-8")
    run_cmd(template_copy, "ingest", "--results-file", str(path))

    suggestion = parse_suggestion(run_cmd(template_copy, "suggest").stdout)
    assert suggestion["trial_id"] == initial + 1
    decision = _latest_decision(template_copy)
    assert decision["strategy"] == "surrogate_acquisition"
    assert decision["surrogate_backend"] == "rbf_proxy"


def test_gp_backend_falls_back_when_usable_observations_insufficient(template_copy) -> None:
    cfg_path = template_copy / "bo_config.json"
    cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
    cfg["surrogate"]["type"] = "gp"
    cfg["surrogate"]["gp_min_fit_observations"] = 2
    cfg["initial_random_trials"] = 1
    cfg_path.write_text(json.dumps(cfg, indent=2), encoding="utf-8")

    suggestion = parse_suggestion(run_cmd(template_copy, "suggest").stdout)
    result = {
        "trial_id": suggestion["trial_id"],
        "params": suggestion["params"],
        "objectives": {"loss": 0.4},
        "status": "ok",
    }
    path = template_copy / "examples" / "_gp_insufficient_seed_result.json"
    path.write_text(json.dumps(result, indent=2), encoding="utf-8")
    run_cmd(template_copy, "ingest", "--results-file", str(path))

    gp_suggestion = parse_suggestion(run_cmd(template_copy, "suggest").stdout)
    assert gp_suggestion["trial_id"] == 2
    decision = _latest_decision(template_copy)
    assert decision["strategy"] == "initial_random"
    assert decision["surrogate_backend"] is None
    assert decision["fallback_reason"].startswith("insufficient_usable_observations_for_gp")


@pytest.mark.skipif(
    os.getenv("RUN_GP_TESTS") != "1" or importlib.util.find_spec("botorch") is None,
    reason="set RUN_GP_TESTS=1 and install botorch to run GP backend tests",
)
def test_suggest_works_with_gp_backend(template_copy) -> None:
    cfg_path = template_copy / "bo_config.json"
    cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
    cfg["surrogate"]["type"] = "gp"
    cfg_path.write_text(json.dumps(cfg, indent=2), encoding="utf-8")

    # Need at least initial_random_trials observations before the GP path is used.
    initial = int(cfg["initial_random_trials"])
    for _ in range(initial):
        suggestion = parse_suggestion(run_cmd(template_copy, "suggest").stdout)
        result = {
            "trial_id": suggestion["trial_id"],
            "params": suggestion["params"],
            "objectives": {"loss": 0.5},
            "status": "ok",
        }
        p = template_copy / "examples" / "_gp_seed_result.json"
        p.write_text(json.dumps(result, indent=2), encoding="utf-8")
        run_cmd(template_copy, "ingest", "--results-file", str(p))

    gp_suggestion = parse_suggestion(run_cmd(template_copy, "suggest").stdout)
    assert gp_suggestion["trial_id"] == initial + 1
