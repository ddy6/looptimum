from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
CONSTRAINTS_MODULE = REPO_ROOT / "templates" / "_shared" / "constraints.py"
SEARCH_SPACE_MODULE = REPO_ROOT / "templates" / "_shared" / "search_space.py"


def _load_module(module_path: Path, module_name: str):
    spec = importlib.util.spec_from_file_location(module_name, module_path)
    if spec is None or spec.loader is None:
        raise ImportError(f"Unable to load shared module from {module_path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


CONSTRAINTS = _load_module(CONSTRAINTS_MODULE, "looptimum_shared_constraints_test")
SEARCH_SPACE = _load_module(
    SEARCH_SPACE_MODULE, "looptimum_shared_search_space_for_constraints_test"
)


def test_normalize_constraints_accepts_all_workstream3_rule_types() -> None:
    params = SEARCH_SPACE.normalize_search_space(
        {
            "parameters": [
                {"name": "x1", "type": "float", "bounds": [0.0, 1.0]},
                {"name": "x2", "type": "int", "bounds": [0, 10]},
                {"name": "optimizer", "type": "categorical", "choices": ["adam", "sgd"]},
                {"name": "use_bn", "type": "bool"},
            ]
        }
    )

    assert CONSTRAINTS.normalize_constraints(
        {
            "bound_tightening": [{"param": "x1", "min": 0.2, "max": 0.8}],
            "linear_inequalities": [
                {
                    "terms": [
                        {"param": "x1", "coefficient": 1.5},
                        {"param": "x2", "coefficient": -1.0},
                    ],
                    "operator": "<=",
                    "rhs": 2.0,
                }
            ],
            "forbidden_combinations": [{"when": {"optimizer": "sgd", "use_bn": True}}],
        },
        params,
    ) == {
        "bound_tightening": [
            {
                "rule_id": "bound_tightening[0]",
                "param": "x1",
                "min": 0.2,
                "max": 0.8,
            }
        ],
        "linear_inequalities": [
            {
                "rule_id": "linear_inequalities[0]",
                "terms": [
                    {"param": "x1", "coefficient": 1.5},
                    {"param": "x2", "coefficient": -1.0},
                ],
                "operator": "<=",
                "rhs": 2.0,
            }
        ],
        "forbidden_combinations": [
            {
                "rule_id": "forbidden_combinations[0]",
                "when": {"optimizer": ["sgd"], "use_bn": [True]},
            }
        ],
    }


@pytest.mark.parametrize(
    ("constraints_cfg", "pattern"),
    [
        (
            {"bound_tightening": [{"param": "missing", "min": 0.1}]},
            "references unknown parameter 'missing'",
        ),
        (
            {"bound_tightening": [{"param": "flag", "min": 0.0}]},
            "must reference a numeric parameter",
        ),
        (
            {
                "bound_tightening": [
                    {"param": "x", "min": 0.7},
                    {"param": "x", "max": 0.6},
                ]
            },
            "collapses parameter 'x'",
        ),
        (
            {
                "linear_inequalities": [
                    {
                        "terms": [
                            {"param": "x", "coefficient": 1.0},
                            {"param": "x", "coefficient": -1.0},
                        ],
                        "operator": "<=",
                        "rhs": 0.0,
                    }
                ]
            },
            "must not repeat parameter 'x'",
        ),
        (
            {
                "linear_inequalities": [
                    {
                        "terms": [{"param": "flag", "coefficient": 1.0}],
                        "operator": "<=",
                        "rhs": 1.0,
                    }
                ]
            },
            "must reference a raw numeric parameter",
        ),
        (
            {"forbidden_combinations": [{"when": {"optimizer": "rmsprop"}}]},
            "must match one of the configured categorical choices",
        ),
    ],
)
def test_normalize_constraints_rejects_invalid_semantics(
    constraints_cfg: dict, pattern: str
) -> None:
    params = SEARCH_SPACE.normalize_search_space(
        {
            "parameters": [
                {"name": "x", "type": "float", "bounds": [0.0, 1.0]},
                {"name": "flag", "type": "bool"},
                {"name": "optimizer", "type": "categorical", "choices": ["adam", "sgd"]},
            ]
        }
    )

    with pytest.raises(ValueError, match=pattern):
        CONSTRAINTS.normalize_constraints(constraints_cfg, params)


def test_evaluate_constraints_reports_deterministic_violations_and_counts() -> None:
    params = SEARCH_SPACE.normalize_search_space(
        {
            "parameters": [
                {"name": "x1", "type": "float", "bounds": [0.0, 1.0]},
                {"name": "x2", "type": "int", "bounds": [0, 10]},
                {"name": "optimizer", "type": "categorical", "choices": ["adam", "sgd"]},
                {"name": "use_bn", "type": "bool"},
                {
                    "name": "momentum",
                    "type": "float",
                    "bounds": [0.0, 0.99],
                    "when": {"optimizer": "sgd"},
                },
            ]
        }
    )
    constraints = CONSTRAINTS.normalize_constraints(
        {
            "bound_tightening": [{"param": "momentum", "max": 0.8}],
            "linear_inequalities": [
                {
                    "terms": [
                        {"param": "x1", "coefficient": 1.0},
                        {"param": "x2", "coefficient": 1.0},
                    ],
                    "operator": "<=",
                    "rhs": 2.5,
                }
            ],
            "forbidden_combinations": [{"when": {"optimizer": "sgd", "use_bn": True}}],
        },
        params,
    )

    evaluation = CONSTRAINTS.evaluate_constraints(
        {"x1": 0.9, "x2": 3, "optimizer": "sgd", "use_bn": True, "momentum": 0.9},
        constraints,
    )

    assert evaluation == {
        "feasible": False,
        "violations": [
            {
                "rule_id": "bound_tightening[0]",
                "rule_type": "bound_tightening",
                "message": "Parameter 'momentum' value 0.9 exceeds maximum 0.8",
                "details": {"param": "momentum", "observed": 0.9, "maximum": 0.8},
            },
            {
                "rule_id": "linear_inequalities[0]",
                "rule_type": "linear_inequality",
                "message": "Linear constraint 3.9 <= 2.5 is not satisfied",
                "details": {
                    "operator": "<=",
                    "lhs": 3.9,
                    "rhs": 2.5,
                    "terms": [
                        {"param": "x1", "coefficient": 1.0, "observed": 0.9},
                        {"param": "x2", "coefficient": 1.0, "observed": 3.0},
                    ],
                },
            },
            {
                "rule_id": "forbidden_combinations[0]",
                "rule_type": "forbidden_combination",
                "message": "Forbidden parameter combination matched",
                "details": {"when": {"optimizer": ["sgd"], "use_bn": [True]}},
            },
        ],
        "reject_counts": {
            "bound_tightening[0]": 1,
            "linear_inequalities[0]": 1,
            "forbidden_combinations[0]": 1,
        },
    }
    assert CONSTRAINTS.accumulate_reject_counts(
        {"bound_tightening[0]": 2},
        evaluation,
    ) == {
        "bound_tightening[0]": 3,
        "linear_inequalities[0]": 1,
        "forbidden_combinations[0]": 1,
    }


def test_evaluate_constraints_treats_missing_conditional_values_as_not_applicable() -> None:
    params = SEARCH_SPACE.normalize_search_space(
        {
            "parameters": [
                {"name": "optimizer", "type": "categorical", "choices": ["adam", "sgd"]},
                {
                    "name": "momentum",
                    "type": "float",
                    "bounds": [0.0, 0.99],
                    "when": {"optimizer": "sgd"},
                },
            ]
        }
    )
    constraints = CONSTRAINTS.normalize_constraints(
        {
            "bound_tightening": [{"param": "momentum", "max": 0.8}],
            "forbidden_combinations": [{"when": {"optimizer": "sgd", "momentum": 0.9}}],
        },
        params,
    )

    evaluation = CONSTRAINTS.evaluate_constraints({"optimizer": "adam"}, constraints)

    assert evaluation == {
        "feasible": True,
        "violations": [],
        "reject_counts": {},
    }


def test_apply_bound_tightening_narrows_sampling_bounds_without_mutating_original() -> None:
    params = SEARCH_SPACE.normalize_search_space(
        {
            "parameters": [
                {"name": "x", "type": "float", "bounds": [0.0, 1.0]},
                {"name": "y", "type": "int", "bounds": [0, 10]},
                {"name": "flag", "type": "bool"},
            ]
        }
    )
    constraints = CONSTRAINTS.normalize_constraints(
        {
            "bound_tightening": [
                {"param": "x", "min": 0.2},
                {"param": "x", "max": 0.8},
                {"param": "y", "min": 3, "max": 5},
            ]
        },
        params,
    )

    tightened = CONSTRAINTS.apply_bound_tightening(params, constraints)

    assert params[0]["bounds"] == [0.0, 1.0]
    assert params[1]["bounds"] == [0, 10]
    assert tightened == [
        {
            "name": "x",
            "type": "float",
            "bounds": [0.2, 0.8],
            "scale": "linear",
            "encoding": "scalar",
            "encoded_size": 1,
        },
        {
            "name": "y",
            "type": "int",
            "bounds": [3, 5],
            "scale": "linear",
            "encoding": "scalar",
            "encoded_size": 1,
        },
        {
            "name": "flag",
            "type": "bool",
            "choices": [False, True],
            "encoding": "binary",
            "encoded_size": 1,
        },
    ]


def test_sample_feasible_candidates_tracks_attempts_and_reject_counts() -> None:
    constraints = {
        "bound_tightening": [],
        "linear_inequalities": [],
        "forbidden_combinations": [{"rule_id": "forbidden_combinations[0]", "when": {"x": [0]}}],
    }

    samples = iter([{"x": 0}, {"x": 0}, {"x": 1}, {"x": 1}])
    result = CONSTRAINTS.sample_feasible_candidates(
        lambda: next(samples),
        constraints,
        target_count=2,
        max_attempts=4,
    )

    assert result == {
        "candidates": [{"x": 1}, {"x": 1}],
        "attempts": 4,
        "infeasible_attempts": 2,
        "reject_counts": {"forbidden_combinations[0]": 2},
    }
    assert (
        CONSTRAINTS.format_reject_summary(result["reject_counts"]) == "forbidden_combinations[0]=2"
    )


def test_constraint_status_and_error_reason_capture_partial_and_total_rejects() -> None:
    partial = CONSTRAINTS.build_constraint_status(
        {
            "bound_tightening": [],
            "linear_inequalities": [],
            "forbidden_combinations": [],
        },
        {
            "candidates": [{"x": 1}],
            "attempts": 4,
            "infeasible_attempts": 3,
            "reject_counts": {"linear_inequalities[0]": 3},
        },
        phase="candidate-pool",
        requested=3,
    )
    assert partial == {
        "enabled": True,
        "phase": "candidate-pool",
        "requested": 3,
        "accepted": 1,
        "attempted": 4,
        "rejected": 3,
        "feasible_ratio": 0.25,
        "reject_counts": {"linear_inequalities[0]": 3},
        "warning": (
            "constraints reduced candidate-pool feasible candidates to 1/3 "
            "(dominant rejects: linear_inequalities[0]=3)"
        ),
    }

    total = CONSTRAINTS.build_constraint_status(
        {
            "bound_tightening": [],
            "linear_inequalities": [],
            "forbidden_combinations": [],
        },
        {
            "candidates": [],
            "attempts": 5,
            "infeasible_attempts": 5,
            "reject_counts": {"forbidden_combinations[0]": 5},
        },
        phase="initial-random",
        requested=1,
    )
    assert CONSTRAINTS.build_constraint_error_reason(total) == (
        "constraints eliminated all 5 initial-random attempts "
        "(dominant rejects: forbidden_combinations[0]=5)"
    )
