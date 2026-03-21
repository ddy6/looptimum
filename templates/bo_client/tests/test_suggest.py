from __future__ import annotations

import importlib.util
import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest
from conftest import parse_suggestion, run_cmd


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


def test_suggest_supports_mixed_search_space_with_surrogate_scoring(
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
    assert decision["strategy"] == "surrogate_acquisition"
    assert decision["surrogate_backend"] == "rbf_proxy"
    assert isinstance(decision["predicted_mean"], float)
    assert isinstance(decision["predicted_std"], float)
    assert isinstance(decision["acquisition_score"], float)
    status = _assert_constraint_status(decision, enabled=False, phase="candidate-pool")
    assert status["accepted"] == status["requested"]
    assert status["warning"] is None
    assert status["reject_counts"] == {}


def test_suggest_supports_conditional_param_activation_and_omission(
    template_copy, tmp_path
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

    inactive = parse_suggestion(run_cmd(template_copy, "suggest").stdout)
    assert inactive["params"]["gate"] == 0
    assert set(inactive["params"]) == {"gate", "x"}
    assert "momentum" not in inactive["params"]
    inactive_state = json.loads(
        (template_copy / "state" / "bo_state.json").read_text(encoding="utf-8")
    )
    assert inactive_state["pending"][0]["params"] == inactive["params"]

    active = parse_suggestion(run_cmd(active_copy, "suggest").stdout)
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

    next_suggestion = parse_suggestion(run_cmd(template_copy, "suggest").stdout)
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
    assert status["warning"] is None


def test_suggest_applies_constraints_to_initial_random_and_surrogate_pool(template_copy) -> None:
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

    first = parse_suggestion(run_cmd(template_copy, "suggest").stdout)
    assert 0.8 <= first["params"]["x1"] <= 0.9
    assert first["params"]["x1"] + first["params"]["x2"] <= 1.1 + 1e-9

    result = {
        "trial_id": first["trial_id"],
        "params": first["params"],
        "objectives": {"loss": 0.25},
        "status": "ok",
    }
    result_path = template_copy / "examples" / "_constraints_seed_result.json"
    result_path.write_text(json.dumps(result, indent=2), encoding="utf-8")
    run_cmd(template_copy, "ingest", "--results-file", str(result_path))

    second = parse_suggestion(run_cmd(template_copy, "suggest").stdout)
    assert 0.8 <= second["params"]["x1"] <= 0.9
    assert second["params"]["x1"] + second["params"]["x2"] <= 1.1 + 1e-9
    decision = _latest_decision(template_copy)
    assert decision["strategy"] == "surrogate_acquisition"
    assert decision["surrogate_backend"] == "rbf_proxy"
    status = _assert_constraint_status(decision, enabled=True, phase="candidate-pool")
    assert status["requested"] == 100
    assert 1 <= status["accepted"] <= status["requested"]
    assert status["attempted"] >= status["accepted"]
    assert status["warning"] is None
    assert all(
        key in {"linear_inequalities[0]", "bound_tightening[0]"} for key in status["reject_counts"]
    )


def test_suggest_hard_fails_when_constraints_eliminate_all_candidates(template_copy) -> None:
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
    status = _assert_constraint_status(decision, enabled=False, phase="fallback-random")
    assert status["accepted"] == status["requested"] == 1


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
    status = _assert_constraint_status(decision, enabled=False, phase="candidate-pool")
    assert status["accepted"] == status["requested"]


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
    status = _assert_constraint_status(decision, enabled=False, phase="fallback-random")
    assert status["accepted"] == status["requested"] == 1


@pytest.mark.skipif(
    os.getenv("RUN_GP_TESTS") != "1" or importlib.util.find_spec("botorch") is None,
    reason="set RUN_GP_TESTS=1 and install botorch to run GP backend tests",
)
def test_suggest_gp_backend_respects_constraints(template_copy) -> None:
    cfg_path = template_copy / "bo_config.json"
    cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
    cfg["surrogate"]["type"] = "gp"
    cfg["initial_random_trials"] = 2
    cfg["candidate_pool_size"] = 60
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
        suggestion = parse_suggestion(run_cmd(template_copy, "suggest").stdout)
        assert suggestion["params"]["x1"] <= 0.2 + 1e-9
        assert suggestion["params"]["x1"] + suggestion["params"]["x2"] <= 0.7 + 1e-9
        result = {
            "trial_id": suggestion["trial_id"],
            "params": suggestion["params"],
            "objectives": {"loss": 0.4 - 0.05 * idx},
            "status": "ok",
        }
        path = template_copy / "examples" / "_gp_constraints_seed_result.json"
        path.write_text(json.dumps(result, indent=2), encoding="utf-8")
        run_cmd(template_copy, "ingest", "--results-file", str(path))

    suggestion = parse_suggestion(run_cmd(template_copy, "suggest").stdout)
    assert suggestion["trial_id"] == 3
    assert suggestion["params"]["x1"] <= 0.2 + 1e-9
    assert suggestion["params"]["x1"] + suggestion["params"]["x2"] <= 0.7 + 1e-9
    decision = _latest_decision(template_copy)
    assert decision["strategy"] == "surrogate_acquisition"
    assert decision["surrogate_backend"] == "gp"
    status = _assert_constraint_status(decision, enabled=True, phase="candidate-pool")
    assert status["requested"] == 60
    assert 1 <= status["accepted"] <= status["requested"]


@pytest.mark.skipif(
    os.getenv("RUN_GP_TESTS") != "1" or importlib.util.find_spec("botorch") is None,
    reason="set RUN_GP_TESTS=1 and install botorch to run GP backend tests",
)
def test_suggest_supports_mixed_search_space_with_gp_backend(template_copy) -> None:
    (template_copy / "parameter_space.json").write_text(
        json.dumps(_mixed_parameter_space(), indent=2), encoding="utf-8"
    )
    cfg_path = template_copy / "bo_config.json"
    cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
    cfg["surrogate"]["type"] = "gp"
    cfg["initial_random_trials"] = 2
    cfg_path.write_text(json.dumps(cfg, indent=2), encoding="utf-8")

    for idx in range(2):
        suggestion = parse_suggestion(run_cmd(template_copy, "suggest").stdout)
        result = {
            "trial_id": suggestion["trial_id"],
            "params": suggestion["params"],
            "objectives": {"loss": 0.4 - 0.05 * idx},
            "status": "ok",
        }
        path = template_copy / "examples" / "_mixed_gp_seed_result.json"
        path.write_text(json.dumps(result, indent=2), encoding="utf-8")
        run_cmd(template_copy, "ingest", "--results-file", str(path))

    suggestion = parse_suggestion(run_cmd(template_copy, "suggest").stdout)
    assert suggestion["trial_id"] == 3
    assert isinstance(suggestion["params"]["use_bn"], bool)
    assert suggestion["params"]["optimizer"] in {"adam", "sgd", "rmsprop"}

    decision = _latest_decision(template_copy)
    assert decision["strategy"] == "surrogate_acquisition"
    assert decision["surrogate_backend"] == "gp"
    status = _assert_constraint_status(decision, enabled=False, phase="candidate-pool")
    assert status["accepted"] == status["requested"]


def test_suggest_warns_when_constraints_reduce_but_do_not_eliminate_candidate_pool(
    template_copy,
) -> None:
    cfg_path = template_copy / "bo_config.json"
    cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
    cfg["initial_random_trials"] = 1
    cfg["candidate_pool_size"] = 25
    cfg["seed"] = 0
    cfg_path.write_text(json.dumps(cfg, indent=2), encoding="utf-8")

    first = parse_suggestion(run_cmd(template_copy, "suggest").stdout)
    payload = {
        "trial_id": first["trial_id"],
        "params": first["params"],
        "objectives": {"loss": 0.3},
        "status": "ok",
    }
    result_path = template_copy / "examples" / "_constraints_warning_seed.json"
    result_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    run_cmd(template_copy, "ingest", "--results-file", str(result_path))

    _write_constraints(
        template_copy,
        {
            "linear_inequalities": [
                {
                    "terms": [
                        {"param": "x1", "coefficient": 1.0},
                        {"param": "x2", "coefficient": 1.0},
                    ],
                    "operator": "<=",
                    "rhs": 0.25,
                }
            ]
        },
    )

    out = run_cmd(template_copy, "suggest")
    suggestion = parse_suggestion(out.stdout)
    assert suggestion["trial_id"] == 2
    decision = _latest_decision(template_copy)
    status = _assert_constraint_status(decision, enabled=True, phase="candidate-pool")
    assert 0 < status["accepted"] < status["requested"] == 25
    assert status["warning"] in out.stderr
    assert "constraints reduced candidate-pool feasible candidates to" in out.stderr


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
