from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
OBJECTIVES_MODULE = REPO_ROOT / "templates" / "_shared" / "objectives.py"


def _load_module(module_path: Path, module_name: str):
    spec = importlib.util.spec_from_file_location(module_name, module_path)
    if spec is None or spec.loader is None:
        raise ImportError(f"Unable to load shared module from {module_path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


OBJECTIVES = _load_module(OBJECTIVES_MODULE, "looptimum_shared_objectives_test")


def test_normalize_objective_schema_preserves_single_objective_defaults() -> None:
    assert OBJECTIVES.normalize_objective_schema(
        {
            "primary_objective": {
                "name": "loss",
                "direction": "minimize",
                "tolerance": 0.0,
                "failure_handling": "record_and_continue",
            },
            "secondary_objectives": [],
        }
    ) == {
        "primary_objective": {
            "name": "loss",
            "direction": "minimize",
            "tolerance": 0.0,
            "failure_handling": "record_and_continue",
        },
        "secondary_objectives": [],
        "objectives": [
            {
                "name": "loss",
                "direction": "minimize",
                "tolerance": 0.0,
                "failure_handling": "record_and_continue",
            }
        ],
        "objective_names": ["loss"],
        "scalarization": {"policy": "primary_only"},
    }


def test_normalize_objective_schema_accepts_weighted_sum_and_normalizes_weights() -> None:
    normalized = OBJECTIVES.normalize_objective_schema(
        {
            "primary_objective": {"name": "loss", "direction": "minimize"},
            "secondary_objectives": [{"name": "runtime", "direction": "minimize"}],
            "scalarization": {
                "policy": "weighted_sum",
                "weights": {"loss": 3.0, "runtime": 1.0},
            },
        }
    )

    assert normalized["objective_names"] == ["loss", "runtime"]
    assert normalized["scalarization"] == {
        "policy": "weighted_sum",
        "weights": {"loss": 0.75, "runtime": 0.25},
    }


def test_normalize_objective_schema_accepts_weighted_tchebycheff_reference_point() -> None:
    normalized = OBJECTIVES.normalize_objective_schema(
        {
            "primary_objective": {"name": "loss", "direction": "minimize"},
            "secondary_objectives": [{"name": "runtime", "direction": "minimize"}],
            "scalarization": {
                "policy": "weighted_tchebycheff",
                "weights": {"loss": 2.0, "runtime": 1.0},
                "reference_point": {"loss": 0.05, "runtime": 10.0},
            },
        }
    )

    assert normalized["scalarization"] == {
        "policy": "weighted_tchebycheff",
        "weights": {"loss": 2.0 / 3.0, "runtime": 1.0 / 3.0},
        "reference_point": {"loss": 0.05, "runtime": 10.0},
    }


@pytest.mark.parametrize(
    ("objective_cfg", "pattern"),
    [
        (
            {
                "primary_objective": {"name": "loss", "direction": "minimize"},
                "secondary_objectives": [{"name": "loss", "direction": "maximize"}],
            },
            "must be unique",
        ),
        (
            {
                "primary_objective": {"name": "loss", "direction": "down"},
            },
            "direction must be one of",
        ),
        (
            {
                "primary_objective": {"name": "loss", "direction": "minimize"},
                "secondary_objectives": [{"name": "runtime", "direction": "minimize"}],
                "scalarization": {
                    "policy": "weighted_sum",
                    "weights": {"loss": 1.0},
                },
            },
            "must match declared objective names exactly",
        ),
        (
            {
                "primary_objective": {"name": "loss", "direction": "minimize"},
                "secondary_objectives": [{"name": "runtime", "direction": "minimize"}],
                "scalarization": {
                    "policy": "lexicographic",
                    "weights": {"loss": 1.0, "runtime": 1.0},
                },
            },
            "only supported for weighted policies",
        ),
    ],
)
def test_normalize_objective_schema_rejects_invalid_semantics(
    objective_cfg: dict, pattern: str
) -> None:
    with pytest.raises(ValueError, match=pattern):
        OBJECTIVES.normalize_objective_schema(objective_cfg)
