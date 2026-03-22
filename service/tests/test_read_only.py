from __future__ import annotations

import json
import shutil
import subprocess
import sys
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


def _prepare_variant_copy(tmp_path: Path, variant: str) -> Path:
    src = TEMPLATES_ROOT / variant
    dst = tmp_path / variant
    shutil.copytree(src, dst)
    shared_src = TEMPLATES_ROOT / "_shared"
    if shared_src.exists():
        shutil.copytree(shared_src, tmp_path / "_shared")
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


@pytest.mark.parametrize("variant", VARIANTS)
def test_status_endpoint_matches_cli_status_payload(tmp_path: Path, variant: str) -> None:
    project_root = _prepare_variant_copy(tmp_path, variant)
    registry_file = tmp_path / "service_state" / "campaign_registry.json"
    app = create_app(build_service_config(registry_file))

    with TestClient(app) as client:
        created = client.post("/campaigns", json={"root_path": str(project_root)}).json()
        response = client.get(f"/campaigns/{created['campaign_id']}/status")

    assert response.status_code == 200
    assert response.json() == json.loads(_run_cli(project_root, "status").stdout)


@pytest.mark.parametrize("variant", VARIANTS)
def test_report_endpoint_reads_canonical_report_artifact_and_detail_tracks_presence(
    tmp_path: Path, variant: str
) -> None:
    project_root = _prepare_variant_copy(tmp_path, variant)
    registry_file = tmp_path / "service_state" / "campaign_registry.json"
    app = create_app(build_service_config(registry_file))

    with TestClient(app) as client:
        created = client.post(
            "/campaigns",
            json={"root_path": str(project_root), "label": f"{variant} preview"},
        ).json()
        campaign_id = created["campaign_id"]

        missing_report = client.get(f"/campaigns/{campaign_id}/report")
        assert missing_report.status_code == 404
        assert missing_report.json() == {
            "error": {
                "code": "report_not_generated",
                "message": f"report.json has not been generated for campaign root: {project_root.resolve()}",
            }
        }

        before_detail = client.get(f"/campaigns/{campaign_id}/detail")
        assert before_detail.status_code == 200
        assert before_detail.json()["artifacts"]["report_json_exists"] is False
        assert before_detail.json()["artifacts"]["report_md_exists"] is False
        assert before_detail.json()["status"] == json.loads(_run_cli(project_root, "status").stdout)

    _run_cli(project_root, "report")
    expected_report = json.loads(
        (project_root / "state" / "report.json").read_text(encoding="utf-8")
    )

    with TestClient(app) as client:
        report_response = client.get(f"/campaigns/{campaign_id}/report")
        detail_response = client.get(f"/campaigns/{campaign_id}/detail")

    assert report_response.status_code == 200
    assert report_response.json() == expected_report
    assert detail_response.status_code == 200
    assert detail_response.json()["artifacts"]["report_json_exists"] is True
    assert detail_response.json()["paths"]["report_json_file"] == "state/report.json"


def test_read_only_endpoints_fail_if_preview_flag_is_disabled_after_registration(
    tmp_path: Path,
) -> None:
    project_root = _prepare_variant_copy(tmp_path, "bo_client_demo")
    registry_file = tmp_path / "service_state" / "campaign_registry.json"
    app = create_app(build_service_config(registry_file))

    with TestClient(app) as client:
        created = client.post("/campaigns", json={"root_path": str(project_root)}).json()

    cfg_path = project_root / "bo_config.json"
    cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
    cfg["feature_flags"]["enable_service_api_preview"] = False
    cfg_path.write_text(json.dumps(cfg, indent=2), encoding="utf-8")

    with TestClient(app) as client:
        response = client.get(f"/campaigns/{created['campaign_id']}/status")

    assert response.status_code == 403
    assert response.json() == {
        "error": {
            "code": "service_preview_disabled",
            "message": "Campaign root is not service-enabled; set "
            "feature_flags.enable_service_api_preview=true before registration",
        }
    }
