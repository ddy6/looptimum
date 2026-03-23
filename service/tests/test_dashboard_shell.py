from __future__ import annotations

import json
from pathlib import Path

from fastapi.testclient import TestClient

from service.app import create_app
from service.config import build_service_config


def _write_campaign_root(
    root: Path,
    *,
    service_enabled: bool = True,
    dashboard_enabled: bool = True,
) -> None:
    root.mkdir(parents=True, exist_ok=True)
    (root / "run_bo.py").write_text("# preview runtime entrypoint\n", encoding="utf-8")
    (root / "parameter_space.json").write_text(
        json.dumps(
            {"params": [{"name": "x", "type": "float", "bounds": [0.0, 1.0]}], "version": 2}
        ),
        encoding="utf-8",
    )
    (root / "objective_schema.json").write_text(
        json.dumps({"primary_objective": {"name": "loss", "goal": "minimize"}}),
        encoding="utf-8",
    )
    (root / "bo_config.json").write_text(
        json.dumps(
            {
                "feature_flags": {
                    "enable_service_api_preview": service_enabled,
                    "enable_dashboard_preview": dashboard_enabled,
                }
            },
            indent=2,
        ),
        encoding="utf-8",
    )


def test_dashboard_root_serves_preview_shell_and_assets(tmp_path: Path) -> None:
    app = create_app(build_service_config(tmp_path / "service_state" / "campaign_registry.json"))

    with TestClient(app) as client:
        shell_response = client.get("/dashboard")
        css_response = client.get("/dashboard/assets/dashboard.css")
        js_response = client.get("/dashboard/assets/dashboard.js")

    assert shell_response.status_code == 200
    assert shell_response.headers["content-type"].startswith("text/html")
    assert "Looptimum Dashboard Preview" in shell_response.text
    assert 'data-current-campaign-id=""' in shell_response.text
    assert "/dashboard/assets/dashboard.css" in shell_response.text
    assert "/dashboard/assets/dashboard.js" in shell_response.text
    assert "Service UI Preview" in shell_response.text
    assert "campaign-list-panel" in shell_response.text
    assert "campaign-detail-panel" in shell_response.text
    assert "best-timeseries-panel" in shell_response.text
    assert "trial-list-panel" in shell_response.text
    assert "trial-detail-panel" in shell_response.text
    assert "decision-trace-panel" in shell_response.text
    assert "export-actions-panel" in shell_response.text
    assert 'aria-live="polite"' in shell_response.text
    assert 'aria-label="Registered campaigns"' in shell_response.text
    assert 'aria-label="Best over time chart"' in shell_response.text
    assert 'aria-disabled="true"' in shell_response.text

    assert css_response.status_code == 200
    assert css_response.headers["content-type"].startswith("text/css")
    assert ".dashboard-shell" in css_response.text
    assert ".preview-chip" in css_response.text
    assert ".timeseries-chart" in css_response.text
    assert ".trial-button" in css_response.text
    assert "@media (max-width: 960px)" in css_response.text

    assert js_response.status_code == 200
    assert js_response.headers["content-type"].startswith("text/javascript")
    assert 'fetchJson(config.healthPath || "/health")' in js_response.text
    assert 'fetchJson(config.campaignsPath || "/campaigns")' in js_response.text
    assert "fetchJson(`/campaigns/${currentCampaignId}/detail`)" in js_response.text
    assert "fetchJson(`/campaigns/${currentCampaignId}/alerts`)" in js_response.text
    assert "fetchJson(`/campaigns/${currentCampaignId}/timeseries/best`)" in js_response.text
    assert "fetchJson(`/campaigns/${currentCampaignId}/trials`)" in js_response.text
    assert "fetchJson(`/campaigns/${currentCampaignId}/decision-trace`)" in js_response.text
    assert "fetchJson(`/campaigns/${currentCampaignId}/trials/${trialId}`)" in js_response.text
    assert "/exports/report.json" in js_response.text
    assert "/exports/report.md" in js_response.text
    assert "/exports/decision-trace.jsonl" in js_response.text
    assert 'button.type = "button"' in js_response.text


def test_dashboard_campaign_route_binds_current_campaign_id(tmp_path: Path) -> None:
    registry_file = tmp_path / "service_state" / "campaign_registry.json"
    campaign_root = tmp_path / "campaigns" / "preview-root"
    _write_campaign_root(campaign_root)

    app = create_app(build_service_config(registry_file))
    with TestClient(app) as client:
        create_response = client.post("/campaigns", json={"root_path": str(campaign_root)})
        assert create_response.status_code == 201

        shell_response = client.get("/dashboard/campaigns/preview-root")

    assert shell_response.status_code == 200
    assert 'data-current-campaign-id="preview-root"' in shell_response.text
    assert "Read-only operator shell over the preview API." in shell_response.text
    assert "Recent Decision Trace" in shell_response.text
    assert "Trial Detail" in shell_response.text


def test_dashboard_campaign_route_returns_json_404_for_unknown_campaign(tmp_path: Path) -> None:
    app = create_app(build_service_config(tmp_path / "service_state" / "campaign_registry.json"))

    with TestClient(app) as client:
        response = client.get("/dashboard/campaigns/missing")

    assert response.status_code == 404
    assert response.json() == {
        "error": {
            "code": "campaign_not_found",
            "message": "campaign not found: missing",
        }
    }


def test_dashboard_campaign_route_fails_if_preview_flag_is_revoked(tmp_path: Path) -> None:
    registry_file = tmp_path / "service_state" / "campaign_registry.json"
    campaign_root = tmp_path / "campaigns" / "preview-root"
    _write_campaign_root(campaign_root)

    app = create_app(build_service_config(registry_file))
    with TestClient(app) as client:
        create_response = client.post("/campaigns", json={"root_path": str(campaign_root)})
        assert create_response.status_code == 201

    cfg_path = campaign_root / "bo_config.json"
    cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
    cfg["feature_flags"]["enable_service_api_preview"] = False
    cfg_path.write_text(json.dumps(cfg, indent=2), encoding="utf-8")

    with TestClient(app) as client:
        response = client.get("/dashboard/campaigns/preview-root")

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "service_preview_disabled"


def test_dashboard_campaign_route_fails_if_dashboard_flag_is_revoked(tmp_path: Path) -> None:
    registry_file = tmp_path / "service_state" / "campaign_registry.json"
    campaign_root = tmp_path / "campaigns" / "preview-root"
    _write_campaign_root(campaign_root)

    app = create_app(build_service_config(registry_file))
    with TestClient(app) as client:
        create_response = client.post("/campaigns", json={"root_path": str(campaign_root)})
        assert create_response.status_code == 201

    cfg_path = campaign_root / "bo_config.json"
    cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
    cfg["feature_flags"]["enable_dashboard_preview"] = False
    cfg_path.write_text(json.dumps(cfg, indent=2), encoding="utf-8")

    with TestClient(app) as client:
        response = client.get("/dashboard/campaigns/preview-root")

    assert response.status_code == 403
    assert response.json() == {
        "error": {
            "code": "dashboard_preview_disabled",
            "message": "Campaign root is not dashboard-enabled; set "
            "feature_flags.enable_dashboard_preview=true before using the preview dashboard",
        }
    }
