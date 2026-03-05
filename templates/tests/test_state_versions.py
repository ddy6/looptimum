from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
TEMPLATES_ROOT = REPO_ROOT / "templates"
FIXTURES_ROOT = REPO_ROOT / "tests" / "fixtures" / "state_versions"
VARIANTS = ("bo_client", "bo_client_demo", "bo_client_full")

_STATE_ARTIFACT_FILES = (
    "state/bo_state.json",
    "state/observations.csv",
    "state/acquisition_log.jsonl",
    "state/event_log.jsonl",
    "state/.looptimum.lock",
    "state/report.json",
    "state/report.md",
    "examples/_demo_result.json",
)


def _run_cmd(
    project_root: Path, *args: str, expect_ok: bool = True
) -> subprocess.CompletedProcess[str]:
    cmd = [sys.executable, "run_bo.py", *args]
    out = subprocess.run(cmd, cwd=project_root, capture_output=True, text=True)
    if expect_ok and out.returncode != 0:
        raise AssertionError(
            f"Command failed: {' '.join(cmd)}\nSTDOUT:\n{out.stdout}\nSTDERR:\n{out.stderr}"
        )
    return out


def _fixture_payload(name: str) -> dict:
    return json.loads((FIXTURES_ROOT / name).read_text(encoding="utf-8"))


def _prepare_variant_copy(tmp_path: Path, variant: str) -> Path:
    src = TEMPLATES_ROOT / variant
    dst = tmp_path / "template"
    shutil.copytree(src, dst)
    shared_src = TEMPLATES_ROOT / "_shared"
    if shared_src.exists():
        shutil.copytree(shared_src, tmp_path / "_shared")

    for rel in _STATE_ARTIFACT_FILES:
        path = dst / rel
        if path.exists():
            path.unlink()

    trials_dir = dst / "state" / "trials"
    if trials_dir.exists():
        shutil.rmtree(trials_dir)
    return dst


def _write_state(project_root: Path, fixture_name: str) -> Path:
    state_path = project_root / "state" / "bo_state.json"
    state_path.parent.mkdir(parents=True, exist_ok=True)
    payload = _fixture_payload(fixture_name)
    state_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return state_path


@pytest.mark.parametrize("variant", VARIANTS)
def test_missing_schema_version_upgrades_in_memory_and_persists_on_suggest(
    tmp_path: Path, variant: str
) -> None:
    project_root = _prepare_variant_copy(tmp_path, variant)
    state_path = _write_state(project_root, "v0_2_x_missing_schema_version.json")

    status = _run_cmd(project_root, "status")
    status_payload = json.loads(status.stdout)
    assert status_payload["schema_version"] == "0.3.0"
    state_after_status = json.loads(state_path.read_text(encoding="utf-8"))
    assert "schema_version" not in state_after_status

    suggest = _run_cmd(project_root, "suggest", "--json-only")
    suggestion_payload = json.loads(suggest.stdout)
    assert suggestion_payload["schema_version"] == "0.3.0"
    assert "LEGACY STATE SCHEMA DETECTED" in suggest.stderr
    state_after_suggest = json.loads(state_path.read_text(encoding="utf-8"))
    assert state_after_suggest["schema_version"] == "0.3.0"


@pytest.mark.parametrize("variant", VARIANTS)
def test_explicit_v0_2_x_schema_version_upgrades_on_next_mutation(
    tmp_path: Path, variant: str
) -> None:
    project_root = _prepare_variant_copy(tmp_path, variant)
    state_path = _write_state(project_root, "v0_2_2_explicit_schema_version.json")

    doctor = _run_cmd(project_root, "doctor", "--json")
    doctor_payload = json.loads(doctor.stdout)
    assert doctor_payload["schema_version"] == "0.3.0"
    assert doctor_payload["status"]["schema_version"] == "0.3.0"
    state_after_doctor = json.loads(state_path.read_text(encoding="utf-8"))
    assert state_after_doctor["schema_version"] == "0.2.2"

    suggest = _run_cmd(project_root, "suggest", "--json-only")
    suggestion_payload = json.loads(suggest.stdout)
    assert suggestion_payload["schema_version"] == "0.3.0"
    assert "LEGACY STATE SCHEMA DETECTED" in suggest.stderr
    state_after_suggest = json.loads(state_path.read_text(encoding="utf-8"))
    assert state_after_suggest["schema_version"] == "0.3.0"


