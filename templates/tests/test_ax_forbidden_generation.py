"""Generation-only pruning preserves exact public typed/conditional feasibility."""

from __future__ import annotations

import json

import pytest
from test_ax_search_spaces import AX, codec


def generated(codec, raw):
    encoded = AX.encode(codec, raw)
    return all(
        parameter["name"] not in encoded
        or "values" not in parameter
        or AX.key(encoded[parameter["name"]]) in {AX.key(value) for value in parameter["values"]}
        for parameter in codec.get("generation_parameters", codec["parameters"])
    )


def assert_exact(parameters, rules):
    constrained = codec(parameters, rules)
    unconstrained = codec(parameters)
    for point in AX.finite_points(unconstrained):
        raw = json.loads(point)
        assert generated(constrained, raw) == AX.feasible(constrained, raw)["feasible"]
        assert AX.key(AX.decode(constrained, AX.encode(constrained, raw))) == AX.key(raw)
    return constrained


def test_branch_activation_eliminates_forbidden_false_without_changing_public_codec():
    parameters = [
        {"name": "kind", "type": "categorical", "choices": [1, 1.0, "1"]},
        {"name": "flag", "type": "bool", "when": {"kind": 1}},
        {"name": "leaf", "type": "int", "bounds": [3, 3], "when": {"flag": True}},
        {"name": "other", "type": "bool"},
    ]
    mapping = assert_exact(
        parameters, {"forbidden_combinations": [{"when": {"kind": 1, "flag": False}}]}
    )
    original = next(p for p in mapping["parameters"] if p.get("raw_name") == "flag")
    pruned = next(p for p in mapping["generation_parameters"] if p.get("raw_name") == "flag")
    assert original["values"] == [False, True]
    assert pruned["values"] == [True]
    assert original["dependents"] == pruned["dependents"]


def test_typed_categorical_token_positions_are_not_renumbered_after_pruning():
    mapping = assert_exact(
        [
            {"name": "gate", "type": "bool"},
            {
                "name": "choice",
                "type": "categorical",
                "choices": [1, 1.0, "1"],
                "when": {"gate": True},
            },
        ],
        {"forbidden_combinations": [{"when": {"gate": True, "choice": 1.0}}]},
    )
    pruned = next(p for p in mapping["generation_parameters"] if p.get("raw_name") == "choice")
    assert pruned["values"] == ["c0", "c2"]
    assert AX.encode(mapping, {"gate": True, "choice": "1"})["p1"] == "c2"


def test_nested_ancestors_and_multiple_allowed_values_prove_the_entire_rule():
    assert_exact(
        [
            {"name": "mode", "type": "categorical", "choices": [1, 1.0, "1"]},
            {"name": "gate", "type": "bool", "when": {"mode": 1}},
            {
                "name": "choice",
                "type": "categorical",
                "choices": ["a", "b", "c"],
                "when": {"gate": True},
            },
        ],
        {
            "forbidden_combinations": [
                {"when": {"mode": [1, "1"], "gate": True, "choice": ["b", "c"]}}
            ]
        },
    )


@pytest.mark.parametrize("mode", [1.0, "1"])
def test_a_different_typed_ancestor_does_not_prune_feasible_points(mode):
    mapping = assert_exact(
        [
            {"name": "mode", "type": "categorical", "choices": [1, 1.0, "1"]},
            {"name": "flag", "type": "bool", "when": {"mode": 1}},
        ],
        {"forbidden_combinations": [{"when": {"mode": mode, "flag": False}}]},
    )
    assert "generation_parameters" not in mapping


def test_a_sibling_condition_keeps_post_filtering_instead_of_narrowing_a_whole_branch():
    mapping = codec(
        [{"name": "a", "type": "bool"}, {"name": "b", "type": "bool"}],
        {"forbidden_combinations": [{"when": {"a": False, "b": False}}]},
    )
    assert "generation_parameters" not in mapping
    assert generated(mapping, {"a": False, "b": True})
    assert not AX.feasible(mapping, {"a": False, "b": False})["feasible"]


def test_child_owning_values_and_empty_domains_keep_bounded_post_filtering():
    mapping = codec(
        [
            {"name": "flag", "type": "bool"},
            {"name": "leaf", "type": "int", "bounds": [3, 3], "when": {"flag": False}},
        ],
        {"forbidden_combinations": [{"when": {"flag": False}}]},
    )
    assert "generation_parameters" not in mapping
    empty = codec(
        [{"name": "flag", "type": "bool"}],
        {"forbidden_combinations": [{"when": {"flag": [False, True]}}]},
    )
    assert "generation_parameters" not in empty
    assert AX.finite_points(empty) == set()


def test_generation_pruning_changes_the_fingerprint_and_rejects_implicit_continuation(
    tmp_path, monkeypatch
):
    from test_ax_measurements import load

    adapter = load("optimizer_ax")
    parameters = adapter._SPACE.SPACE.normalize_search_space(
        {"parameters": [{"name": "flag", "type": "bool"}]}
    )
    rules = adapter._CONSTRAINTS.normalize_constraints(
        {"forbidden_combinations": [{"when": {"flag": False}}]}, parameters
    )
    objectives = adapter._OBJECTIVES.normalize_objective_schema(
        {"primary_objective": {"name": "loss", "direction": "minimize"}}, contract_version=2
    )
    optimizer = adapter._BACKEND.normalize_optimizer_config(
        {"optimizer": {"backend": "ax", "ax": {"contract_version": 2}}}
    )
    state = {
        "meta": {"seed": 41},
        "schema_version": "0.5.0",
        "observations": [],
        "pending": [],
    }
    with monkeypatch.context() as old:
        old.setattr(adapter._SPACE, "_generation_choices", lambda *args: None)
        old_codec, old_fingerprint = adapter.configuration_v2(
            parameters, objectives, rules, optimizer["ax"], state
        )
    new_codec, new_fingerprint = adapter.configuration_v2(
        parameters, objectives, rules, optimizer["ax"], state
    )
    assert "generation_parameters" not in old_codec
    assert "generation_parameters" in new_codec
    assert old_fingerprint != new_fingerprint
    state["optimizer"] = {"backend": "ax", "format_version": 2, "fingerprint": old_fingerprint}
    before = json.loads(json.dumps(state))
    with pytest.raises(ValueError, match="explicit rebuild/new campaign"):
        adapter.validate_v2_context(tmp_path, {}, state, parameters, objectives, rules, optimizer)
    assert state == before
