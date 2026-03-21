from __future__ import annotations

import importlib.util
import json
import math
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


def test_normalize_search_space_accepts_conditional_descriptors_and_active_helpers() -> None:
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
                {
                    "name": "nesterov",
                    "type": "bool",
                    "when": {"optimizer": ["sgd"]},
                },
            ]
        }
    )

    assert params == [
        {
            "name": "optimizer",
            "type": "categorical",
            "choices": ["adam", "sgd"],
            "encoding": "one_hot",
            "encoded_size": 2,
        },
        {
            "name": "momentum",
            "type": "float",
            "bounds": [0.0, 0.99],
            "scale": "linear",
            "encoding": "scalar",
            "encoded_size": 1,
            "when": {"optimizer": ["sgd"]},
        },
        {
            "name": "nesterov",
            "type": "bool",
            "choices": [False, True],
            "encoding": "binary",
            "encoded_size": 1,
            "when": {"optimizer": ["sgd"]},
        },
    ]
    assert [
        param["name"] for param in SEARCH_SPACE.active_parameters(params, {"optimizer": "adam"})
    ] == ["optimizer"]
    assert [
        param["name"] for param in SEARCH_SPACE.active_parameters(params, {"optimizer": "sgd"})
    ] == [
        "optimizer",
        "momentum",
        "nesterov",
    ]
    assert SEARCH_SPACE.omit_inactive_params(
        {"optimizer": "adam", "momentum": 0.9, "nesterov": True}, params
    ) == {"optimizer": "adam"}
    assert SEARCH_SPACE.canonicalize_conditional_params(
        {"optimizer": "adam", "momentum": 0.9, "extra": "keep"}, params
    ) == {"optimizer": "adam", "extra": "keep"}


def test_conditional_sampling_omits_inactive_params_and_orders_dependencies() -> None:
    params = SEARCH_SPACE.normalize_search_space(
        {
            "parameters": [
                {
                    "name": "momentum",
                    "type": "float",
                    "bounds": [0.0, 0.99],
                    "when": {"gate": 1},
                },
                {"name": "gate", "type": "int", "bounds": [0, 1]},
                {"name": "x", "type": "float", "bounds": [0.0, 1.0]},
            ]
        }
    )

    inactive_point = SEARCH_SPACE.sample_random_point(random.Random(1), params)
    active_point = SEARCH_SPACE.sample_random_point(random.Random(5), params)

    assert list(inactive_point.keys()) == ["gate", "x"]
    assert inactive_point["gate"] == 0
    assert "momentum" not in inactive_point

    assert list(active_point.keys()) == ["gate", "momentum", "x"]
    assert active_point["gate"] == 1
    assert 0.0 <= active_point["momentum"] <= 0.99


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
        (
            {
                "parameters": [
                    {"name": "optimizer", "type": "categorical", "choices": ["adam", "sgd"]},
                    {
                        "name": "momentum",
                        "type": "float",
                        "bounds": [0.0, 0.99],
                        "when": {"missing": "sgd"},
                    },
                ]
            },
            "unknown conditional controller 'missing'",
        ),
        (
            {
                "parameters": [
                    {"name": "base_lr", "type": "float", "bounds": [0.001, 0.1]},
                    {
                        "name": "warmup_steps",
                        "type": "int",
                        "bounds": [0, 10],
                        "when": {"base_lr": 0.01},
                    },
                ]
            },
            "must not use float controller 'base_lr'",
        ),
        (
            {
                "parameters": [
                    {"name": "optimizer", "type": "categorical", "choices": ["adam", "sgd"]},
                    {
                        "name": "momentum",
                        "type": "float",
                        "bounds": [0.0, 0.99],
                        "when": {"optimizer": "rmsprop"},
                    },
                ]
            },
            "must match one of the configured categorical choices",
        ),
        (
            {
                "parameters": [
                    {"name": "a", "type": "int", "bounds": [0, 1], "when": {"b": 1}},
                    {"name": "b", "type": "int", "bounds": [0, 1], "when": {"a": 1}},
                ]
            },
            "conditional dependency cycle: a -> b -> a",
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


def test_conditional_encoding_round_trips_with_omitted_inactive_params() -> None:
    params = SEARCH_SPACE.normalize_search_space(
        {
            "parameters": [
                {
                    "name": "momentum",
                    "type": "float",
                    "bounds": [0.0, 0.99],
                    "when": {"gate": 1},
                },
                {"name": "gate", "type": "int", "bounds": [0, 1]},
                {"name": "x", "type": "float", "bounds": [0.0, 1.0]},
            ]
        }
    )

    inactive_point = {"gate": 0, "x": 0.25}
    inactive_encoded = SEARCH_SPACE.normalize_numeric_point(inactive_point, params)
    assert inactive_encoded == pytest.approx([0.0, 0.0, 0.25])
    assert SEARCH_SPACE.denormalize_numeric_point(inactive_encoded, params) == inactive_point

    active_point = {"gate": 1, "momentum": 0.5, "x": 0.25}
    active_encoded = SEARCH_SPACE.normalize_numeric_point(active_point, params)
    assert active_encoded == pytest.approx([1.0, 0.5050505050505051, 0.25])
    assert SEARCH_SPACE.denormalize_numeric_point(active_encoded, params) == pytest.approx(
        active_point
    )


def test_mixed_encoding_round_trips_raw_values() -> None:
    params = SEARCH_SPACE.normalize_search_space(
        {
            "parameters": [
                {"name": "lr", "type": "float", "bounds": [0.001, 1.0], "scale": "log"},
                {"name": "layers", "type": "int", "bounds": [1, 9]},
                {"name": "use_bn", "type": "bool"},
                {"name": "optimizer", "type": "categorical", "choices": ["adam", "sgd", "rmsprop"]},
            ]
        }
    )
    point = {
        "lr": 0.03162277660168379,
        "layers": 5,
        "use_bn": True,
        "optimizer": "sgd",
    }

    encoded = SEARCH_SPACE.normalize_numeric_point(point, params)
    assert encoded == pytest.approx([0.5, 0.5, 1.0, 0.0, 1.0, 0.0])

    decoded = SEARCH_SPACE.denormalize_numeric_point(encoded, params)
    assert decoded["lr"] == pytest.approx(point["lr"])
    assert decoded["layers"] == point["layers"]
    assert decoded["use_bn"] is point["use_bn"]
    assert decoded["optimizer"] == point["optimizer"]


def test_mixed_distance_uses_encoded_representation() -> None:
    params = SEARCH_SPACE.normalize_search_space(
        {
            "parameters": [
                {"name": "lr", "type": "float", "bounds": [0.001, 1.0], "scale": "log"},
                {"name": "layers", "type": "int", "bounds": [1, 9]},
                {"name": "use_bn", "type": "bool"},
                {"name": "optimizer", "type": "categorical", "choices": ["adam", "sgd", "rmsprop"]},
            ]
        }
    )
    first = {
        "lr": 0.03162277660168379,
        "layers": 5,
        "use_bn": True,
        "optimizer": "sgd",
    }
    second = {
        "lr": 0.03162277660168379,
        "layers": 5,
        "use_bn": False,
        "optimizer": "adam",
    }

    assert SEARCH_SPACE.normalized_numeric_distance(first, first, params) == pytest.approx(0.0)
    assert SEARCH_SPACE.normalized_numeric_distance(first, second, params) == pytest.approx(
        math.sqrt(3.0)
    )
