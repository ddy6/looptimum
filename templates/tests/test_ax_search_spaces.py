"""Typed, conditional, finite-feasible and rejection contracts without Ax imports."""

from __future__ import annotations

import importlib.util
import json
import os
import shutil
from pathlib import Path

import pytest

SHARED = Path(__file__).resolve().parents[1] / "_shared"


def load(name):
    spec = importlib.util.spec_from_file_location(f"ax_spaces_test_{name}", SHARED / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


AX = load("ax_space")
SPACE = load("search_space")
CONSTRAINTS = load("constraints")
AVAILABLE = importlib.util.find_spec("ax") is not None
if os.environ.get("LOOPTIMUM_REQUIRE_AX_TESTS") == "1" and not AVAILABLE:
    raise RuntimeError("Required Ax search-space lane did not install the Ax extra")


@pytest.mark.skipif(not AVAILABLE, reason="optional Ax stack is not installed")
@pytest.mark.parametrize("variant", ["bo_client", "bo_client_full"])
@pytest.mark.parametrize("seed", [17, 41])
def test_real_typed_tree_raw_linear_forbidden_and_seeded_model_restore(tmp_path, variant, seed):
    from test_ax_integration import campaign, invoke, state

    project = campaign(tmp_path, variant)
    settings = json.loads((project / "bo_config.json").read_text())
    settings["seed"] = seed
    settings["optimizer"]["ax"].update(contract_version=2)
    (project / "bo_config.json").write_text(json.dumps(settings))
    parameters = [
        {"name": "kind + quoted", "type": "categorical", "choices": [1, 1.0, "1"]},
        {"name": "flag", "type": "bool", "when": {"kind + quoted": 1}},
        {"name": "leaf", "type": "int", "bounds": [3, 3], "when": {"flag": True}},
        {"name": "x", "type": "float", "bounds": [0, 1]},
        {"name": "y", "type": "float", "bounds": [0, 1]},
        {"name": "count", "type": "int", "bounds": [1, 3]},
    ]
    rules = {
        "linear_inequalities": [
            {
                "operator": "<=",
                "rhs": 1.6,
                "terms": [
                    {"param": "x", "coefficient": 1},
                    {"param": "y", "coefficient": 1},
                    {"param": "count", "coefficient": 0.1},
                ],
            }
        ],
        "forbidden_combinations": [{"when": {"kind + quoted": 1, "flag": False}}],
    }
    (project / "parameter_space.json").write_text(json.dumps({"parameters": parameters}))
    (project / "constraints.json").write_text(json.dumps(rules))
    c = codec(parameters, rules)
    assert next(p for p in c["generation_parameters"] if p.get("raw_name") == "flag")["values"] == [
        True
    ]
    for step in range(4):
        suggestion = json.loads(invoke(project, "suggest", "--json-only").stdout)
        raw = suggestion["params"]
        assert AX.feasible(c, raw)["feasible"]
        assert AX.key(AX.decode(c, AX.encode(c, raw))) == AX.key(raw)
        if type(raw["kind + quoted"]) is int:
            assert raw["flag"] is True and raw["leaf"] == 3
        else:
            assert "flag" not in raw and "leaf" not in raw
        payload = {
            "trial_id": suggestion["trial_id"],
            "params": raw,
            "status": "ok",
            "objectives": {"loss": (raw["x"] - 0.3) ** 2 + (raw["y"] - 0.6) ** 2},
        }
        (project / "result.json").write_text(json.dumps(payload))
        invoke(
            project,
            "ingest",
            "--results-file",
            "result.json",
            "--lease-token",
            suggestion["lease_token"],
            lean=True,
        )
    decisions = [
        json.loads(line)
        for line in (project / "state/acquisition_log.jsonl").read_text().splitlines()
    ]
    assert decisions[-1]["decision"]["generation_node"] == "MBM"
    assert all(
        "forbidden_combinations[0]" not in row["decision"]["constraint_status"]["reject_counts"]
        for row in decisions
    )
    twin = tmp_path / "restored"
    shutil.copytree(project, twin)
    a = json.loads(invoke(project, "suggest", "--json-only").stdout)
    b = json.loads(invoke(twin, "suggest", "--json-only").stdout)
    assert type(a["params"]["kind + quoted"]) is type(b["params"]["kind + quoted"])
    assert AX.key({k: v for k, v in a["params"].items() if k not in ("x", "y")}) == AX.key(
        {k: v for k, v in b["params"].items() if k not in ("x", "y")}
    )
    for name in ("x", "y"):
        assert a["params"][name] == pytest.approx(b["params"][name], abs=1e-7, rel=0)
    assert state(project)["optimizer"]["format_version"] == 2


def codec(parameters, constraints=None):
    params = SPACE.normalize_search_space({"parameters": parameters})
    normalized = CONSTRAINTS.normalize_constraints(constraints, params) if constraints else None
    return AX.build_codec(params, normalized)


def test_mixed_choices_are_a_typed_bijection_without_expression_names():
    name = 'x + dangerous("m0")'
    c = codec([{"name": name, "type": "categorical", "choices": [1, 1.0, "1"]}])
    tokens = []
    for value in (1, 1.0, "1"):
        raw = {name: value}
        encoded = AX.encode(c, raw)
        decoded = AX.decode(c, encoded)
        assert type(decoded[name]) is type(value)
        assert AX.key(decoded) == AX.key(raw)
        tokens.append(encoded["p0"])
    assert len(set(tokens)) == 3
    assert c["parameters"][0]["name"] == "p0"
    with pytest.raises(ValueError):
        codec([{"name": "x", "type": "categorical", "choices": [True, 1]}])


def test_nested_tree_omits_inactive_fields_and_internal_root():
    c = codec(
        [
            {"name": "mode", "type": "categorical", "choices": [1, "1"]},
            {"name": "x", "type": "float", "bounds": [0, 1]},
            {"name": "flag", "type": "bool", "when": {"mode": 1}},
            {"name": "leaf", "type": "int", "bounds": [7, 7], "when": {"flag": True}},
        ]
    )
    for raw in (
        {"mode": 1, "x": 0.2, "flag": True, "leaf": 7},
        {"mode": 1, "x": 0.2, "flag": False},
        {"mode": "1", "x": 0.2},
    ):
        assert AX.decode(c, AX.encode(c, raw)) == raw
        assert "root" not in AX.decode(c, AX.encode(c, raw))
    for raw in (
        {"mode": "1", "x": 0.2, "leaf": 7},
        {"mode": 1, "x": 0.2},
        {"mode": "1", "x": 0.2, "unknown": 4},
    ):
        with pytest.raises(ValueError, match="active"):
            AX.encode(c, raw)


def test_only_exact_finite_tree_shapes_are_accepted():
    base = [{"name": "a", "type": "bool"}, {"name": "b", "type": "bool"}]
    for when in ({"a": [False, True]}, {"a": True, "b": True}):
        with pytest.raises(ValueError, match="tree|branch|DAG"):
            codec([*base, {"name": "child", "type": "int", "bounds": [1, 3], "when": when}])
    with pytest.raises(ValueError, match="finite|float controller"):
        codec(
            [
                {"name": "a", "type": "float", "bounds": [0, 1]},
                {"name": "child", "type": "bool", "when": {"a": 0.5}},
            ]
        )


def test_finite_point_limit_is_enforced_after_the_last_leaf():
    c = codec([{"name": "kind", "type": "categorical", "choices": ["a", "b", "c"]}])
    assert AX.finite_points(c, limit=2) is None
    assert len(AX.finite_points(c, limit=3)) == 3


def test_raw_linear_rules_keep_fixed_terms_and_use_safe_aliases():
    c = codec(
        [
            {"name": "rate + expression", "type": "float", "bounds": [0, 1]},
            {"name": "fixed", "type": "float", "bounds": [2, 2]},
            {"name": "count", "type": "int", "bounds": [1, 3]},
        ],
        {
            "linear_inequalities": [
                {
                    "operator": ">=",
                    "rhs": 5,
                    "terms": [
                        {"param": "rate + expression", "coefficient": 2},
                        {"param": "fixed", "coefficient": 2},
                        {"param": "count", "coefficient": 1},
                    ],
                }
            ]
        },
    )
    expression = c["parameter_constraints"][0]
    assert "rate" not in expression and ">= 1.0" in expression and "p0" in expression
    assert AX.feasible(c, {"rate + expression": 0, "fixed": 2, "count": 1})["feasible"]
    with pytest.raises(ValueError, match="log-scaled"):
        codec(
            [{"name": "x", "type": "float", "bounds": [0.01, 1], "scale": "log"}],
            {
                "linear_inequalities": [
                    {"operator": "<=", "rhs": 0.5, "terms": [{"param": "x", "coefficient": 1}]}
                ]
            },
        )


def test_impossible_fixed_rule_fails_before_generation_even_with_zero_terms():
    with pytest.raises(ValueError, match="fixed linear"):
        codec(
            [
                {"name": "fixed", "type": "float", "bounds": [2, 2]},
                {"name": "x", "type": "float", "bounds": [0, 1]},
            ],
            {
                "linear_inequalities": [
                    {
                        "operator": "<=",
                        "rhs": 1,
                        "terms": [
                            {"param": "fixed", "coefficient": 1},
                            {"param": "x", "coefficient": 0},
                        ],
                    }
                ]
            },
        )


def test_finite_capacity_counts_feasible_active_points_and_pending_repeats():
    c = codec(
        [
            {"name": "mode", "type": "categorical", "choices": [1, "1"]},
            {"name": "x", "type": "int", "bounds": [1, 2], "when": {"mode": 1}},
        ],
        {"forbidden_combinations": [{"when": {"mode": 1, "x": 2}}]},
    )
    points = AX.finite_points(c)
    assert points == {AX.key({"mode": 1, "x": 1}), AX.key({"mode": "1"})}
    terminal = {"params": {"mode": 1, "x": 1}, "status": "ok"}
    AX.check_capacity(c, [terminal], 2, allow_completed_repeats=True)
    with pytest.raises(ValueError, match="1 available"):
        AX.check_capacity(c, [terminal], 2, allow_completed_repeats=False)
    with pytest.raises(ValueError, match="1 available"):
        AX.check_capacity(c, [{**terminal, "status": "pending"}], 2, allow_completed_repeats=True)


def test_capacity_enumeration_is_bounded_and_types_are_not_silently_cast():
    c = codec([{"name": "x", "type": "int", "bounds": [1, 1_000_000]}])
    assert AX.finite_points(c, limit=10) is None
    with pytest.raises(ValueError):
        AX.decode(c, {"p0": 1.0})
    with pytest.raises(ValueError):
        AX.encode(c, {"x": True})
    floating = codec([{"name": "x", "type": "float", "bounds": [1, 2]}])
    assert type(AX.decode(floating, {"p0": 1})["x"]) is float
