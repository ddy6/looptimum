from __future__ import annotations

import json
import shutil
import subprocess
import sys
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from service.app import create_app
from service.config import build_service_config

REPO_ROOT = Path(__file__).resolve().parents[2]
TEMPLATES_ROOT = REPO_ROOT / "templates"
VARIANTS = ("bo_client", "bo_client_demo", "bo_client_full")
STATE_ARTIFACT_FILES = (
    "state/bo_state.json",
    "state/observations.csv",
    "state/acquisition_log.jsonl",
    "state/event_log.jsonl",
    "state/.looptimum.lock",
    "state/report.json",
    "state/report.md",
    "examples/_demo_result.json",
)


def _prepare_variant_copy(
    tmp_path: Path,
    variant: str,
    *,
    target_name: str,
) -> Path:
    src = TEMPLATES_ROOT / variant
    dst = tmp_path / target_name
    shutil.copytree(src, dst)
    shared_src = TEMPLATES_ROOT / "_shared"
    if shared_src.exists():
        shutil.copytree(shared_src, tmp_path / "_shared", dirs_exist_ok=True)
    for rel in STATE_ARTIFACT_FILES:
        path = dst / rel
        if path.exists():
            path.unlink()
    trials_dir = dst / "state" / "trials"
    if trials_dir.exists():
        shutil.rmtree(trials_dir)

    cfg_path = dst / "bo_config.json"
    cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
    feature_flags = dict(cfg.get("feature_flags", {}))
    feature_flags["enable_service_api_preview"] = True
    cfg["feature_flags"] = feature_flags
    cfg_path.write_text(json.dumps(cfg, indent=2), encoding="utf-8")
    return dst


def _run_cli(project_root: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "run_bo.py", *args],
        cwd=project_root,
        text=True,
        capture_output=True,
        check=True,
    )


def _primary_objective_name(project_root: Path) -> str:
    payload = json.loads((project_root / "objective_schema.json").read_text(encoding="utf-8"))
    return str(payload["primary_objective"]["name"])


def _ok_result_payload(
    project_root: Path, suggestion: dict[str, object], value: float
) -> dict[str, object]:
    objective_name = _primary_objective_name(project_root)
    return {
        "trial_id": suggestion["trial_id"],
        "params": suggestion["params"],
        "status": "ok",
        "objectives": {objective_name: value},
    }


