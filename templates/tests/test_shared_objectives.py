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


def test_scalarize_objectives_weighted_sum_respects_direction() -> None:
    objective_cfg = OBJECTIVES.normalize_objective_schema(
        {
            "primary_objective": {"name": "loss", "direction": "minimize"},
            "secondary_objectives": [{"name": "throughput", "direction": "maximize"}],
            "scalarization": {
                "policy": "weighted_sum",
                "weights": {"loss": 1.0, "throughput": 1.0},
            },
        }
    )

    assert OBJECTIVES.scalarize_objectives(
        {"loss": 0.2, "throughput": 3.0},
        objective_cfg,
    ) == pytest.approx(-1.4)


def test_best_rank_key_uses_lexicographic_tie_breaks() -> None:
    objective_cfg = OBJECTIVES.normalize_objective_schema(
        {
            "primary_objective": {"name": "loss", "direction": "minimize"},
            "secondary_objectives": [{"name": "throughput", "direction": "maximize"}],
            "scalarization": {"policy": "lexicographic"},
        }
    )

    better = OBJECTIVES.best_rank_key(
        {"loss": 0.2, "throughput": 3.0},
        objective_cfg,
        trial_id=1,
    )
    worse = OBJECTIVES.best_rank_key(
        {"loss": 0.2, "throughput": 1.0},
        objective_cfg,
        trial_id=2,
    )
    assert better < worse


def test_build_best_record_includes_vector_and_policy_for_multi_objective() -> None:
    objective_cfg = OBJECTIVES.normalize_objective_schema(
        {
            "primary_objective": {"name": "loss", "direction": "minimize"},
            "secondary_objectives": [{"name": "throughput", "direction": "maximize"}],
            "scalarization": {
                "policy": "weighted_sum",
                "weights": {"loss": 1.0, "throughput": 1.0},
            },
        }
    )

    record = OBJECTIVES.build_best_record(
        {
            "trial_id": 7,
            "objectives": {"loss": 0.2, "throughput": 3.0},
        },
        objective_cfg,
        updated_at=12.5,
    )

    assert record == {
        "trial_id": 7,
        "objective_name": "scalarized",
        "objective_value": pytest.approx(-1.4),
        "updated_at": 12.5,
        "scalarization_policy": "weighted_sum",
        "objective_vector": {"loss": 0.2, "throughput": 3.0},
    }


def test_build_objective_metadata_keeps_primary_and_scalarized_values() -> None:
    objective_cfg = OBJECTIVES.normalize_objective_schema(
        {
            "primary_objective": {"name": "loss", "direction": "minimize"},
            "secondary_objectives": [{"name": "throughput", "direction": "maximize"}],
            "scalarization": {
                "policy": "weighted_sum",
                "weights": {"loss": 1.0, "throughput": 1.0},
            },
        }
    )

    metadata = OBJECTIVES.build_objective_metadata(
        {"loss": 0.2, "throughput": 3.0},
        objective_cfg,
    )

    assert metadata == {
        "objective_name": "loss",
        "objective_value": 0.2,
        "objective_vector": {"loss": 0.2, "throughput": 3.0},
        "scalarized_objective": pytest.approx(-1.4),
        "scalarization_policy": "weighted_sum",
    }


def test_pareto_front_records_filters_dominated_trials_and_sorts_deterministically() -> None:
    objective_cfg = OBJECTIVES.normalize_objective_schema(
        {
            "primary_objective": {"name": "loss", "direction": "minimize"},
            "secondary_objectives": [{"name": "throughput", "direction": "maximize"}],
            "scalarization": {
                "policy": "weighted_sum",
                "weights": {"loss": 1.0, "throughput": 1.0},
            },
        }
    )

    frontier = OBJECTIVES.pareto_front_records(
        [
            {"trial_id": 1, "objectives": {"loss": 0.4, "throughput": 1.0}},
            {"trial_id": 2, "objectives": {"loss": 0.3, "throughput": 2.0}},
            {"trial_id": 3, "objectives": {"loss": 0.2, "throughput": 1.0}},
            {"trial_id": 4, "objectives": {"loss": 0.25, "throughput": 0.9}},
        ],
        objective_cfg,
    )

    assert [row["trial_id"] for row in frontier] == [2, 3]


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
