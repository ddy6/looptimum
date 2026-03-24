from __future__ import annotations

import json
import shutil
import sqlite3
import subprocess
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
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


def _coordination_error_payload(campaign_id: str) -> dict[str, object]:
    return {
        "error": {
            "code": "coordination_unavailable",
            "message": f"service coordination lease unavailable for campaign {campaign_id!r}",
        }
    }


def _seed_expired_campaign_lease(sqlite_file: Path, campaign_id: str) -> None:
    sqlite_file.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(sqlite_file) as connection:
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS campaign_leases (
                campaign_id TEXT PRIMARY KEY,
                owner_token TEXT NOT NULL,
                acquired_at REAL NOT NULL,
                expires_at REAL NOT NULL
            )
            """
        )
        connection.execute(
            """
            INSERT OR REPLACE INTO campaign_leases (
                campaign_id,
                owner_token,
                acquired_at,
                expires_at
            )
            VALUES (?, ?, ?, ?)
            """,
            (
                campaign_id,
                "dead-controller",
                time.time() - 60.0,
                time.time() - 30.0,
            ),
        )
        connection.commit()


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


def test_sqlite_coordination_mode_fail_fast_when_controller_lease_is_held(tmp_path: Path) -> None:
    registry_file = tmp_path / "service_state" / "campaign_registry.json"
    project_root = _prepare_demo_campaign_root(
        tmp_path,
        target_name="preview-root-held-lease",
        multi_controller_enabled=True,
    )
    app = create_app(build_service_config(registry_file, coordination_mode="sqlite_lease"))

    with TestClient(app) as client:
        created = client.post("/campaigns", json={"root_path": str(project_root)}).json()

    backend = app.state.coordination_backend
    with backend.acquire_campaign_lease(
        created["campaign_id"],
        timeout_seconds=1.0,
        fail_fast=False,
    ):
        with TestClient(app) as client:
            response = client.post(
                f"/campaigns/{created['campaign_id']}/suggest",
                json={"fail_fast": True},
            )

    assert response.status_code == 409
    assert response.json() == _coordination_error_payload("preview-root-held-lease")


def test_sqlite_coordination_mode_serializes_parallel_suggest_requests(tmp_path: Path) -> None:
    registry_file = tmp_path / "service_state" / "campaign_registry.json"
    project_root = _prepare_demo_campaign_root(
        tmp_path,
        target_name="preview-root-concurrent",
        multi_controller_enabled=True,
    )
    app = create_app(build_service_config(registry_file, coordination_mode="sqlite_lease"))

    with TestClient(app) as client:
        created = client.post("/campaigns", json={"root_path": str(project_root)}).json()
    campaign_id = created["campaign_id"]

    worker_count = 3
    start_barrier = threading.Barrier(worker_count)

    def _issue_suggest() -> dict[str, object]:
        start_barrier.wait(timeout=5.0)
        with TestClient(app) as client:
            response = client.post(
                f"/campaigns/{campaign_id}/suggest",
                json={"lock_timeout_seconds": 5.0},
            )
        assert response.status_code == 200
        return response.json()

    with ThreadPoolExecutor(max_workers=worker_count) as executor:
        payloads = list(executor.map(lambda _index: _issue_suggest(), range(worker_count)))

    trial_ids = sorted(int(payload["trial_id"]) for payload in payloads)
    assert trial_ids == [1, 2, 3]

    with sqlite3.connect(registry_file.parent / "coordination.sqlite3") as connection:
        rows = connection.execute("SELECT campaign_id FROM campaign_leases").fetchall()
    assert rows == []

    with TestClient(app) as client:
        status_response = client.get(f"/campaigns/{campaign_id}/status")
    assert status_response.status_code == 200
    assert status_response.json()["pending"] == worker_count


def test_sqlite_coordination_mode_reclaims_expired_lease_on_suggest(tmp_path: Path) -> None:
    registry_file = tmp_path / "service_state" / "campaign_registry.json"
    project_root = _prepare_demo_campaign_root(
        tmp_path,
        target_name="preview-root-expired-lease",
        multi_controller_enabled=True,
    )
    app = create_app(
        build_service_config(
            registry_file,
            coordination_mode="sqlite_lease",
            coordination_lease_ttl_seconds=0.5,
        )
    )

    with TestClient(app) as client:
        created = client.post("/campaigns", json={"root_path": str(project_root)}).json()
        campaign_id = created["campaign_id"]

    _seed_expired_campaign_lease(registry_file.parent / "coordination.sqlite3", campaign_id)

    with TestClient(app) as client:
        response = client.post(
            f"/campaigns/{campaign_id}/suggest",
            json={"fail_fast": True},
        )

    assert response.status_code == 200
    assert response.json()["trial_id"] == 1

    with sqlite3.connect(registry_file.parent / "coordination.sqlite3") as connection:
        rows = connection.execute("SELECT campaign_id FROM campaign_leases").fetchall()
    assert rows == []


def test_sqlite_coordination_mode_blocks_ingest_when_controller_lease_is_held(
    tmp_path: Path,
) -> None:
    registry_file = tmp_path / "service_state" / "campaign_registry.json"
    project_root = _prepare_demo_campaign_root(
        tmp_path,
        target_name="preview-root-held-ingest",
        multi_controller_enabled=True,
    )
    app = create_app(build_service_config(registry_file, coordination_mode="sqlite_lease"))

    with TestClient(app) as client:
        created = client.post("/campaigns", json={"root_path": str(project_root)}).json()
        campaign_id = created["campaign_id"]
        suggestion = client.post(f"/campaigns/{campaign_id}/suggest").json()

    result_payload = {
        "trial_id": suggestion["trial_id"],
        "params": suggestion["params"],
        "status": "ok",
        "objectives": {"objective": 0.1},
    }
    objective_payload = json.loads(
        (project_root / "objective_schema.json").read_text(encoding="utf-8")
    )
    objective_name = objective_payload["primary_objective"]["name"]
    result_payload["objectives"] = {objective_name: 0.1}

    backend = app.state.coordination_backend
    with backend.acquire_campaign_lease(campaign_id, timeout_seconds=1.0, fail_fast=False):
        with TestClient(app) as client:
            response = client.post(
                f"/campaigns/{campaign_id}/ingest",
                json={"payload": result_payload, "fail_fast": True},
            )

    assert response.status_code == 409
    assert response.json() == _coordination_error_payload("preview-root-held-ingest")


def test_sqlite_coordination_mode_blocks_reset_when_controller_lease_is_held(
    tmp_path: Path,
) -> None:
    registry_file = tmp_path / "service_state" / "campaign_registry.json"
    project_root = _prepare_demo_campaign_root(
        tmp_path,
        target_name="preview-root-held-reset",
        multi_controller_enabled=True,
    )
    app = create_app(build_service_config(registry_file, coordination_mode="sqlite_lease"))

    with TestClient(app) as client:
        created = client.post("/campaigns", json={"root_path": str(project_root)}).json()

    backend = app.state.coordination_backend
    with backend.acquire_campaign_lease(
        created["campaign_id"],
        timeout_seconds=1.0,
        fail_fast=False,
    ):
        with TestClient(app) as client:
            response = client.post(
                f"/campaigns/{created['campaign_id']}/reset",
                json={"yes": True, "fail_fast": True},
            )

    assert response.status_code == 409
    assert response.json() == _coordination_error_payload("preview-root-held-reset")


def test_sqlite_coordination_mode_blocks_restore_when_controller_lease_is_held(
    tmp_path: Path,
) -> None:
    registry_file = tmp_path / "service_state" / "campaign_registry.json"
    project_root = _prepare_demo_campaign_root(
        tmp_path,
        target_name="preview-root-held-restore",
        multi_controller_enabled=True,
    )
    app = create_app(build_service_config(registry_file, coordination_mode="sqlite_lease"))

    with TestClient(app) as client:
        created = client.post("/campaigns", json={"root_path": str(project_root)}).json()
        campaign_id = created["campaign_id"]
        reset_response = client.post(
            f"/campaigns/{campaign_id}/reset",
            json={"yes": True},
        )

    assert reset_response.status_code == 200
    archive_id = reset_response.json()["archive_id"]

    backend = app.state.coordination_backend
    with backend.acquire_campaign_lease(campaign_id, timeout_seconds=1.0, fail_fast=False):
        with TestClient(app) as client:
            response = client.post(
                f"/campaigns/{campaign_id}/restore",
                json={"archive_id": archive_id, "yes": True, "fail_fast": True},
            )

    assert response.status_code == 409
    assert response.json() == _coordination_error_payload("preview-root-held-restore")