@pytest.mark.parametrize("variant", VARIANTS)
def test_dashboard_read_models_match_runtime_artifacts_across_variants(
    tmp_path: Path, variant: str
) -> None:
    project_root = _prepare_variant_copy(tmp_path, variant, target_name=f"{variant}_dashboard")
    registry_file = tmp_path / "service_state" / "campaign_registry.json"
    app = create_app(build_service_config(registry_file))

    with TestClient(app) as client:
        created = client.post("/campaigns", json={"root_path": str(project_root)}).json()
        campaign_id = created["campaign_id"]
        suggest_response = client.post(
            f"/campaigns/{campaign_id}/suggest",
            json={"count": 2},
        )
        assert suggest_response.status_code == 200
        suggestions = suggest_response.json()["suggestions"]

        ingest_response = client.post(
            f"/campaigns/{campaign_id}/ingest",
            json={"payload": _ok_result_payload(project_root, suggestions[0], 0.25)},
        )
        trials_response = client.get(f"/campaigns/{campaign_id}/trials")
        detail_response = client.get(f"/campaigns/{campaign_id}/trials/1")
        missing_trial_response = client.get(f"/campaigns/{campaign_id}/trials/99")
        best_timeseries_response = client.get(f"/campaigns/{campaign_id}/timeseries/best")
        alerts_response = client.get(f"/campaigns/{campaign_id}/alerts")
        decision_trace_response = client.get(f"/campaigns/{campaign_id}/decision-trace")

    assert ingest_response.status_code == 200
    assert trials_response.status_code == 200
    trials_payload = trials_response.json()
    assert trials_payload["count"] == 2
    assert trials_payload["counts"]["pending"] == 1
    assert trials_payload["counts"]["terminal"] == 1
    assert [row["trial_id"] for row in trials_payload["trials"]] == [2, 1]
    assert [row["status"] for row in trials_payload["trials"]] == ["pending", "ok"]
    assert trials_payload["trials"][0]["is_pending"] is True
    assert trials_payload["trials"][0]["pending_age_seconds"] is not None
    assert (
        trials_payload["trials"][1]["artifact_path"] == "state/trials/trial_1/ingest_payload.json"
    )

    assert detail_response.status_code == 200
    detail_payload = detail_response.json()
    assert detail_payload["trial"]["trial_id"] == 1
    assert detail_payload["trial"]["status"] == "ok"
    assert detail_payload["trial"]["has_manifest"] is True
    assert detail_payload["trial"]["manifest_path"] == "state/trials/trial_1/manifest.json"
    assert detail_payload["decision"]["trial_id"] == 1

    assert missing_trial_response.status_code == 404
    assert missing_trial_response.json()["error"]["code"] == "trial_not_found"

    assert best_timeseries_response.status_code == 200
    best_timeseries_payload = best_timeseries_response.json()
    assert best_timeseries_payload["points"] == [
        {
            "trial_id": 1,
            "completed_at": detail_payload["trial"]["completed_at"],
            "objective_name": _primary_objective_name(project_root),
            "objective_value": 0.25,
            "objective_vector": {_primary_objective_name(project_root): 0.25},
            "scalarized_objective": 0.25,
            "is_improvement": True,
            "best_trial_id": 1,
            "best_objective_name": "loss",
            "best_objective_value": 0.25,
        }
    ]
    assert best_timeseries_payload["ignored_trial_ids"] == []

    assert alerts_response.status_code == 200
    alerts_payload = alerts_response.json()
    assert alerts_payload["pending_count"] == 1
    assert alerts_payload["pending_trial_ids"] == [2]
    assert alerts_payload["stale_pending_count"] == 0
    assert alerts_payload["report_available"] is False
    assert alerts_payload["decision_trace_available"] is True

    assert decision_trace_response.status_code == 200
    decision_trace_payload = decision_trace_response.json()
    assert decision_trace_payload["available"] is True
    assert decision_trace_payload["count"] == 2
    assert [row["trial_id"] for row in decision_trace_payload["entries"]] == [1, 2]


def test_dashboard_exports_and_decision_trace_error_posture(tmp_path: Path) -> None:
    project_root = _prepare_variant_copy(tmp_path, "bo_client_demo", target_name="demo_exports")
    registry_file = tmp_path / "service_state" / "campaign_registry.json"
    app = create_app(build_service_config(registry_file))

    with TestClient(app) as client:
        created = client.post("/campaigns", json={"root_path": str(project_root)}).json()
        campaign_id = created["campaign_id"]

        empty_trace = client.get(f"/campaigns/{campaign_id}/decision-trace")
        missing_trace_export = client.get(f"/campaigns/{campaign_id}/exports/decision-trace.jsonl")
        missing_report_json = client.get(f"/campaigns/{campaign_id}/exports/report.json")
        missing_report_md = client.get(f"/campaigns/{campaign_id}/exports/report.md")

        suggest_response = client.post(f"/campaigns/{campaign_id}/suggest", json={"count": 2})
        suggestion = suggest_response.json()["suggestions"][0]
        ingest_response = client.post(
            f"/campaigns/{campaign_id}/ingest",
            json={"payload": _ok_result_payload(project_root, suggestion, 0.15)},
        )

    assert empty_trace.status_code == 200
    assert empty_trace.json() == {
        "available": False,
        "count": 0,
        "path": "state/acquisition_log.jsonl",
        "entries": [],
    }
    assert missing_trace_export.status_code == 404
    assert missing_trace_export.json()["error"]["code"] == "decision_trace_not_generated"
    assert missing_report_json.status_code == 404
    assert missing_report_json.json()["error"]["code"] == "report_not_generated"
    assert missing_report_md.status_code == 404
    assert missing_report_md.json()["error"]["code"] == "report_not_generated"
    assert ingest_response.status_code == 200

    _run_cli(project_root, "report")

    expected_report_json = json.loads(
        (project_root / "state" / "report.json").read_text(encoding="utf-8")
    )
    expected_report_md = (project_root / "state" / "report.md").read_text(encoding="utf-8")
    expected_decision_trace = (project_root / "state" / "acquisition_log.jsonl").read_text(
        encoding="utf-8"
    )

    with TestClient(app) as client:
        report_json_response = client.get(f"/campaigns/{campaign_id}/exports/report.json")
        report_md_response = client.get(f"/campaigns/{campaign_id}/exports/report.md")
        decision_trace_response = client.get(f"/campaigns/{campaign_id}/decision-trace")
        decision_trace_export = client.get(f"/campaigns/{campaign_id}/exports/decision-trace.jsonl")

    assert report_json_response.status_code == 200
    assert report_json_response.json() == expected_report_json
    assert report_json_response.headers["content-disposition"] == (
        f'attachment; filename="{campaign_id}-report.json"'
    )

    assert report_md_response.status_code == 200
    assert report_md_response.text == expected_report_md
    assert report_md_response.headers["content-disposition"] == (
        f'attachment; filename="{campaign_id}-report.md"'
    )

    assert decision_trace_response.status_code == 200
    assert decision_trace_response.json()["count"] == 2

    assert decision_trace_export.status_code == 200
    assert decision_trace_export.text == expected_decision_trace
    assert decision_trace_export.headers["content-disposition"] == (
        f'attachment; filename="{campaign_id}-decision-trace.jsonl"'
    )


