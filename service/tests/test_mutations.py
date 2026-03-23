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


def _prepare_variant_copy(
    tmp_path: Path,
    variant: str,
    *,
    target_name: str,
    worker_leases_enabled: bool = False,
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
    cfg["worker_leases"] = {"enabled": worker_leases_enabled}
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
    primary = payload["primary_objective"]
    return str(primary["name"])


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


def _normalize_suggest_response(payload: dict[str, object]) -> dict[str, object]:
    normalized = dict(payload)
    suggestions = []
    for suggestion in payload.get("suggestions", []):
        if not isinstance(suggestion, dict):
            suggestions.append(suggestion)
            continue
        suggestion_payload = dict(suggestion)
        suggestion_payload.pop("suggested_at", None)
        suggestions.append(suggestion_payload)
    normalized["suggestions"] = suggestions
    return normalized


def _normalize_jsonl_suggestions(text: str) -> list[dict[str, object]]:
    normalized: list[dict[str, object]] = []
    for raw_line in text.splitlines():
        if not raw_line.strip():
            continue
        payload = json.loads(raw_line)
        payload.pop("suggested_at", None)
        normalized.append(payload)
    return normalized


@pytest.mark.parametrize("variant", VARIANTS)
def test_suggest_endpoint_matches_cli_bundle_payload_across_variants(
    tmp_path: Path, variant: str
) -> None:
    service_root = _prepare_variant_copy(tmp_path, variant, target_name=f"{variant}_service")
    cli_root = _prepare_variant_copy(tmp_path, variant, target_name=f"{variant}_cli")
    registry_file = tmp_path / "service_state" / "campaign_registry.json"
    app = create_app(build_service_config(registry_file))

    with TestClient(app) as client:
        created = client.post("/campaigns", json={"root_path": str(service_root)}).json()
        response = client.post(f"/campaigns/{created['campaign_id']}/suggest", json={"count": 2})

    assert response.status_code == 200
    cli_payload = json.loads(_run_cli(cli_root, "suggest", "--json-only", "--count", "2").stdout)
    assert _normalize_suggest_response(response.json()) == _normalize_suggest_response(cli_payload)


@pytest.mark.parametrize("variant", VARIANTS)
def test_suggest_endpoint_supports_jsonl_output_mode_across_variants(
    tmp_path: Path, variant: str
) -> None:
    service_root = _prepare_variant_copy(tmp_path, variant, target_name=f"{variant}_service_jsonl")
    cli_root = _prepare_variant_copy(tmp_path, variant, target_name=f"{variant}_cli_jsonl")
    registry_file = tmp_path / "service_state" / "campaign_registry.json"
    app = create_app(build_service_config(registry_file))

    with TestClient(app) as client:
        created = client.post("/campaigns", json={"root_path": str(service_root)}).json()
        response = client.post(
            f"/campaigns/{created['campaign_id']}/suggest",
            json={"count": 2, "output_mode": "jsonl"},
        )

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/x-ndjson")
    cli_payload = _run_cli(cli_root, "suggest", "--jsonl", "--count", "2").stdout
    assert _normalize_jsonl_suggestions(response.text) == _normalize_jsonl_suggestions(cli_payload)


def test_ingest_endpoint_supports_duplicate_noop(tmp_path: Path) -> None:
    project_root = _prepare_variant_copy(tmp_path, "bo_client_demo", target_name="demo_ingest")
    registry_file = tmp_path / "service_state" / "campaign_registry.json"
    app = create_app(build_service_config(registry_file))

    with TestClient(app) as client:
        created = client.post("/campaigns", json={"root_path": str(project_root)}).json()
        campaign_id = created["campaign_id"]
        suggestion = client.post(f"/campaigns/{campaign_id}/suggest").json()

        result_payload = _ok_result_payload(project_root, suggestion, 0.25)
        first_ingest = client.post(
            f"/campaigns/{campaign_id}/ingest",
            json={"payload": result_payload},
        )
        second_ingest = client.post(
            f"/campaigns/{campaign_id}/ingest",
            json={"payload": result_payload},
        )
        status_response = client.get(f"/campaigns/{campaign_id}/status")

    assert first_ingest.status_code == 200
    assert first_ingest.json()["noop"] is False
    assert first_ingest.json()["message"] == "Ingested trial_id=1. Observations=1"
    assert second_ingest.status_code == 200
    assert second_ingest.json() == {
        "message": "No-op: trial_id=1 already ingested with identical payload.",
        "noop": True,
    }
    assert status_response.status_code == 200
    assert status_response.json()["observations"] == 1
    assert status_response.json()["pending"] == 0


def test_ingest_endpoint_enforces_lease_tokens_when_enabled(tmp_path: Path) -> None:
    project_root = _prepare_variant_copy(
        tmp_path,
        "bo_client_demo",
        target_name="demo_leases",
        worker_leases_enabled=True,
    )
    registry_file = tmp_path / "service_state" / "campaign_registry.json"
    app = create_app(build_service_config(registry_file))

    with TestClient(app) as client:
        created = client.post("/campaigns", json={"root_path": str(project_root)}).json()
        campaign_id = created["campaign_id"]
        suggestion = client.post(f"/campaigns/{campaign_id}/suggest").json()
        result_payload = _ok_result_payload(project_root, suggestion, 0.2)

        missing_token = client.post(
            f"/campaigns/{campaign_id}/ingest",
            json={"payload": result_payload},
        )
        wrong_token = client.post(
            f"/campaigns/{campaign_id}/ingest",
            json={"payload": result_payload, "lease_token": "wrong-token"},
        )
        correct_token = client.post(
            f"/campaigns/{campaign_id}/ingest",
            json={"payload": result_payload, "lease_token": suggestion["lease_token"]},
        )

    assert missing_token.status_code == 409
    assert missing_token.json()["error"]["code"] == "lease_token_required"
    assert wrong_token.status_code == 409
    assert wrong_token.json()["error"]["code"] == "lease_token_mismatch"
    assert correct_token.status_code == 200
    assert correct_token.json()["noop"] is False


def test_reset_and_restore_round_trip_archive_id_and_artifacts(tmp_path: Path) -> None:
    project_root = _prepare_variant_copy(tmp_path, "bo_client_demo", target_name="demo_restore")
    registry_file = tmp_path / "service_state" / "campaign_registry.json"
    app = create_app(build_service_config(registry_file))

    with TestClient(app) as client:
        created = client.post("/campaigns", json={"root_path": str(project_root)}).json()
        campaign_id = created["campaign_id"]
        suggestion = client.post(f"/campaigns/{campaign_id}/suggest").json()
        result_payload = _ok_result_payload(project_root, suggestion, 0.15)
        ingest_response = client.post(
            f"/campaigns/{campaign_id}/ingest",
            json={"payload": result_payload},
        )
        assert ingest_response.status_code == 200

    _run_cli(project_root, "report")

    with TestClient(app) as client:
        pre_reset_status = client.get(f"/campaigns/{campaign_id}/status").json()
        pre_reset_report = client.get(f"/campaigns/{campaign_id}/report").json()

        reset_without_yes = client.post(f"/campaigns/{campaign_id}/reset", json={})
        reset_with_yes = client.post(f"/campaigns/{campaign_id}/reset", json={"yes": True})
        assert reset_with_yes.status_code == 200
        archive_id = reset_with_yes.json()["archive_id"]
        assert archive_id

        post_reset_status = client.get(f"/campaigns/{campaign_id}/status")
        post_reset_report = client.get(f"/campaigns/{campaign_id}/report")
        restore_response = client.post(
            f"/campaigns/{campaign_id}/restore",
            json={"archive_id": archive_id, "yes": True},
        )
        post_restore_status = client.get(f"/campaigns/{campaign_id}/status")
        post_restore_report = client.get(f"/campaigns/{campaign_id}/report")

    assert reset_without_yes.status_code == 400
    assert reset_without_yes.json()["error"]["code"] == "confirmation_required"
    assert post_reset_status.status_code == 200
    assert post_reset_status.json()["observations"] == 0
    assert post_reset_report.status_code == 404
    assert post_reset_report.json()["error"]["code"] == "report_not_generated"

    assert restore_response.status_code == 200
    assert restore_response.json()["archive_id"] == archive_id
    assert post_restore_status.status_code == 200
    assert post_restore_status.json() == pre_reset_status
    assert post_restore_report.status_code == 200
    assert post_restore_report.json() == pre_reset_report


def test_mutating_endpoint_fails_if_preview_flag_is_disabled_after_registration(
    tmp_path: Path,
) -> None:
    project_root = _prepare_variant_copy(
        tmp_path, "bo_client_demo", target_name="demo_preview_revoked"
    )
    registry_file = tmp_path / "service_state" / "campaign_registry.json"
    app = create_app(build_service_config(registry_file))

    with TestClient(app) as client:
        created = client.post("/campaigns", json={"root_path": str(project_root)}).json()

    cfg_path = project_root / "bo_config.json"
    cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
    cfg["feature_flags"]["enable_service_api_preview"] = False
    cfg_path.write_text(json.dumps(cfg, indent=2), encoding="utf-8")

    with TestClient(app) as client:
        response = client.post(f"/campaigns/{created['campaign_id']}/suggest", json={})

    assert response.status_code == 403
    assert response.json() == {
        "error": {
            "code": "service_preview_disabled",
            "message": "Campaign root is not service-enabled; set "
            "feature_flags.enable_service_api_preview=true before registration",
        }
    }
