from __future__ import annotations

import base64
import json
import shutil
from pathlib import Path

from fastapi.testclient import TestClient

from service.app import create_app
from service.config import build_service_config

REPO_ROOT = Path(__file__).resolve().parents[2]
TEMPLATES_ROOT = REPO_ROOT / "templates"
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


def _write_campaign_root(
    root: Path,
    *,
    auth_enabled: bool = True,
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
                    "enable_service_api_preview": True,
                    "enable_dashboard_preview": dashboard_enabled,
                    "enable_auth_preview": auth_enabled,
                }
            },
            indent=2,
        ),
        encoding="utf-8",
    )


def _prepare_demo_campaign_root(
    tmp_path: Path,
    *,
    target_name: str,
    auth_enabled: bool = True,
    dashboard_enabled: bool = True,
) -> Path:
    src = TEMPLATES_ROOT / "bo_client_demo"
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
    feature_flags["enable_dashboard_preview"] = dashboard_enabled
    feature_flags["enable_auth_preview"] = auth_enabled
    cfg["feature_flags"] = feature_flags
    cfg_path.write_text(json.dumps(cfg, indent=2), encoding="utf-8")
    return dst


def _basic_auth_header(username: str, password: str) -> dict[str, str]:
    token = base64.b64encode(f"{username}:{password}".encode("utf-8")).decode("ascii")
    return {"Authorization": f"Basic {token}"}


def _read_audit_events(path: Path) -> list[dict[str, object]]:
    if not path.exists():
        return []
    events: list[dict[str, object]] = []
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        if not raw_line.strip():
            continue
        events.append(json.loads(raw_line))
    return events


def _build_auth_app(tmp_path: Path) -> tuple[TestClient, Path]:
    registry_file = tmp_path / "service_state" / "campaign_registry.json"
    app = create_app(
        build_service_config(
            registry_file,
            auth_mode="basic",
            auth_users=[
                {"username": "viewer", "password": "viewer-secret", "role": "viewer"},
                {"username": "operator", "password": "operator-secret", "role": "operator"},
                {"username": "admin", "password": "admin-secret", "role": "admin"},
            ],
        )
    )
    return TestClient(app), registry_file.parent / "auth_audit_log.jsonl"


def test_viewer_can_read_but_cannot_suggest_and_denial_is_audited(tmp_path: Path) -> None:
    campaign_root = _prepare_demo_campaign_root(
        tmp_path,
        target_name="preview-root",
        auth_enabled=True,
    )
    client, audit_log = _build_auth_app(tmp_path)

    with client:
        create_response = client.post(
            "/campaigns",
            json={"root_path": str(campaign_root)},
            headers=_basic_auth_header("admin", "admin-secret"),
        )
        assert create_response.status_code == 201

        status_response = client.get(
            "/campaigns/preview-root/status",
            headers=_basic_auth_header("viewer", "viewer-secret"),
        )
        suggest_response = client.post(
            "/campaigns/preview-root/suggest",
            headers=_basic_auth_header("viewer", "viewer-secret"),
        )

    assert status_response.status_code == 200
    assert suggest_response.status_code == 403
    assert suggest_response.json()["error"]["code"] == "insufficient_role"

    events = _read_audit_events(audit_log)
    assert any(
        event["event_type"] == "authz_failure"
        and event["username"] == "viewer"
        and event["role"] == "viewer"
        and event["campaign_id"] == "preview-root"
        and event["action"] == "route_access"
        and event["reason"] == "requires_role=operator"
        for event in events
    )


def test_operator_cannot_reset_and_admin_privileged_action_is_audited(tmp_path: Path) -> None:
    campaign_root = _prepare_demo_campaign_root(
        tmp_path,
        target_name="preview-root",
        auth_enabled=True,
    )
    client, audit_log = _build_auth_app(tmp_path)

    with client:
        create_response = client.post(
            "/campaigns",
            json={"root_path": str(campaign_root)},
            headers=_basic_auth_header("admin", "admin-secret"),
        )
        assert create_response.status_code == 201

        suggest_response = client.post(
            "/campaigns/preview-root/suggest",
            headers=_basic_auth_header("operator", "operator-secret"),
        )
        reset_response = client.post(
            "/campaigns/preview-root/reset",
            json={"yes": True},
            headers=_basic_auth_header("operator", "operator-secret"),
        )

    assert suggest_response.status_code == 200
    assert reset_response.status_code == 403
    assert reset_response.json()["error"]["code"] == "insufficient_role"

    events = _read_audit_events(audit_log)
    assert any(
        event["event_type"] == "privileged_action"
        and event["username"] == "admin"
        and event["action"] == "register_campaign"
        and event["outcome"] == "allowed"
        and event["campaign_id"] == "preview-root"
        for event in events
    )
    assert any(
        event["event_type"] == "authz_failure"
        and event["username"] == "operator"
        and event["campaign_id"] == "preview-root"
        and event["reason"] == "requires_role=admin"
        for event in events
    )


def test_auth_preview_flag_is_required_for_registration_when_auth_is_enabled(
    tmp_path: Path,
) -> None:
    campaign_root = tmp_path / "campaigns" / "auth-disabled-root"
    _write_campaign_root(campaign_root, auth_enabled=False)
    client, audit_log = _build_auth_app(tmp_path)

    with client:
        response = client.post(
            "/campaigns",
            json={"root_path": str(campaign_root)},
            headers=_basic_auth_header("admin", "admin-secret"),
        )

    assert response.status_code == 403
    assert response.json() == {
        "error": {
            "code": "auth_preview_disabled",
            "message": "Campaign root is not auth-preview-enabled; set "
            "feature_flags.enable_auth_preview=true before using auth-protected preview routes",
        }
    }

    events = _read_audit_events(audit_log)
    assert any(
        event["event_type"] == "authz_failure"
        and event["username"] == "admin"
        and event["action"] == "campaign_auth_preview_validation"
        and event["reason"] == "campaign_auth_preview_disabled"
        and event["outcome"] == "denied"
        for event in events
    )


def test_auth_preview_flag_revocation_blocks_existing_campaign_access_and_is_audited(
    tmp_path: Path,
) -> None:
    campaign_root = _prepare_demo_campaign_root(
        tmp_path,
        target_name="preview-root",
        auth_enabled=True,
    )
    client, audit_log = _build_auth_app(tmp_path)

    with client:
        create_response = client.post(
            "/campaigns",
            json={"root_path": str(campaign_root)},
            headers=_basic_auth_header("admin", "admin-secret"),
        )
        assert create_response.status_code == 201
        cfg_path = campaign_root / "bo_config.json"
        cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
        cfg["feature_flags"]["enable_auth_preview"] = False
        cfg_path.write_text(json.dumps(cfg, indent=2), encoding="utf-8")
        response = client.get(
            "/campaigns/preview-root/status",
            headers=_basic_auth_header("viewer", "viewer-secret"),
        )

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "auth_preview_disabled"

    events = _read_audit_events(audit_log)
    assert any(
        event["event_type"] == "authz_failure"
        and event["username"] == "viewer"
        and event["campaign_id"] == "preview-root"
        and event["action"] == "campaign_auth_preview_validation"
        and event["reason"] == "campaign_auth_preview_disabled"
        for event in events
    )
