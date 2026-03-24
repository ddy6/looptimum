from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

from fastapi.testclient import TestClient

from service.app import create_app
from service.config import (
    ServiceConfigError,
    build_service_config,
    build_service_coordination_config,
)
from service.coordination import FileLockCoordinationBackend, SQLiteLeaseCoordinationBackend

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
    service_enabled: bool = True,
    multi_controller_enabled: bool = False,
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
                    "enable_multi_controller_preview": multi_controller_enabled,
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
    multi_controller_enabled: bool,
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
    feature_flags["enable_multi_controller_preview"] = multi_controller_enabled
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


def test_build_service_coordination_config_defaults_to_file_lock(tmp_path: Path) -> None:
    registry_file = tmp_path / "service_state" / "campaign_registry.json"

    config = build_service_coordination_config(registry_file)

    assert config.mode == "file_lock"
    assert config.sqlite_file == (registry_file.parent / "coordination.sqlite3").resolve()
    assert config.lease_ttl_seconds == 30.0


def test_build_service_coordination_config_rejects_invalid_mode(tmp_path: Path) -> None:
    registry_file = tmp_path / "service_state" / "campaign_registry.json"

    try:
        build_service_coordination_config(registry_file, coordination_mode="redis")
    except ServiceConfigError as exc:
        assert "service coordination mode must be one of: file_lock, sqlite_lease" in str(exc)
    else:
        raise AssertionError("expected invalid coordination mode to raise ServiceConfigError")


def test_create_app_exposes_selected_coordination_backend(tmp_path: Path) -> None:
    registry_file = tmp_path / "service_state" / "campaign_registry.json"
    app = create_app(
        build_service_config(
            registry_file,
            coordination_mode="sqlite_lease",
            coordination_lease_ttl_seconds=45.0,
        )
    )

    backend = app.state.coordination_backend
    assert isinstance(backend, SQLiteLeaseCoordinationBackend)
    assert backend.mode == "sqlite_lease"
    assert backend.requires_campaign_opt_in is True
    assert backend.sqlite_file == (registry_file.parent / "coordination.sqlite3").resolve()
    assert backend.lease_ttl_seconds == 45.0


def test_default_file_lock_mode_does_not_require_multi_controller_flag(tmp_path: Path) -> None:
    registry_file = tmp_path / "service_state" / "campaign_registry.json"
    campaign_root = tmp_path / "campaigns" / "preview-root"
    _write_campaign_root(campaign_root, multi_controller_enabled=False)

    app = create_app(build_service_config(registry_file))
    assert isinstance(app.state.coordination_backend, FileLockCoordinationBackend)

    with TestClient(app) as client:
        response = client.post("/campaigns", json={"root_path": str(campaign_root)})

    assert response.status_code == 201
    assert response.json()["campaign_id"] == "preview-root"


def test_sqlite_coordination_mode_requires_campaign_opt_in_on_registration(
    tmp_path: Path,
) -> None:
    registry_file = tmp_path / "service_state" / "campaign_registry.json"
    campaign_root = tmp_path / "campaigns" / "preview-root"
    _write_campaign_root(campaign_root, multi_controller_enabled=False)

    app = create_app(build_service_config(registry_file, coordination_mode="sqlite_lease"))

    with TestClient(app) as client:
        response = client.post("/campaigns", json={"root_path": str(campaign_root)})

    assert response.status_code == 403
    assert response.json() == {
        "error": {
            "code": "multi_controller_preview_disabled",
            "message": "Campaign root is not multi-controller-preview-enabled; set "
            "feature_flags.enable_multi_controller_preview=true before using coordinated preview routes",
        }
    }


def test_sqlite_coordination_mode_blocks_mutation_if_flag_is_revoked(tmp_path: Path) -> None:
    registry_file = tmp_path / "service_state" / "campaign_registry.json"
    project_root = _prepare_demo_campaign_root(
        tmp_path,
        target_name="preview-root",
        multi_controller_enabled=True,
    )
    app = create_app(build_service_config(registry_file, coordination_mode="sqlite_lease"))

    with TestClient(app) as client:
        created = client.post("/campaigns", json={"root_path": str(project_root)}).json()

    cfg_path = project_root / "bo_config.json"
    cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
    cfg["feature_flags"]["enable_multi_controller_preview"] = False
    cfg_path.write_text(json.dumps(cfg, indent=2), encoding="utf-8")

    with TestClient(app) as client:
        response = client.post(f"/campaigns/{created['campaign_id']}/suggest")

    assert response.status_code == 403
    assert response.json() == {
        "error": {
            "code": "multi_controller_preview_disabled",
            "message": "Campaign root is not multi-controller-preview-enabled; set "
            "feature_flags.enable_multi_controller_preview=true before using coordinated preview routes",
        }
    }


def test_sqlite_coordination_mode_preserves_mutation_behavior_when_opted_in(tmp_path: Path) -> None:
    registry_file = tmp_path / "service_state" / "campaign_registry.json"
    service_project_root = _prepare_demo_campaign_root(
        tmp_path,
        target_name="preview-root-service",
        multi_controller_enabled=True,
    )
    cli_project_root = _prepare_demo_campaign_root(
        tmp_path,
        target_name="preview-root-cli",
        multi_controller_enabled=True,
    )
    app = create_app(build_service_config(registry_file, coordination_mode="sqlite_lease"))

    with TestClient(app) as client:
        created = client.post("/campaigns", json={"root_path": str(service_project_root)}).json()
        suggest_response = client.post(f"/campaigns/{created['campaign_id']}/suggest")

    assert suggest_response.status_code == 200
    service_payload = suggest_response.json()
    cli_payload = json.loads(_run_cli(cli_project_root, "suggest", "--json-only").stdout)
    assert service_payload["trial_id"] == cli_payload["trial_id"]
    assert service_payload["params"] == cli_payload["params"]
