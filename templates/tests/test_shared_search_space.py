from __future__ import annotations

import importlib.util
import json
import random
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SEARCH_SPACE_MODULE = REPO_ROOT / "templates" / "_shared" / "search_space.py"


def _load_search_space_module():
    spec = importlib.util.spec_from_file_location(
        "looptimum_shared_search_space_test", SEARCH_SPACE_MODULE
    )
    if spec is None or spec.loader is None:
        raise ImportError(f"Unable to load shared module from {SEARCH_SPACE_MODULE}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


SEARCH_SPACE = _load_search_space_module()


def test_normalize_search_space_preserves_numeric_template_descriptors() -> None:
    cfg = json.loads(
        (REPO_ROOT / "templates" / "bo_client" / "parameter_space.json").read_text(encoding="utf-8")
    )

    assert SEARCH_SPACE.normalize_search_space(cfg) == [
        {
            "name": "x1",
            "type": "float",
            "bounds": [0.0, 1.0],
            "scale": "linear",
            "encoding": "scalar",
            "encoded_size": 1,
            "description": "First controllable factor",
        },
        {
            "name": "x2",
            "type": "float",
            "bounds": [0.0, 1.0],
            "scale": "linear",
            "encoding": "scalar",
            "encoded_size": 1,
            "description": "Second controllable factor",
        },
    ]


def test_normalize_search_space_accepts_mixed_parameter_descriptors() -> None:
    cfg = {
        "parameters": [
            {"name": "lr", "type": "float", "bounds": [0.0001, 0.1], "scale": "log"},
            {"name": "layers", "type": "int", "bounds": [1, 8]},
            {"name": "use_bn", "type": "bool", "description": "Enable batch norm"},
            {"name": "optimizer", "type": "categorical", "choices": ["adam", "sgd", 2]},
        ]
    }

    assert SEARCH_SPACE.normalize_search_space(cfg) == [
        {
            "name": "lr",
            "type": "float",
            "bounds": [0.0001, 0.1],
            "scale": "log",
            "encoding": "scalar",
            "encoded_size": 1,
        },
        {
            "name": "layers",
            "type": "int",
            "bounds": [1, 8],
            "scale": "linear",
            "encoding": "scalar",
            "encoded_size": 1,
        },
        {
            "name": "use_bn",
            "type": "bool",
            "choices": [False, True],
            "encoding": "binary",
            "encoded_size": 1,
            "description": "Enable batch norm",
        },
        {
            "name": "optimizer",
            "type": "categorical",
            "choices": ["adam", "sgd", 2],
            "encoding": "one_hot",
            "encoded_size": 3,
        },
    ]


@pytest.mark.parametrize(
    ("cfg", "pattern"),
    [
        (
            {"parameters": [{"name": "optimizer", "type": "categorical"}]},
            "must define non-empty 'choices'",
        ),
        (
            {"parameters": [{"name": "lr", "type": "float", "bounds": [0.0, 1.0], "scale": "log"}]},
            "strictly positive bounds for log scale",
        ),
        (
            {"parameters": [{"name": "flag", "type": "bool", "bounds": [0, 1]}]},
            "must not define 'bounds'",
        ),
        (
            {
                "parameters": [
                    {"name": "x", "type": "float", "bounds": [0.0, 1.0]},
                    {"name": "x", "type": "int", "bounds": [1, 2]},
                ]
            },
            "duplicate name 'x'",
        ),
    ],
)
def test_normalize_search_space_rejects_invalid_semantics(cfg: dict, pattern: str) -> None:
    with pytest.raises(ValueError, match=pattern):
        SEARCH_SPACE.normalize_search_space(cfg)


def test_random_sampling_supports_mixed_parameter_types_and_preserves_raw_values() -> None:
    params = SEARCH_SPACE.normalize_search_space(
        {
            "parameters": [
                {"name": "epochs", "type": "int", "bounds": [1, 64], "scale": "log"},
                {"name": "lr", "type": "float", "bounds": [0.001, 0.1], "scale": "log"},
                {"name": "use_bn", "type": "bool"},
                {"name": "optimizer", "type": "categorical", "choices": ["adam", "sgd"]},
            ]
        }
    )

    first = SEARCH_SPACE.sample_random_point(random.Random(17), params)
    second = SEARCH_SPACE.sample_random_point(random.Random(17), params)

    assert first == second
    assert 1 <= first["epochs"] <= 64
    assert isinstance(first["epochs"], int)
    assert 0.001 <= first["lr"] <= 0.1
    assert isinstance(first["use_bn"], bool)
    assert first["optimizer"] in {"adam", "sgd"}


def test_surrogate_numeric_only_capability_gap_flags_deferred_modeling_shapes() -> None:
    linear_numeric = SEARCH_SPACE.normalize_search_space(
        {"parameters": [{"name": "x", "type": "float", "bounds": [0.0, 1.0]}]}
    )
    assert SEARCH_SPACE.surrogate_numeric_only_capability_gap(linear_numeric) is None

    mixed = SEARCH_SPACE.normalize_search_space(
        {
            "parameters": [
                {"name": "lr", "type": "float", "bounds": [0.001, 0.1], "scale": "log"},
                {"name": "optimizer", "type": "categorical", "choices": ["adam", "sgd"]},
            ]
        }
    )

    assert SEARCH_SPACE.surrogate_numeric_only_capability_gap(mixed) == {
        "fallback_reason": "search_space_requires_workstream1_model_encoding",
        "fallback_param": "lr",
        "fallback_param_type": "float",
        "fallback_param_scale": "log",
    }
