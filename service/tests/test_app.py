from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from service.app import create_app
from service.config import SERVICE_REGISTRY_FILE_ENV, build_service_config


def _write_campaign_root(root: Path, *, service_enabled: bool = True) -> None:
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
                }
            },
            indent=2,
        ),
        encoding="utf-8",
    )


def test_health_uses_explicit_or_env_registry_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    registry_file = tmp_path / "custom-service-state" / "campaign_registry.json"
    monkeypatch.setenv(SERVICE_REGISTRY_FILE_ENV, str(registry_file))

    with TestClient(create_app()) as client:
        response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {
        "ok": True,
        "preview": "service_api_preview",
        "registry_file": str(registry_file.resolve()),
        "campaign_count": 0,
    }


def test_campaign_registration_round_trip_over_http(tmp_path: Path) -> None:
    registry_file = tmp_path / "service_state" / "campaign_registry.json"
    campaign_root = tmp_path / "campaigns" / "preview-root"
    _write_campaign_root(campaign_root)

    app = create_app(build_service_config(registry_file))
    with TestClient(app) as client:
        create_response = client.post(
            "/campaigns",
            json={"root_path": str(campaign_root), "label": "Preview Root"},
        )
        assert create_response.status_code == 201
        created = create_response.json()
        assert created["campaign_id"] == "preview-root"
        assert created["label"] == "Preview Root"
        assert created["root_path"] == str(campaign_root.resolve())

        list_response = client.get("/campaigns")
        assert list_response.status_code == 200
        assert list_response.json() == {"campaigns": [created]}

        detail_response = client.get("/campaigns/preview-root")
        assert detail_response.status_code == 200
        assert detail_response.json() == created

        health_response = client.get("/health")
        assert health_response.status_code == 200
        assert health_response.json()["campaign_count"] == 1


def test_campaign_registration_returns_machine_readable_preview_error(tmp_path: Path) -> None:
    registry_file = tmp_path / "service_state" / "campaign_registry.json"
    disabled_root = tmp_path / "campaigns" / "preview-disabled"
    _write_campaign_root(disabled_root, service_enabled=False)

    app = create_app(build_service_config(registry_file))
    with TestClient(app) as client:
        response = client.post("/campaigns", json={"root_path": str(disabled_root)})

    assert response.status_code == 403
    assert response.json() == {
        "error": {
            "code": "service_preview_disabled",
            "message": "Campaign root is not service-enabled; set "
            "feature_flags.enable_service_api_preview=true before registration",
        }
    }


def test_get_missing_campaign_returns_machine_readable_404(tmp_path: Path) -> None:
    app = create_app(build_service_config(tmp_path / "service_state" / "campaign_registry.json"))
    with TestClient(app) as client:
        response = client.get("/campaigns/missing")

    assert response.status_code == 404
    assert response.json() == {
        "error": {
            "code": "campaign_not_found",
            "message": "campaign not found: missing",
        }
    }
