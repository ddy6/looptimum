from __future__ import annotations

import copy
import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


def load_shared(name):
    spec = importlib.util.spec_from_file_location(
        f"test_ax_{name}", ROOT / "templates/_shared" / f"{name}.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


BACKEND = load_shared("optimizer_backend")
RUNTIME = load_shared("runtime")
OBJECTIVES = load_shared("objectives")
SEARCH = load_shared("search_space")
AX = load_shared("optimizer_ax")


def test_absent_optimizer_preserves_legacy_and_new_options_are_strict():
    assert BACKEND.normalize_optimizer_config({}) == {"backend": "legacy"}
    assert BACKEND.normalize_optimizer_config({"optimizer": {"backend": "legacy"}}) == {
        "backend": "legacy"
    }
    config = BACKEND.normalize_optimizer_config(
        {"optimizer": {"backend": "ax", "ax": {"initialization_budget": 3}}}
    )
    assert config["ax"]["min_observed_initialization_trials"] == 3
    assert config["ax"]["method"] == "fast"


@pytest.mark.parametrize(
    "optimizer",
    [
        None,
        [],
        {"backend": "Ax"},
        {"unknown": 1},
        {"backend": "legacy", "ax": {"method": "fast"}},
        {"backend": "ax", "ax": []},
        {"backend": "ax", "ax": {"method": "random_search"}},
        {"backend": "ax", "ax": {"initialization_budget": True}},
        {"backend": "ax", "ax": {"initialization_budget": 0}},
        {"backend": "ax", "ax": {"min_observed_initialization_trials": 7}},
        {"backend": "ax", "ax": {"generation_timeout_seconds": float("nan")}},
        {"backend": "ax", "ax": {"allow_completed_repeats": 1}},
        {"backend": "ax", "ax": {"typo": 1}},
    ],
)
def test_invalid_optimizer_is_rejected(optimizer):
    with pytest.raises(ValueError):
        BACKEND.normalize_optimizer_config({"optimizer": optimizer})


def test_ax_conflicting_flags_and_demo_are_rejected():
    cfg = {"optimizer": {"backend": "ax"}}
    for kwargs in ({"template": "bo_client_demo"}, {"enable_botorch_gp": True}):
        with pytest.raises(ValueError):
            BACKEND.normalize_optimizer_config(cfg, **kwargs)
    with pytest.raises(ValueError):
        BACKEND.normalize_optimizer_config({**cfg, "feature_flags": {"enable_botorch_gp": True}})


def test_ax_state_is_distinct_from_payload_and_legacy_state():
    state = {"schema_version": "0.4.0", "optimizer": {"backend": "ax", "format_version": 1}}
    RUNTIME.normalize_state_schema_version(state, state_path=Path("unused.json"))
    assert RUNTIME.state_schema_version(state) == "0.4.0"
    assert RUNTIME.payload_schema_version(state) == "0.3.0"
    assert RUNTIME.state_for_persist(state)["schema_version"] == "0.4.0"
    assert RUNTIME.payload_schema_version({"schema_version": "0.3.1"}) == "0.3.1"
    for bad in (
        {"schema_version": "0.4.0"},
        {**state, "schema_version": "0.3.0"},
        {**state, "optimizer": {"backend": "ax", "format_version": True}},
    ):
        with pytest.raises(ValueError):
            RUNTIME.normalize_state_schema_version(bad, state_path=Path("unused.json"))
    with pytest.raises(ValueError, match="Ax campaign"):
        BACKEND.assert_backend_matches_state(state, {"backend": "legacy"})
    with pytest.raises(ValueError, match="pending"):
        BACKEND.assert_backend_matches_state({"pending": [{}]}, {"backend": "ax"})


def test_ax_capabilities_do_not_silently_drop_conditions_constraints_or_types():
    objective = OBJECTIVES.normalize_objective_schema(
        {"primary_objective": {"name": "loss", "direction": "minimize"}}
    )
    params = SEARCH.normalize_search_space(
        {"parameters": [{"name": "x", "type": "float", "bounds": [0, 1]}]}
    )
    BACKEND.validate_ax_capabilities(params, objective, None)
    for constraints in ({"linear_inequalities": [{}]}, {"forbidden_combinations": [{}]}):
        with pytest.raises(ValueError):
            BACKEND.validate_ax_capabilities(params, objective, constraints)
    with pytest.raises(ValueError, match="conditional"):
        BACKEND.validate_ax_capabilities(
            [{**params[0], "when": {"switch": [True]}}], objective, None
        )
    with pytest.raises(ValueError, match="homogeneous"):
        BACKEND.validate_ax_capabilities(
            [{"name": "x", "type": "categorical", "choices": [1, "1"]}], objective, None
        )
    with pytest.raises(ValueError, match="lexicographic"):
        BACKEND.validate_ax_capabilities(
            params, {**objective, "scalarization": {"policy": "lexicographic"}}, None
        )


def test_parameter_aliases_and_types_round_trip():
    params = SEARCH.normalize_search_space(
        {
            "parameters": [
                {"name": "learning/rate", "type": "float", "bounds": [0.001, 0.1], "scale": "log"},
                {"name": "flag", "type": "bool"},
                {"name": "batch", "type": "int", "bounds": [2, 8]},
                {"name": "solver", "type": "categorical", "choices": ["a", "b"]},
            ]
        }
    )
    compiled = AX._parameters(params)
    assert AX._encode(
        {"learning/rate": 0.01, "flag": True, "batch": 4, "solver": "a"}, compiled
    ) == {"p0": 0.01, "p1": True, "p2": 4, "p3": "a"}
    for values in (
        {"learning/rate": 0.01, "flag": 1, "batch": 4, "solver": "a"},
        {"learning/rate": 0.5, "flag": True, "batch": 4, "solver": "a"},
    ):
        with pytest.raises(ValueError):
            AX._encode(values, compiled)


def test_snapshot_preparation_never_commits_canonical_state(tmp_path, monkeypatch):
    from types import SimpleNamespace

    state = {
        "schema_version": "0.3.0",
        "meta": {"seed": 17},
        "observations": [],
        "pending": [],
        "next_trial_id": 1,
        "best": None,
    }
    original = copy.deepcopy(state)
    paths = RUNTIME.resolve_runtime_paths(tmp_path, {})
    objective = OBJECTIVES.normalize_objective_schema(
        {"primary_objective": {"name": "loss", "direction": "minimize"}}
    )
    params = SEARCH.normalize_search_space(
        {"parameters": [{"name": "x", "type": "float", "bounds": [0, 1]}]}
    )
    config = {"optimizer": {"backend": "ax"}}
    optimizer = BACKEND.normalize_optimizer_config(config)

    def fake_run(*args, **kwargs):
        return SimpleNamespace(
            returncode=0,
            stdout=json.dumps(
                {
                    "ok": True,
                    "result": {
                        "snapshot": {"fake": True},
                        "mapping": {"1": 0},
                        "signatures": {},
                        "candidates": [
                            {"params": {"p0": 0.2}, "ax_trial_index": 0, "generation_node": "Sobol"}
                        ],
                        "versions": BACKEND.dependency_versions(),
                        "attempts": 1,
                    },
                }
            ),
        )

    monkeypatch.setattr(AX.subprocess, "run", fake_run)
    plan = AX.prepare_batch(tmp_path, paths, state, config, params, objective, None, 1, optimizer)
    assert plan[0][0] == {"x": 0.2}
    assert state["schema_version"] == "0.4.0"
    assert not paths["state_file"].exists()
    assert original["pending"] == state["pending"] == []
    assert original["next_trial_id"] == state["next_trial_id"] == 1
    snapshot = AX.inspect_snapshot(tmp_path, paths, state)
    assert snapshot["generation"] == 1
    selected = tmp_path / state["optimizer"]["snapshot"]["path"]
    selected.write_text("{}")
    with pytest.raises(ValueError, match="digest"):
        AX.inspect_snapshot(tmp_path, paths, state)


@pytest.mark.parametrize("variant", ["bo_client", "bo_client_full", "bo_client_demo"])
def test_invalid_optimizer_preflight_creates_no_campaign_artifacts(tmp_path, variant):
    project = tmp_path / "controller"
    subprocess.run(
        [
            sys.executable,
            str(ROOT / "templates/_shared/vendor_copy.py"),
            str(ROOT / "templates" / variant),
            str(project),
        ],
        check=True,
        capture_output=True,
    )
    config = json.loads((project / "bo_config.json").read_text())
    config["optimizer"] = {"backend": "typo"}
    (project / "bo_config.json").write_text(json.dumps(config))
    out = subprocess.run(
        [sys.executable, "run_bo.py", "suggest", "--json-only"],
        cwd=project,
        text=True,
        capture_output=True,
    )
    assert out.returncode != 0
    assert "optimizer.backend" in out.stderr
    assert not (project / "state/bo_state.json").exists()
    assert not (project / "state/trials").exists()


def test_shared_optimizer_modules_do_not_import_optional_stack():
    source = f"import sys; sys.path.insert(0, {str(ROOT / 'templates/_shared')!r}); import optimizer_ax; assert not any(x in sys.modules for x in ('ax', 'torch', 'numpy', 'botorch'))"
    subprocess.run([sys.executable, "-S", "-c", source], check=True)


def test_finite_capacity_preserves_repeat_policy_and_counts_unique_parameterizations():
    parameters = [
        {"name": "p0", "parameter_type": "bool", "values": [False, True]},
        {"name": "p1", "parameter_type": "int", "bounds": [2, 3]},
    ]
    records = [
        {"status": "ok", "params": {"p0": False, "p1": 2}},
        {"status": "failed", "params": {"p0": False, "p1": 2}},
        {"status": "pending", "params": {"p0": True, "p1": 2}},
        {"status": "killed", "params": {"p0": False, "p1": 3}},
    ]
    AX._check_finite_capacity(parameters, records, 1, allow_completed_repeats=False)
    with pytest.raises(ValueError, match="1 available unique points"):
        AX._check_finite_capacity(parameters, records, 2, allow_completed_repeats=False)
    AX._check_finite_capacity(parameters, records, 3, allow_completed_repeats=True)
    with pytest.raises(ValueError, match="3 available unique points"):
        AX._check_finite_capacity(parameters, records, 4, allow_completed_repeats=True)
    AX._check_finite_capacity(parameters, records, 0, allow_completed_repeats=False)
    continuous = [{"name": "p0", "parameter_type": "float", "bounds": [0, 1]}]
    AX._check_finite_capacity(continuous, [], 100, allow_completed_repeats=False)