@pytest.mark.parametrize("variant", VARIANTS)
def test_v0_3_x_state_loads_transparently_without_forced_upgrade(
    tmp_path: Path, variant: str
) -> None:
    project_root = _prepare_variant_copy(tmp_path, variant)
    state_path = _write_state(project_root, "v0_3_1_schema_version.json")

    status = _run_cmd(project_root, "status")
    status_payload = json.loads(status.stdout)
    assert status_payload["schema_version"] == "0.3.1"

    suggest = _run_cmd(project_root, "suggest", "--json-only")
    suggestion_payload = json.loads(suggest.stdout)
    assert suggestion_payload["schema_version"] == "0.3.1"
    assert "LEGACY STATE SCHEMA DETECTED" not in suggest.stderr
    state_after_suggest = json.loads(state_path.read_text(encoding="utf-8"))
    assert state_after_suggest["schema_version"] == "0.3.1"


@pytest.mark.parametrize("variant", VARIANTS)
def test_upgrade_path_from_v0_2_fixture_to_validate_report_and_doctor(
    tmp_path: Path, variant: str
) -> None:
    project_root = _prepare_variant_copy(tmp_path, variant)
    state_path = _write_state(project_root, "v0_2_x_missing_schema_version.json")

    suggest = _run_cmd(project_root, "suggest", "--json-only")
    suggestion_payload = json.loads(suggest.stdout)

    result_payload = {
        "schema_version": suggestion_payload["schema_version"],
        "trial_id": suggestion_payload["trial_id"],
        "params": suggestion_payload["params"],
        "objectives": {"loss": 0.25},
        "status": "ok",
    }
    result_path = project_root / "examples" / "_phase3_upgrade_result.json"
    result_path.write_text(json.dumps(result_payload, indent=2), encoding="utf-8")

    _run_cmd(project_root, "ingest", "--results-file", str(result_path))
    validate = _run_cmd(project_root, "validate")
    assert "Validation passed." in validate.stdout

    _run_cmd(project_root, "report", "--top-n", "3")
    report_payload = json.loads(
        (project_root / "state" / "report.json").read_text(encoding="utf-8")
    )
    assert report_payload["schema_version"] == "0.3.0"
    assert int(report_payload["counts"]["observations"]) >= 1

    doctor_payload = json.loads(_run_cmd(project_root, "doctor", "--json").stdout)
    assert doctor_payload["schema_version"] == "0.3.0"
    assert doctor_payload["status"]["schema_version"] == "0.3.0"

    state_after = json.loads(state_path.read_text(encoding="utf-8"))
    assert state_after["schema_version"] == "0.3.0"
    assert "_looptimum_schema_upgrade_pending" not in state_after


@pytest.mark.parametrize("variant", VARIANTS)
def test_rejects_unsupported_state_schema_series(tmp_path: Path, variant: str) -> None:
    project_root = _prepare_variant_copy(tmp_path, variant)
    state_path = _write_state(project_root, "v0_3_1_schema_version.json")
    state = json.loads(state_path.read_text(encoding="utf-8"))
    state["schema_version"] = "0.4.0"
    state_path.write_text(json.dumps(state, indent=2), encoding="utf-8")

    out = _run_cmd(project_root, "status", expect_ok=False)
    assert out.returncode != 0
    assert "Unsupported state.schema_version '0.4.0'" in out.stderr
