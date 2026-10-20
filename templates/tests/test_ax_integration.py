"""Run with the Ax extra; CI sets LOOPTIMUM_REQUIRE_AX_TESTS to prohibit skips."""

from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
import venv
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
AVAILABLE = importlib.util.find_spec("ax") is not None
if os.environ.get("LOOPTIMUM_REQUIRE_AX_TESTS") == "1" and not AVAILABLE:
    raise RuntimeError("Required Ax integration lane did not install the Ax extra")
pytestmark = pytest.mark.skipif(not AVAILABLE, reason="optional Ax stack is not installed")


def invoke(project, *args, lean=False, success=True, env=None, executable=None):
    out = subprocess.run(
        [executable or sys.executable, *(["-S"] if lean else []), "run_bo.py", *args],
        cwd=project,
        text=True,
        capture_output=True,
        env={**os.environ, **(env or {})},
        timeout=150,
    )
    if success:
        assert out.returncode == 0, out.stdout + out.stderr
    return out


def campaign(tmp_path, variant="bo_client", mixed=False):
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
    config["optimizer"] = {"backend": "ax", "ax": {"initialization_budget": 2}}
    config["initial_random_trials"] = 999
    config["worker_leases"] = {"enabled": True}
    config["max_pending_age_seconds"] = None
    (project / "bo_config.json").write_text(json.dumps(config))
    parameters = [
        {"name": "x", "type": "float", "bounds": [0, 1]},
        {"name": "y", "type": "float", "bounds": [0, 1]},
    ]
    if mixed:
        parameters = [
            {"name": "lr", "type": "float", "bounds": [0.001, 0.1], "scale": "log"},
            {"name": "flag", "type": "bool"},
            {"name": "batch", "type": "int", "bounds": [2, 8]},
            {"name": "kind", "type": "categorical", "choices": ["a", "b"]},
        ]
    (project / "parameter_space.json").write_text(json.dumps({"parameters": parameters}))
    (project / "objective_schema.json").write_text(
        json.dumps({"primary_objective": {"name": "loss", "direction": "minimize"}})
    )
    return project


def state(project):
    return json.loads((project / "state/bo_state.json").read_text())


def ingest(project, suggestion, value, status="ok"):
    payload = {
        "trial_id": suggestion["trial_id"],
        "params": suggestion["params"],
        "objectives": {"loss": value},
        "status": status,
    }
    path = project / "result.json"
    path.write_text(json.dumps(payload))
    return invoke(
        project,
        "ingest",
        "--results-file",
        str(path),
        "--lease-token",
        suggestion["lease_token"],
        lean=True,
    )


@pytest.mark.parametrize("variant", ["bo_client", "bo_client_full"])
def test_real_ax_batch_restart_ingest_failure_and_cancellation(tmp_path, variant):
    project = campaign(tmp_path, variant)
    initial = json.loads(invoke(project, "suggest", "--count", "2", "--json-only").stdout)[
        "suggestions"
    ]
    assert [row["trial_id"] for row in initial] == [1, 2]
    assert all(row["schema_version"] == "0.3.0" for row in initial)
    assert state(project)["schema_version"] == "0.4.0"
    first_snapshot = project / state(project)["optimizer"]["snapshot"]["path"]
    original_bytes = first_snapshot.read_bytes()
    ingest(project, initial[1], 0.2)
    replay = ingest(project, initial[1], 0.2)
    assert "No-op" in replay.stdout
    ingest(project, initial[0], 0.4)
    third = json.loads(invoke(project, "suggest", "--json-only").stdout)
    assert third["trial_id"] == 3
    decisions = [
        json.loads(line)
        for line in (project / "state/acquisition_log.jsonl").read_text().splitlines()
    ]
    assert decisions[-1]["decision"]["generation_node"] == "MBM"
    assert decisions[-1]["decision"]["surrogate_backend"] == "ax"
    ingest(project, third, None, "timeout")
    fourth = json.loads(invoke(project, "suggest", "--json-only").stdout)
    invoke(project, "cancel", "--trial-id", str(fourth["trial_id"]), lean=True)
    fifth = json.loads(invoke(project, "suggest", "--json-only").stdout)
    assert fifth["trial_id"] == 5
    assert first_snapshot.read_bytes() == original_bytes
    observed = json.loads(invoke(project, "status", lean=True).stdout)
    assert observed["best"]["trial_id"] == 2
    assert observed["state_schema_version"] == "0.4.0"
    assert observed["observations_by_status"]["timeout"] == 1
    assert observed["observations_by_status"]["killed"] == 1
    assert "Validation passed" in invoke(project, "validate", lean=True).stdout
    invoke(project, "report", lean=True)
    doctor = json.loads(invoke(project, "doctor", "--json", lean=True).stdout)
    assert doctor["optimizer"]["available"] is False


def test_real_ax_mixed_space_types_and_snapshot_failure_are_atomic(tmp_path):
    project = campaign(tmp_path, mixed=True)
    first = json.loads(invoke(project, "suggest", "--json-only").stdout)
    params = first["params"]
    assert 0.001 <= params["lr"] <= 0.1
    assert type(params["flag"]) is bool and type(params["batch"]) is int
    assert params["kind"] in ("a", "b")
    original = (project / "state/bo_state.json").read_bytes()
    failed = invoke(
        project,
        "suggest",
        "--json-only",
        success=False,
        env={"LOOPTIMUM_TEST_ATOMIC_FAIL_BASENAME": "bo_state.json"},
    )
    assert failed.returncode != 0
    assert (project / "state/bo_state.json").read_bytes() == original
    assert len(state(project)["pending"]) == 1
    retried = json.loads(invoke(project, "suggest", "--json-only").stdout)
    assert retried["trial_id"] == 2


def test_real_ax_partial_initialization_batch_does_not_allocate(tmp_path):
    project = campaign(tmp_path)
    failed = invoke(project, "suggest", "--count", "3", "--json-only", success=False)
    assert failed.returncode != 0
    assert not (project / "state/bo_state.json").exists()
    assert not (project / "state/trials").exists()


def test_missing_ax_never_falls_back_to_legacy_warmup(tmp_path):
    project = campaign(tmp_path)
    environment = tmp_path / "without_ax"
    venv.EnvBuilder(with_pip=False, system_site_packages=False).create(environment)
    executable = environment / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    failed = invoke(project, "suggest", "--json-only", executable=str(executable), success=False)
    assert failed.returncode != 0
    assert "requires ax-platform==1.3.1" in failed.stderr
    assert not (project / "state/bo_state.json").exists()


def test_snapshot_corruption_blocks_generation_but_preserves_read_and_ingest(tmp_path):
    project = campaign(tmp_path)
    first = json.loads(invoke(project, "suggest", "--json-only").stdout)
    pointer = state(project)["optimizer"]["snapshot"]["path"]
    (project / pointer).write_text("{}")
    failed = invoke(project, "suggest", "--json-only", success=False)
    assert failed.returncode != 0 and "digest mismatch" in failed.stderr
    ingest(project, first, 0.2)
    observed = json.loads(invoke(project, "status", lean=True).stdout)
    assert observed["observations"] == 1 and observed["pending"] == 0
    assert invoke(project, "validate", lean=True, success=False).returncode != 0