def test_dashboard_alerts_surface_stale_pending_trials(tmp_path: Path) -> None:
    project_root = _prepare_variant_copy(tmp_path, "bo_client_demo", target_name="demo_stale")
    registry_file = tmp_path / "service_state" / "campaign_registry.json"
    app = create_app(build_service_config(registry_file))

    with TestClient(app) as client:
        created = client.post("/campaigns", json={"root_path": str(project_root)}).json()
        campaign_id = created["campaign_id"]
        suggest_response = client.post(f"/campaigns/{campaign_id}/suggest", json={})

    assert suggest_response.status_code == 200
    state_path = project_root / "state" / "bo_state.json"
    state_payload = json.loads(state_path.read_text(encoding="utf-8"))
    state_payload["pending"][0]["suggested_at"] = time.time() - 200_000.0
    state_path.write_text(json.dumps(state_payload, indent=2), encoding="utf-8")

    with TestClient(app) as client:
        alerts_response = client.get(f"/campaigns/{campaign_id}/alerts")

    assert alerts_response.status_code == 200
    assert alerts_response.json()["stale_pending_count"] == 1
    assert alerts_response.json()["stale_pending_trial_ids"] == [1]


def test_dashboard_endpoints_fail_if_preview_flag_is_disabled_after_registration(
    tmp_path: Path,
) -> None:
    project_root = _prepare_variant_copy(tmp_path, "bo_client_demo", target_name="demo_revoked")
    registry_file = tmp_path / "service_state" / "campaign_registry.json"
    app = create_app(build_service_config(registry_file))

    with TestClient(app) as client:
        created = client.post("/campaigns", json={"root_path": str(project_root)}).json()

    cfg_path = project_root / "bo_config.json"
    cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
    cfg["feature_flags"]["enable_service_api_preview"] = False
    cfg_path.write_text(json.dumps(cfg, indent=2), encoding="utf-8")

    with TestClient(app) as client:
        trials_response = client.get(f"/campaigns/{created['campaign_id']}/trials")
        decision_trace_export = client.get(
            f"/campaigns/{created['campaign_id']}/exports/decision-trace.jsonl"
        )

    assert trials_response.status_code == 403
    assert trials_response.json()["error"]["code"] == "service_preview_disabled"
    assert decision_trace_export.status_code == 403
    assert decision_trace_export.json()["error"]["code"] == "service_preview_disabled"
