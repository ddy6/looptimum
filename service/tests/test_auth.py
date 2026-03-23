from __future__ import annotations

import base64
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from service.app import create_app
from service.auth import resolve_local_dev_principal
from service.config import ServiceConfigError, build_service_auth_config, build_service_config
from service.models import LocalAuthUser


def _write_campaign_root(root: Path, *, auth_enabled: bool = True) -> None:
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
                    "enable_auth_preview": auth_enabled,
                }
            },
            indent=2,
        ),
        encoding="utf-8",
    )


def _basic_auth_header(username: str, password: str) -> dict[str, str]:
    token = base64.b64encode(f"{username}:{password}".encode("utf-8")).decode("ascii")
    return {"Authorization": f"Basic {token}"}


def _bearer_auth_header(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _encode_jwt_segment(payload: dict[str, object]) -> str:
    raw = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _oidc_test_token(*, sub: str, iss: str, aud: str, roles: list[str]) -> str:
    header = _encode_jwt_segment({"alg": "none", "typ": "JWT"})
    payload = _encode_jwt_segment({"sub": sub, "iss": iss, "aud": aud, "roles": roles})
    return f"{header}.{payload}."


def test_build_service_auth_config_defaults_to_disabled_mode() -> None:
    config = build_service_auth_config()

    assert config.mode == "disabled"
    assert config.local_users == ()


def test_build_service_auth_config_rejects_basic_mode_without_users() -> None:
    with pytest.raises(
        ServiceConfigError, match="basic service auth mode requires at least one configured user"
    ):
        build_service_auth_config(auth_mode="basic")


def test_build_service_auth_config_rejects_oidc_mode_without_config() -> None:
    with pytest.raises(
        ServiceConfigError, match="oidc service auth mode requires explicit OIDC config"
    ):
        build_service_auth_config(auth_mode="oidc")


def test_build_service_auth_config_rejects_duplicate_usernames() -> None:
    with pytest.raises(ServiceConfigError, match="duplicates: preview-user"):
        build_service_auth_config(
            auth_mode="basic",
            auth_users=[
                {"username": "preview-user", "password": "secret-1", "role": "viewer"},
                {"username": "preview-user", "password": "secret-2", "role": "admin"},
            ],
        )


def test_health_stays_open_but_protected_routes_require_auth_when_preview_enabled(
    tmp_path: Path,
) -> None:
    registry_file = tmp_path / "service_state" / "campaign_registry.json"
    campaign_root = tmp_path / "campaigns" / "preview-root"
    _write_campaign_root(campaign_root)
    app = create_app(
        build_service_config(
            registry_file,
            auth_mode="basic",
            auth_users=[{"username": "viewer", "password": "secret", "role": "viewer"}],
        )
    )

    with TestClient(app) as client:
        health_response = client.get("/health")
        protected_response = client.post("/campaigns", json={"root_path": str(campaign_root)})

    assert health_response.status_code == 200
    assert protected_response.status_code == 401
    assert (
        protected_response.headers["www-authenticate"] == 'Basic realm="Looptimum Service Preview"'
    )
    assert protected_response.json() == {
        "error": {
            "code": "auth_required",
            "message": "Authentication is required for this preview route",
        }
    }


def test_protected_routes_accept_valid_basic_auth_and_reject_invalid_credentials(
    tmp_path: Path,
) -> None:
    registry_file = tmp_path / "service_state" / "campaign_registry.json"
    campaign_root = tmp_path / "campaigns" / "preview-root"
    _write_campaign_root(campaign_root)
    app = create_app(
        build_service_config(
            registry_file,
            auth_mode="basic",
            auth_users=[{"username": "admin", "password": "correct-horse", "role": "admin"}],
        )
    )

    with TestClient(app) as client:
        invalid_response = client.get(
            "/campaigns",
            headers=_basic_auth_header("admin", "wrong-battery"),
        )
        create_response = client.post(
            "/campaigns",
            json={"root_path": str(campaign_root)},
            headers=_basic_auth_header("admin", "correct-horse"),
        )
        list_response = client.get(
            "/campaigns",
            headers=_basic_auth_header("admin", "correct-horse"),
        )

    assert invalid_response.status_code == 401
    assert invalid_response.json() == {
        "error": {
            "code": "invalid_credentials",
            "message": "Authentication failed for the provided preview credentials",
        }
    }
    assert create_response.status_code == 201
    assert create_response.json()["campaign_id"] == "preview-root"
    assert list_response.status_code == 200
    assert list_response.json()["campaigns"][0]["campaign_id"] == "preview-root"


def test_resolve_local_dev_principal_returns_normalized_principal() -> None:
    auth_config = build_service_auth_config(
        auth_mode="basic",
        auth_users=[LocalAuthUser(username="admin", password="s3cr3t", role="admin")],
    )

    principal = resolve_local_dev_principal(
        auth_config,
        _basic_auth_header("admin", "s3cr3t")["Authorization"],
    )

    assert principal.username == "admin"
    assert principal.role == "admin"
    assert principal.auth_mode == "basic"


def test_oidc_bearer_routes_accept_valid_claims_and_map_roles(tmp_path: Path) -> None:
    registry_file = tmp_path / "service_state" / "campaign_registry.json"
    campaign_root = tmp_path / "campaigns" / "preview-root"
    _write_campaign_root(campaign_root)
    app = create_app(
        build_service_config(
            registry_file,
            auth_mode="oidc",
            oidc_config={
                "issuer": "https://issuer.example.test",
                "audience": "looptimum-preview",
                "role_mapping": {
                    "group:admins": "admin",
                    "group:viewers": "viewer",
                },
            },
        )
    )
    admin_token = _oidc_test_token(
        sub="admin@example.test",
        iss="https://issuer.example.test",
        aud="looptimum-preview",
        roles=["group:admins"],
    )
    viewer_token = _oidc_test_token(
        sub="viewer@example.test",
        iss="https://issuer.example.test",
        aud="looptimum-preview",
        roles=["group:viewers"],
    )

    with TestClient(app) as client:
        create_response = client.post(
            "/campaigns",
            json={"root_path": str(campaign_root)},
            headers=_bearer_auth_header(admin_token),
        )
        list_response = client.get(
            "/campaigns",
            headers=_bearer_auth_header(viewer_token),
        )

    assert create_response.status_code == 201
    assert create_response.json()["campaign_id"] == "preview-root"
    assert list_response.status_code == 200
    assert list_response.json()["campaigns"][0]["campaign_id"] == "preview-root"


def test_oidc_bearer_routes_reject_unmapped_roles_with_claim_error(tmp_path: Path) -> None:
    registry_file = tmp_path / "service_state" / "campaign_registry.json"
    app = create_app(
        build_service_config(
            registry_file,
            auth_mode="oidc",
            oidc_config={
                "issuer": "https://issuer.example.test",
                "audience": "looptimum-preview",
                "role_mapping": {"group:viewers": "viewer"},
            },
        )
    )
    token = _oidc_test_token(
        sub="mystery@example.test",
        iss="https://issuer.example.test",
        aud="looptimum-preview",
        roles=["group:unknown"],
    )

    with TestClient(app) as client:
        response = client.get("/campaigns", headers=_bearer_auth_header(token))

    assert response.status_code == 401
    assert response.headers["www-authenticate"] == 'Bearer realm="Looptimum Service Preview"'
    assert response.json() == {
        "error": {
            "code": "invalid_token_claims",
            "message": "OIDC bearer token roles did not map to a service role via claim 'roles'",
        }
    }
