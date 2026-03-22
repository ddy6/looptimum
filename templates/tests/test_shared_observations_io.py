from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
OBSERVATIONS_IO_MODULE = REPO_ROOT / "templates" / "_shared" / "observations_io.py"
OBJECTIVES_MODULE = REPO_ROOT / "templates" / "_shared" / "objectives.py"
SEARCH_SPACE_MODULE = REPO_ROOT / "templates" / "_shared" / "search_space.py"


def _load_module(module_path: Path, module_name: str):
    spec = importlib.util.spec_from_file_location(module_name, module_path)
    if spec is None or spec.loader is None:
        raise ImportError(f"Unable to load shared module from {module_path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


OBS_IO = _load_module(OBSERVATIONS_IO_MODULE, "looptimum_shared_observations_io_test")
OBJECTIVES = _load_module(OBJECTIVES_MODULE, "looptimum_shared_observations_objectives_test")
SEARCH_SPACE = _load_module(SEARCH_SPACE_MODULE, "looptimum_shared_observations_space_test")


def _objective_cfg():
    return OBJECTIVES.normalize_objective_schema(
        {"primary_objective": {"name": "loss", "direction": "minimize"}}
    )


def test_infer_observation_format_from_suffix() -> None:
    assert OBS_IO.infer_observation_format(Path("seed.csv")) == "csv"
    assert OBS_IO.infer_observation_format(Path("seed.jsonl")) == "jsonl"
    assert OBS_IO.infer_observation_format(Path("seed.ndjson")) == "jsonl"

    with pytest.raises(ValueError, match="Unsupported observation file format"):
        OBS_IO.infer_observation_format(Path("seed.json"))


def test_plan_import_trial_ids_allocates_sequential_ids_and_rejects_pending() -> None:
    assert OBS_IO.plan_import_trial_ids({"pending": [], "next_trial_id": 7}, 3) == [7, 8, 9]

    with pytest.raises(ValueError, match="requires zero pending trials"):
        OBS_IO.plan_import_trial_ids(
            {"pending": [{"trial_id": 5, "params": {}, "suggested_at": 1.0}], "next_trial_id": 8},
            1,
        )


def test_normalize_import_record_jsonl_remaps_trial_id_and_canonicalizes_conditionals() -> None:
    params = SEARCH_SPACE.normalize_search_space(
        {
            "parameters": [
                {"name": "gate", "type": "int", "bounds": [0, 1]},
                {"name": "x", "type": "float", "bounds": [0.0, 1.0]},
                {
                    "name": "momentum",
                    "type": "float",
                    "bounds": [0.0, 0.99],
                    "when": {"gate": 1},
                },
            ]
        }
    )

    normalized = OBS_IO.normalize_import_record(
        {
            "trial_id": 41,
            "params": {"gate": 0, "x": 0.25, "momentum": 0.8},
            "objectives": {"loss": None},
            "status": "failed",
        },
        row_format="jsonl",
        params=params,
        objective_cfg=_objective_cfg(),
        local_trial_id=7,
        imported_at=99.0,
    )

    assert normalized == {
        "row_format": "jsonl",
        "source_trial_id": 41,
        "observation": {
            "trial_id": 7,
            "status": "failed",
            "suggested_at": None,
            "completed_at": 99.0,
            "artifact_path": None,
            "terminal_reason": "status=failed",
            "penalty_objective": None,
            "params": {"gate": 0, "x": 0.25},
            "objectives": {"loss": None},
        },
    }


def test_flatten_observation_for_csv_round_trips_mixed_values() -> None:
    params = SEARCH_SPACE.normalize_search_space(
        {
            "parameters": [
                {"name": "use_bn", "type": "bool"},
                {"name": "optimizer", "type": "categorical", "choices": ["adam", "sgd"]},
                {"name": "layers", "type": "int", "bounds": [1, 8]},
                {"name": "lr", "type": "float", "bounds": [0.0001, 0.1], "scale": "log"},
            ]
        }
    )
    observation = {
        "trial_id": 5,
        "params": {"use_bn": True, "optimizer": "adam", "layers": 4, "lr": 0.01},
        "objectives": {"loss": 0.25},
        "status": "ok",
        "suggested_at": 10.0,
        "completed_at": 12.5,
        "runtime_seconds": 2.5,
        "artifact_path": "state/trials/trial_5/ingest_payload.json",
        "heartbeat_count": 3,
        "heartbeat_note": "done",
        "heartbeat_meta": {"worker": "node-1"},
        "lease_token": "lease-5",
    }

    flat = OBS_IO.flatten_observation_for_csv(observation)
    assert flat["param_use_bn"] is True
    assert flat["param_optimizer"] == "adam"
    assert flat["objective_loss"] == 0.25
    assert flat["heartbeat_meta_json"] == '{"worker":"node-1"}'

    csv_row = {key: ("" if value is None else str(value)) for key, value in flat.items()}
    normalized = OBS_IO.normalize_import_record(
        csv_row,
        row_format="csv",
        params=params,
        objective_cfg=_objective_cfg(),
        local_trial_id=9,
        imported_at=99.0,
    )

    assert normalized == {
        "row_format": "csv",
        "source_trial_id": "5",
        "observation": {
            "trial_id": 9,
            "status": "ok",
            "suggested_at": 10.0,
            "completed_at": 12.5,
            "runtime_seconds": 2.5,
            "artifact_path": "state/trials/trial_5/ingest_payload.json",
            "heartbeat_count": 3,
            "heartbeat_note": "done",
            "heartbeat_meta": {"worker": "node-1"},
            "lease_token": "lease-5",
            "params": {"use_bn": True, "optimizer": "adam", "layers": 4, "lr": 0.01},
            "objectives": {"loss": 0.25},
        },
    }


def test_normalize_import_record_rejects_csv_unknown_columns_and_missing_active_params() -> None:
    params = SEARCH_SPACE.normalize_search_space(
        {"parameters": [{"name": "x", "type": "float", "bounds": [0.0, 1.0]}]}
    )

    with pytest.raises(ValueError, match="unknown column 'bogus'"):
        OBS_IO.normalize_import_record(
            {
                "status": "ok",
                "param_x": "0.5",
                "objective_loss": "0.1",
                "bogus": "present",
            },
            row_format="csv",
            params=params,
            objective_cfg=_objective_cfg(),
            local_trial_id=1,
            imported_at=10.0,
        )

    conditional_params = SEARCH_SPACE.normalize_search_space(
        {
            "parameters": [
                {"name": "gate", "type": "int", "bounds": [0, 1]},
                {"name": "x", "type": "float", "bounds": [0.0, 1.0]},
                {
                    "name": "momentum",
                    "type": "float",
                    "bounds": [0.0, 0.99],
                    "when": {"gate": 1},
                },
            ]
        }
    )

    with pytest.raises(ValueError, match="missing required active params \\['momentum'\\]"):
        OBS_IO.normalize_import_record(
            {
                "status": "ok",
                "param_gate": "1",
                "param_x": "0.5",
                "objective_loss": "0.1",
            },
            row_format="csv",
            params=conditional_params,
            objective_cfg=_objective_cfg(),
            local_trial_id=1,
            imported_at=10.0,
        )


def test_normalize_import_record_rejects_invalid_objective_status_combinations() -> None:
    params = SEARCH_SPACE.normalize_search_space(
        {"parameters": [{"name": "x", "type": "float", "bounds": [0.0, 1.0]}]}
    )

    with pytest.raises(ValueError, match="objectives.loss must be a finite number"):
        OBS_IO.normalize_import_record(
            {
                "params": {"x": 0.5},
                "objectives": {"loss": None},
                "status": "ok",
            },
            row_format="jsonl",
            params=params,
            objective_cfg=_objective_cfg(),
            local_trial_id=1,
            imported_at=10.0,
        )

    with pytest.raises(
        ValueError, match="must be null for all configured objectives when status=timeout"
    ):
        OBS_IO.normalize_import_record(
            {
                "params": {"x": 0.5},
                "objectives": {"loss": 0.2},
                "status": "timeout",
            },
            row_format="jsonl",
            params=params,
            objective_cfg=_objective_cfg(),
            local_trial_id=1,
            imported_at=10.0,
        )


def test_export_observation_json_record_stabilizes_known_fields_only() -> None:
    observation = {
        "trial_id": 3,
        "params": {"x": 0.5},
        "objectives": {"loss": 0.2},
        "status": "ok",
        "completed_at": 11.0,
        "artifact_path": None,
        "extra": "ignored",
    }

    assert OBS_IO.export_observation_json_record(observation) == {
        "trial_id": 3,
        "params": {"x": 0.5},
        "objectives": {"loss": 0.2},
        "status": "ok",
        "completed_at": 11.0,
        "artifact_path": None,
    }
