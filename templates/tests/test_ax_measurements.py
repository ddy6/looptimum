"""Noise/outcome contracts remain dependency-free and preserve replay identity."""

from __future__ import annotations

import copy
import importlib.util
import json
import math
import os
import subprocess
import sys
from pathlib import Path

import pytest

SHARED = Path(__file__).resolve().parents[1] / "_shared"


def load(name):
    spec = importlib.util.spec_from_file_location(
        f"measurements_test_{name}", SHARED / f"{name}.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


AX = load("ax_contract")
OBJECTIVES = load("objectives")
CONTRACT = load("contract")
IO = load("observations_io")
SPACE = load("search_space")
RUNTIME = load("runtime")
AVAILABLE = importlib.util.find_spec("ax") is not None
if os.environ.get("LOOPTIMUM_REQUIRE_AX_TESTS") == "1" and not AVAILABLE:
    raise RuntimeError("Required Ax measurement lane did not install the Ax extra")


def config(*, weighted=False, pareto=False):
    raw = {
        "primary_objective": {"name": "loss", "direction": "minimize"},
        "measurement_metrics": ["resource"],
        "outcome_constraints": [{"metric": "resource", "op": "<=", "bound": 1.0}],
    }
    if weighted or pareto:
        raw["secondary_objectives"] = [{"name": "gain", "direction": "maximize"}]
    if weighted:
        raw["scalarization"] = {"policy": "weighted_sum", "weights": {"loss": 1, "gain": 1}}
    if pareto:
        raw["pareto_reference"] = {"loss": 10, "gain": -1}
    return OBJECTIVES.normalize_objective_schema(
        raw, contract_version=2, acquisition="pareto" if pareto else "scalar"
    )


def row(**fields):
    return {
        "trial_id": 1,
        "params": {"x": 0.5},
        "status": "ok",
        "objectives": {"loss": 0.2},
        "measurements": {"resource": 0.8},
        **fields,
    }


def normalize(value, cfg=None):
    return CONTRACT.normalize_ingest_payload(
        value, objective_cfg=cfg or config(), source_path=Path("result.json")
    )[0]


def test_unknown_zero_and_empty_maps_have_distinct_canonical_meanings():
    unknown = normalize(row(objective_sems={}, measurement_sems={}))
    assert "objective_sems" not in unknown and "measurement_sems" not in unknown
    known = normalize(row(objective_sems={"loss": 0}, measurement_sems={"resource": 0}))
    assert known["objective_sems"] == {"loss": 0.0}
    assert known["measurement_sems"] == {"resource": 0.0}
    assert AX.project_metrics(known, config(), 0.2) == {
        "score": {"mean": 0.2, "sem": 0.0},
        "m1": {"mean": 0.8, "sem": 0.0},
    }
    assert AX.project_metrics(unknown, config(), 0.2)["score"]["sem"] is None


@pytest.mark.parametrize(
    "value", [True, "0.1", None, -0.01, math.nan, math.inf, -math.inf, 10**1000]
)
@pytest.mark.parametrize(
    "field,metric", [("objective_sems", "loss"), ("measurement_sems", "resource")]
)
def test_invalid_sem_values_are_rejected(value, field, metric):
    with pytest.raises(ValueError):
        normalize(row(**{field: {metric: value}}))


@pytest.mark.parametrize("field", ["objective_sems", "measurements", "measurement_sems"])
@pytest.mark.parametrize("value", [None, [], False])
def test_metric_maps_cannot_be_null_arrays_or_booleans(field, value):
    with pytest.raises(ValueError):
        normalize(row(**{field: value}))


@pytest.mark.parametrize("value", [True, "0.1", None, math.nan, math.inf, 10**1000])
def test_measurements_are_finite_numbers(value):
    with pytest.raises(ValueError):
        normalize(row(measurements={"resource": value}))


def test_measurements_are_required_and_cannot_use_unknown_names():
    for fields in (
        {"measurements": {}},
        {"measurements": {"other": 1}},
        {"measurement_sems": {"other": 0}},
        {"objective_sems": {"other": 0}},
    ):
        with pytest.raises(ValueError):
            normalize(row(**fields))


def test_successful_infeasible_measurements_are_retained_as_measurements():
    value = normalize(row(measurements={"resource": 2.0}))
    assert value["status"] == "ok" and value["measurements"] == {"resource": 2.0}


def test_weighted_noise_requires_actual_score_sem_without_covariance_assumptions():
    cfg = config(weighted=True)
    value = row(objectives={"loss": 0.2, "gain": 0.5}, objective_sems={"loss": 0.1, "gain": 0.2})
    with pytest.raises(ValueError, match="scalarized_sem"):
        normalize(value, cfg)
    result = normalize({**value, "scalarized_sem": 0}, cfg)
    assert AX.project_metrics(result, cfg, -0.15)["score"]["sem"] == 0.0
    assert result["objective_sems"] == {"loss": 0.1, "gain": 0.2}


def test_primary_and_pareto_reject_unused_score_sems_and_pareto_keeps_individual_errors():
    for cfg in (config(), config(pareto=True)):
        with pytest.raises(ValueError, match="scalarized_sem"):
            normalize(
                row(objectives={name: 0.2 for name in cfg["objective_names"]}, scalarized_sem=0),
                cfg,
            )
    cfg = config(pareto=True)
    value = normalize(row(objectives={"loss": 0.2, "gain": 0.5}, objective_sems={"loss": 0}), cfg)
    projected = AX.project_metrics(value, cfg, 99)
    assert "score" not in projected
    assert projected["m0"] == {"mean": 0.2, "sem": 0.0}
    assert projected["m1"] == {"mean": 0.5, "sem": None}


@pytest.mark.parametrize("status", ["failed", "killed", "timeout"])
def test_failed_outcomes_carry_no_measured_values_or_errors(status):
    value = row(status=status, objectives={"loss": None}, measurements={})
    assert "measurements" not in normalize(value)
    for fields in (
        {"objective_sems": {"loss": 0}},
        {"measurements": {"resource": 0.8}},
        {"measurement_sems": {"resource": 0}},
    ):
        with pytest.raises(ValueError, match="Non-ok"):
            normalize({**value, **fields})


def test_coverage_is_per_modeled_metric_and_zero_establishes_known_noise():
    known = normalize(row(objective_sems={"loss": 0}))
    also_known = normalize(row(trial_id=2, objective_sems={"loss": 0.2}))
    AX.validate_measurement_coverage([known, also_known], config())
    # Constraint noise may be known while objective noise is entirely unknown.
    AX.validate_measurement_coverage(
        [
            normalize(row(measurement_sems={"resource": 0.1})),
            normalize(row(trial_id=2, measurement_sems={"resource": 0})),
        ],
        config(),
    )
    for rows in ([known, normalize(row())], [normalize(row()), known]):
        before = copy.deepcopy(rows)
        with pytest.raises(ValueError, match="Inconsistent SEM coverage"):
            AX.validate_measurement_coverage(rows, config())
        assert rows == before


def test_failure_does_not_set_coverage_and_batch_or_out_of_order_history_cannot_mix():
    failure = {"status": "failed", "objectives": {"loss": None}}
    known = normalize(row(objective_sems={"loss": 0}))
    AX.validate_measurement_coverage([failure, known], config())
    with pytest.raises(ValueError, match="Inconsistent SEM coverage"):
        AX.validate_measurement_coverage([failure, known, normalize(row(trial_id=2))], config())


def test_terminal_replay_identity_includes_known_and_unknown_noise():
    unknown = CONTRACT.build_observation_contract(normalize(row()), objective_cfg=config())
    zero = CONTRACT.build_observation_contract(
        normalize(row(objective_sems={"loss": 0})), objective_cfg=config()
    )
    diffs = CONTRACT.diff_contract_records(unknown, zero)
    assert any("objective_sems" in difference for difference in diffs)
    assert not CONTRACT.diff_contract_records(
        unknown,
        CONTRACT.build_observation_contract(
            normalize(row(objective_sems={})), objective_cfg=config()
        ),
    )


def test_version_one_records_and_objective_snapshots_have_no_new_fields():
    cfg = OBJECTIVES.normalize_objective_schema(
        {"primary_objective": {"name": "loss", "direction": "minimize"}}
    )
    assert "ax_contract_version" not in cfg
    assert "ax_contract_version" not in OBJECTIVES.objective_config_snapshot(cfg)
    value = row()
    del value["measurements"]
    assert (
        CONTRACT.normalize_ingest_payload(value, objective_cfg=cfg, source_path=Path("old.json"))[0]
        == value
    )
    with pytest.raises(ValueError, match="contract_version=2"):
        CONTRACT.normalize_ingest_payload(
            {**value, "objective_sems": {}}, objective_cfg=cfg, source_path=Path("old.json")
        )


def test_outcome_reference_and_constraint_configuration_rejects_ambiguous_semantics():
    base = {
        "primary_objective": {"name": "loss", "direction": "minimize"},
        "measurement_metrics": ["resource"],
    }
    invalid = [
        {"measurement_metrics": ["loss"]},
        {"measurement_metrics": ["resource", "resource"]},
        {"outcome_constraints": [{"metric": "loss", "op": "<=", "bound": 1}]},
        {"outcome_constraints": [{"metric": "other", "op": "<=", "bound": 1}]},
        {"outcome_constraints": [{"metric": "resource", "op": "<", "bound": 1}]},
        {
            "outcome_constraints": [
                {"metric": "resource", "op": ">=", "bound": 2},
                {"metric": "resource", "op": "<=", "bound": 1},
            ]
        },
        {"pareto_reference": {"loss": math.nan}},
    ]
    for fields in invalid:
        with pytest.raises(ValueError):
            OBJECTIVES.normalize_objective_schema({**base, **fields}, contract_version=2)
    with pytest.raises(ValueError, match="contract_version=2"):
        OBJECTIVES.normalize_objective_schema(base)


@pytest.mark.parametrize("format", ["jsonl", "csv"])
def test_measurements_survive_export_import_with_typed_params_and_zero_sem(tmp_path, format):
    value = normalize(row(objective_sems={"loss": 0}, measurement_sems={"resource": 0.03}))
    params = SPACE.normalize_search_space(
        {"parameters": [{"name": "x", "type": "float", "bounds": [0, 1]}]}
    )
    path = tmp_path / f"records.{format}"
    render = IO.render_observations_csv if format == "csv" else IO.render_observations_jsonl
    path.write_text(render([value]))
    raw = IO.load_observation_rows(path, format)[0]
    imported = IO.normalize_import_record(
        raw,
        row_format=format,
        params=params,
        objective_cfg=config(),
        local_trial_id=2,
        imported_at=1.0,
    )["observation"]
    for key in AX.MEASUREMENT_FIELDS:
        assert imported.get(key) == value.get(key)
    assert imported["params"] == value["params"]
    assert imported["objective_sems"]["loss"] == 0.0


def test_csv_extension_names_do_not_collide_with_user_objective_names():
    value = row(objectives={"sems_json": 0.2}, objective_sems={"sems_json": 0})
    flat = IO.flatten_observation_for_csv(value)
    assert flat["objective_sems_json"] == 0.2
    assert flat["ax_objective_sems_json"] == '{"sems_json":0}'


@pytest.mark.parametrize("format", ["jsonl", "csv"])
def test_v2_round_trips_distinct_numeric_string_and_empty_categorical_choices(tmp_path, format):
    params = SPACE.normalize_search_space(
        {"parameters": [{"name": "choice", "type": "categorical", "choices": [1, 1.0, "1", ""]}]}
    )
    values = [
        row(trial_id=i + 1, params={"choice": choice}) for i, choice in enumerate([1, 1.0, "1", ""])
    ]
    path = tmp_path / f"typed.{format}"
    path.write_text(
        IO.render_observations_csv(values, typed_params=True)
        if format == "csv"
        else IO.render_observations_jsonl(values)
    )
    for original, raw in zip(values, IO.load_observation_rows(path, format), strict=True):
        parsed = IO.normalize_import_record(
            raw,
            row_format=format,
            params=params,
            objective_cfg=config(),
            local_trial_id=10,
            imported_at=1.0,
        )["observation"]
        assert parsed["params"] == original["params"]
        assert type(parsed["params"]["choice"]) is type(original["params"]["choice"])
    assert CONTRACT.diff_contract_records(
        {"params": {"choice": 1}}, {"params": {"choice": 1.0}}, typed_params=True
    )


def test_pareto_requires_reference_and_scalar_reference_is_observed_report_metadata():
    raw = {
        "primary_objective": {"name": "loss", "direction": "minimize"},
        "secondary_objectives": [{"name": "gain", "direction": "maximize"}],
    }
    with pytest.raises(ValueError, match="pareto_reference"):
        OBJECTIVES.normalize_objective_schema(raw, contract_version=2, acquisition="pareto")
    # C4 requires the reference for Pareto acquisition; scalar acquisition may
    # declare one for an observed hypervolume report, without changing its score.
    cfg = OBJECTIVES.normalize_objective_schema(
        {**raw, "pareto_reference": {"loss": 2, "gain": -1}}, contract_version=2
    )
    assert cfg["acquisition"] == "scalar"
    assert OBJECTIVES.scalarize_objectives({"loss": 0.2, "gain": 100}, cfg) == 0.2


def test_tchebycheff_sems_are_evaluator_supplied_not_derived_from_components():
    cfg = config(weighted=True)
    cfg["scalarization"]["policy"] = "weighted_tchebycheff"
    value = row(objectives={"loss": 0.2, "gain": 0.5}, objective_sems={"loss": 0.1})
    with pytest.raises(ValueError, match="scalarized_sem"):
        normalize(value, cfg)
    assert normalize({**value, "scalarized_sem": 0.03}, cfg)["scalarized_sem"] == 0.03


@pytest.mark.parametrize("schema,format", [("0.4.0", 1), ("0.5.0", 2)])
def test_current_state_reader_dispatch_and_payload_version_are_explicit(schema, format):
    value = {"schema_version": schema, "optimizer": {"backend": "ax", "format_version": format}}
    assert RUNTIME.normalize_state_schema_version(value, state_path=Path("state.json")) == value
    assert RUNTIME.payload_schema_version(value) == ("0.3.0" if format == 1 else "0.4.0")
    bad = {**value, "optimizer": {"backend": "ax", "format_version": 3 - format}}
    before = copy.deepcopy(bad)
    with pytest.raises(ValueError, match="format_version"):
        RUNTIME.normalize_state_schema_version(bad, state_path=Path("bad.json"))
    assert bad == before


@pytest.mark.skipif(not AVAILABLE, reason="optional Ax stack is not installed")
@pytest.mark.parametrize("variant", ["bo_client", "bo_client_full"])
def test_real_v2_noise_constraint_projection_lean_ingest_and_model_restart(tmp_path, variant):
    root = SHARED.parents[1]
    project = tmp_path / "controller"
    subprocess.run(
        [
            sys.executable,
            str(SHARED / "vendor_copy.py"),
            str(root / "templates" / variant),
            str(project),
        ],
        check=True,
        capture_output=True,
    )
    settings = json.loads((project / "bo_config.json").read_text())
    settings["optimizer"] = {
        "backend": "ax",
        "ax": {"contract_version": 2, "initialization_budget": 2},
    }
    settings["max_pending_age_seconds"] = None
    (project / "bo_config.json").write_text(json.dumps(settings))
    (project / "parameter_space.json").write_text(
        json.dumps(
            {
                "parameters": [
                    {"name": "x", "type": "float", "bounds": [0, 1]},
                    {"name": "y", "type": "float", "bounds": [0, 1]},
                ]
            }
        )
    )
    (project / "objective_schema.json").write_text(
        json.dumps(
            {
                "primary_objective": {"name": "loss", "direction": "minimize"},
                "measurement_metrics": ["resource"],
                "outcome_constraints": [{"metric": "resource", "op": "<=", "bound": 0.75}],
            }
        )
    )

    def invoke(*args, lean=False, success=True):
        out = subprocess.run(
            [sys.executable, *(["-S"] if lean else []), "run_bo.py", *args],
            cwd=project,
            capture_output=True,
            text=True,
            timeout=150,
        )
        if success:
            assert out.returncode == 0, out.stdout + out.stderr
        return out

    suggestions = json.loads(invoke("suggest", "--count", "2", "--json-only").stdout)["suggestions"]
    assert all(suggestion["schema_version"] == "0.4.0" for suggestion in suggestions)
    state_file = project / "state/bo_state.json"
    assert json.loads(state_file.read_text())["schema_version"] == "0.5.0"
    for i, suggestion in enumerate(reversed(suggestions)):
        payload = {
            "schema_version": "0.4.0",
            "trial_id": suggestion["trial_id"],
            "params": suggestion["params"],
            "status": "ok",
            "objectives": {
                "loss": (suggestion["params"]["x"] - 0.3) ** 2
                + (suggestion["params"]["y"] - 0.7) ** 2
            },
            "objective_sems": {"loss": 0 if i == 0 else 0.02},
            "measurements": {"resource": suggestion["params"]["x"]},
            "measurement_sems": {"resource": 0.01},
        }
        file = project / "result.json"
        if i == 1:
            before_invalid = {
                str(path.relative_to(project)): path.read_bytes()
                for path in (project / "state").rglob("*")
                if path.is_file() and path.name != ".looptimum.lock"
            }
            file.write_text(json.dumps({**payload, "objective_sems": {}}))
            rejected = invoke("ingest", "--results-file", str(file), lean=True, success=False)
            assert rejected.returncode and "Inconsistent SEM coverage" in rejected.stderr
            after_invalid = {
                str(path.relative_to(project)): path.read_bytes()
                for path in (project / "state").rglob("*")
                if path.is_file() and path.name != ".looptimum.lock"
            }
            assert after_invalid == before_invalid
        file.write_text(json.dumps(payload))
        invoke("ingest", "--results-file", str(file), lean=True)
        before = state_file.read_bytes()
        assert "No-op" in invoke("ingest", "--results-file", str(file), lean=True).stdout
        assert state_file.read_bytes() == before
        manifest = json.loads(
            (project / f"state/trials/trial_{suggestion['trial_id']}/manifest.json").read_text()
        )
        assert manifest["objective_sems"] == payload["objective_sems"]
        assert manifest["measurements"] == payload["measurements"]
    modeled = json.loads(invoke("suggest", "--json-only").stdout)
    assert modeled["trial_id"] == 3
    state = json.loads(state_file.read_text())
    assert state["optimizer"]["format_version"] == 2
    snapshot = json.loads((project / state["optimizer"]["snapshot"]["path"]).read_text())
    assert snapshot["objective_config"]["measurement_metrics"] == ["resource"]
    assert len(snapshot["mapping"]) == 3
    decisions = [
        json.loads(line)
        for line in (project / "state/acquisition_log.jsonl").read_text().splitlines()
    ]
    assert decisions[-1]["decision"]["generation_node"] == "MBM"
    assert "Validation passed" in invoke("validate", lean=True).stdout


def test_unmodeled_measurements_are_retained_without_becoming_model_noise():
    cfg = config()
    cfg["measurement_metrics"].append("diagnostic")
    first = normalize(
        row(measurements={"resource": 0.5, "diagnostic": 1}, measurement_sems={"diagnostic": 0.1}),
        cfg,
    )
    second = normalize(row(trial_id=2, measurements={"resource": 0.5, "diagnostic": 2}), cfg)
    AX.validate_measurement_coverage([first, second], cfg)
    assert first["measurement_sems"] == {"diagnostic": 0.1}
    assert set(AX.project_metrics(first, cfg, 0.2)) == {"score", "m1"}


def test_v1_fingerprint_matches_actual_pre_change_code_fixture():
    fixture = json.loads((Path(__file__).parent / "fixtures/ax_v1_fingerprint.json").read_text())
    optimizer_ax = load("optimizer_ax")
    backend = load("optimizer_backend")
    parameters = optimizer_ax._parameters(
        SPACE.normalize_search_space(fixture["raw_parameter_space"])
    )
    cfg = OBJECTIVES.normalize_objective_schema(fixture["raw_objective_schema"])
    for explicit in ({}, {"contract_version": 1, "acquisition": "scalar"}):
        optimizer = backend.normalize_optimizer_config(
            {"optimizer": {"backend": "ax", "ax": explicit}}
        )
        assert (
            optimizer_ax._fingerprint(
                parameters, cfg, optimizer["ax"], {"meta": {"seed": fixture["seed"]}}
            )
            == fixture["expected_fingerprint"]
        )


@pytest.mark.parametrize("version", ["0.3.0", "0.4.0", "0.4.9"])
def test_new_reader_accepts_compatible_declared_evaluator_versions(version):
    assert normalize(row(schema_version=version))["schema_version"] == version


@pytest.mark.parametrize("version", ["0.5.0", "1.0.0", True, None, "0.4"])
def test_new_reader_refuses_incompatible_declared_evaluator_versions(version):
    with pytest.raises(ValueError, match="payload schema"):
        normalize(row(schema_version=version))
