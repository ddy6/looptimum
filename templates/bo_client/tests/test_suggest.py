from __future__ import annotations

import importlib.util
import json
import os
import subprocess
from pathlib import Path

import pytest
from conftest import parse_suggestion, run_cmd


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
    bounds_cfg = json.loads((template_copy / "parameter_space.yaml").read_text(encoding="utf-8"))
    for param in bounds_cfg["parameters"]:
        name = param["name"]
        lo, hi = param["bounds"]
        assert float(lo) <= float(suggestion["params"][name]) <= float(hi)


def test_deterministic_first_suggestion_under_fixed_seed(template_copy, tmp_path) -> None:
    src = Path(__file__).resolve().parents[1]
    second_copy = tmp_path / "template_two"
    subprocess.run(["cp", "-R", str(src), str(second_copy)], check=True)
    for p in [
        second_copy / "state" / "bo_state.json",
        second_copy / "state" / "observations.csv",
        second_copy / "state" / "acquisition_log.jsonl",
        second_copy / "examples" / "_demo_result.json",
    ]:
        if p.exists():
            p.unlink()

    first = parse_suggestion(run_cmd(template_copy, "suggest").stdout)
    second = parse_suggestion(run_cmd(second_copy, "suggest").stdout)
    assert first["trial_id"] == second["trial_id"] == 1
    assert first["params"] == second["params"]


@pytest.mark.skipif(
    os.getenv("RUN_GP_TESTS") != "1" or importlib.util.find_spec("botorch") is None,
    reason="set RUN_GP_TESTS=1 and install botorch to run GP backend tests",
)
def test_suggest_works_with_gp_backend(template_copy) -> None:
    cfg_path = template_copy / "bo_config.yaml"
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
