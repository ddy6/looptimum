#!/usr/bin/env python3
"""Release smoke checks for quickstart workflows across template variants."""

from __future__ import annotations

import argparse
import base64
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any, cast

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from fastapi.testclient import TestClient  # noqa: E402

from service.app import create_app  # noqa: E402
from service.config import build_service_config  # noqa: E402

TEMPLATES_SRC = REPO_ROOT / "templates"
TINY_LOOP_SCRIPT = (
    REPO_ROOT / "examples" / "toy_objectives" / "03_tiny_quadratic_loop" / "run_tiny_loop.py"
)

VARIANTS = ["bo_client_demo", "bo_client", "bo_client_full"]


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Run release smoke checks for quickstart commands across template variants "
            "in temporary copies."
        )
    )
    parser.add_argument(
        "--demo-steps",
        type=int,
        default=3,
        help="Number of steps for per-variant demo smoke (default: 3).",
    )
    parser.add_argument(
        "--tiny-loop-steps",
        type=int,
        default=4,
        help="Number of steps for tiny objective smoke (default: 4).",
    )
    parser.add_argument(
        "--keep-temp-dir",
        action="store_true",
        help="Keep the temporary workspace for debugging.",
    )
    return parser.parse_args()


def _run(cmd: list[str], *, cwd: Path) -> str:
    proc = subprocess.run(
        cmd,
        cwd=str(cwd),
        text=True,
        capture_output=True,
        check=False,
    )
    if proc.returncode != 0:
        raise RuntimeError(
            "Command failed\n"
            f"cmd: {' '.join(cmd)}\n"
            f"returncode: {proc.returncode}\n"
            f"stdout:\n{proc.stdout}\n"
            f"stderr:\n{proc.stderr}"
        )
    return proc.stdout


def _prepare_temp_templates(temp_root: Path) -> Path:
    temp_templates = temp_root / "templates"
    ignore = shutil.ignore_patterns(
        "__pycache__",
        "*.pyc",
        ".DS_Store",
        ".looptimum.lock",
        "bo_state.json",
        "observations.csv",
        "acquisition_log.jsonl",
        "event_log.jsonl",
        "report.json",
        "report.md",
    )
    shutil.copytree(TEMPLATES_SRC, temp_templates, ignore=ignore)
    return temp_templates


def _enable_service_preview(project_root: Path, *, enable_multi_controller: bool = False) -> None:
    cfg_path = project_root / "bo_config.json"
    cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
    feature_flags = dict(cfg.get("feature_flags", {}))
    feature_flags["enable_service_api_preview"] = True
    feature_flags["enable_dashboard_preview"] = True
    feature_flags["enable_auth_preview"] = True
    feature_flags["enable_multi_controller_preview"] = enable_multi_controller
    cfg["feature_flags"] = feature_flags
    cfg_path.write_text(json.dumps(cfg, indent=2), encoding="utf-8")


def _clean_state(project_root: Path) -> None:
    state_dir = project_root / "state"
    state_dir.mkdir(parents=True, exist_ok=True)
    for child in state_dir.iterdir():
        if child.name == ".gitkeep":
            continue
        if child.is_dir():
            shutil.rmtree(child)
        else:
            child.unlink()


def _require_keys(payload: dict[str, Any], keys: list[str], *, context: str) -> None:
    for key in keys:
        if key not in payload:
            raise RuntimeError(f"Missing key '{key}' in {context}: {payload}")


def _basic_auth_header(username: str, password: str) -> dict[str, str]:
    token = base64.b64encode(f"{username}:{password}".encode("utf-8")).decode("ascii")
    return {"Authorization": f"Basic {token}"}


def _status_payload(raw: str, *, context: str) -> dict[str, Any]:
    payload = cast(dict[str, Any], json.loads(raw))
    _require_keys(
        payload,
        [
            "schema_version",
            "observations",
            "pending",
            "next_trial_id",
            "best",
            "stale_pending",
            "paths",
        ],
        context=context,
    )
    return payload


def _smoke_core_flow(project_root: Path, *, demo_steps: int, include_botorch_flag: bool) -> None:
    run_bo = project_root / "run_bo.py"

    _clean_state(project_root)
    _status_payload(
        _run(
            [sys.executable, str(run_bo), "status", "--project-root", str(project_root)],
            cwd=REPO_ROOT,
        ),
        context=f"{project_root.name} initial status",
    )
    _run(
        [
            sys.executable,
            str(run_bo),
            "suggest",
            "--project-root",
            str(project_root),
            "--json-only",
        ],
        cwd=REPO_ROOT,
    )
    _run(
        [
            sys.executable,
            str(run_bo),
            "ingest",
            "--project-root",
            str(project_root),
            "--results-file",
            str(project_root / "examples" / "example_results.json"),
        ],
        cwd=REPO_ROOT,
    )
    status_after_ingest = _status_payload(
        _run(
            [sys.executable, str(run_bo), "status", "--project-root", str(project_root)],
            cwd=REPO_ROOT,
        ),
        context=f"{project_root.name} status after ingest",
    )
    if int(status_after_ingest["observations"]) < 1:
        raise RuntimeError(f"{project_root.name}: expected at least one observation after ingest")

    _clean_state(project_root)
    _run(
        [
            sys.executable,
            str(run_bo),
            "demo",
            "--project-root",
            str(project_root),
            "--steps",
            str(demo_steps),
        ],
        cwd=REPO_ROOT,
    )
    status_after_demo = _status_payload(
        _run(
            [sys.executable, str(run_bo), "status", "--project-root", str(project_root)],
            cwd=REPO_ROOT,
        ),
        context=f"{project_root.name} status after demo",
    )
    if int(status_after_demo["observations"]) < demo_steps:
        raise RuntimeError(
            f"{project_root.name}: expected at least {demo_steps} observations after demo,"
            f" got {status_after_demo['observations']}"
        )

    if include_botorch_flag:
        _clean_state(project_root)
        _run(
            [
                sys.executable,
                str(run_bo),
                "suggest",
                "--project-root",
                str(project_root),
                "--enable-botorch-gp",
            ],
            cwd=REPO_ROOT,
        )


def _smoke_ops_flow(project_root: Path) -> None:
    run_bo = project_root / "run_bo.py"
    state_dir = project_root / "state"
    _clean_state(project_root)

    suggestion_1 = json.loads(
        _run(
            [
                sys.executable,
                str(run_bo),
                "suggest",
                "--project-root",
                str(project_root),
                "--json-only",
            ],
            cwd=REPO_ROOT,
        )
    )
    _require_keys(
        suggestion_1,
        ["schema_version", "trial_id", "params", "suggested_at"],
        context=f"{project_root.name} first suggestion",
    )
    trial_1 = int(suggestion_1["trial_id"])
    _run(
        [
            sys.executable,
            str(run_bo),
            "heartbeat",
            "--project-root",
            str(project_root),
            "--trial-id",
            str(trial_1),
            "--heartbeat-note",
            "release smoke heartbeat",
        ],
        cwd=REPO_ROOT,
    )
    _run(
        [
            sys.executable,
            str(run_bo),
            "cancel",
            "--project-root",
            str(project_root),
            "--trial-id",
            str(trial_1),
        ],
        cwd=REPO_ROOT,
    )

    suggestion_2 = json.loads(
        _run(
            [
                sys.executable,
                str(run_bo),
                "suggest",
                "--project-root",
                str(project_root),
                "--json-only",
            ],
            cwd=REPO_ROOT,
        )
    )
    _require_keys(
        suggestion_2,
        ["schema_version", "trial_id", "params", "suggested_at"],
        context=f"{project_root.name} second suggestion",
    )
    trial_2 = int(suggestion_2["trial_id"])
    _run(
        [
            sys.executable,
            str(run_bo),
            "retire",
            "--project-root",
            str(project_root),
            "--trial-id",
            str(trial_2),
        ],
        cwd=REPO_ROOT,
    )

    _run(
        [
            sys.executable,
            str(run_bo),
            "suggest",
            "--project-root",
            str(project_root),
            "--json-only",
        ],
        cwd=REPO_ROOT,
    )
    _run(
        [
            sys.executable,
            str(run_bo),
            "retire",
            "--project-root",
            str(project_root),
            "--stale",
        ],
        cwd=REPO_ROOT,
    )
    _run(
        [
            sys.executable,
            str(run_bo),
            "report",
            "--project-root",
            str(project_root),
            "--top-n",
            "5",
        ],
        cwd=REPO_ROOT,
    )
    _run(
        [sys.executable, str(run_bo), "validate", "--project-root", str(project_root)],
        cwd=REPO_ROOT,
    )
    doctor_payload = json.loads(
        _run(
            [
                sys.executable,
                str(run_bo),
                "doctor",
                "--project-root",
                str(project_root),
                "--json",
            ],
            cwd=REPO_ROOT,
        )
    )
    _require_keys(
        doctor_payload,
        ["generated_at", "python_version", "platform", "project_root", "status"],
        context=f"{project_root.name} doctor",
    )

    if not (state_dir / "report.json").exists():
        raise RuntimeError(f"{project_root.name}: missing report.json after report command")
    if not (state_dir / "report.md").exists():
        raise RuntimeError(f"{project_root.name}: missing report.md after report command")


def _smoke_variant(variant_name: str, project_root: Path, *, demo_steps: int) -> None:
    include_botorch_flag = variant_name == "bo_client_full"
    print(f"[smoke] core flow: {variant_name}")
    _smoke_core_flow(
        project_root,
        demo_steps=demo_steps,
        include_botorch_flag=include_botorch_flag,
    )
    print(f"[smoke] ops flow: {variant_name}")
    _smoke_ops_flow(project_root)
    print(f"[smoke] variant passed: {variant_name}")


def _smoke_tiny_loop(tiny_steps: int) -> None:
    print("[smoke] tiny loop")
    _run(
        [sys.executable, str(TINY_LOOP_SCRIPT), "--steps", str(tiny_steps)],
        cwd=REPO_ROOT,
    )
    print("[smoke] tiny loop passed")


def _smoke_service_preview(temp_root: Path, project_root: Path) -> None:
    print("[smoke] service preview")
    _clean_state(project_root)
    _enable_service_preview(project_root)

    registry_file = temp_root / "service_state" / "campaign_registry.json"
    admin_headers = _basic_auth_header("admin", "admin-secret")
    operator_headers = _basic_auth_header("operator", "operator-secret")
    viewer_headers = _basic_auth_header("viewer", "viewer-secret")
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

    with TestClient(app) as client:
        health_response = client.get("/health")
        if health_response.status_code != 200:
            raise RuntimeError(f"service preview health failed: {health_response.text}")
        unauthenticated_response = client.get("/campaigns")
        if unauthenticated_response.status_code != 401:
            raise RuntimeError(
                "service preview expected authenticated /campaigns access; "
                f"got {unauthenticated_response.status_code}: {unauthenticated_response.text}"
            )

        create_response = client.post(
            "/campaigns",
            json={"root_path": str(project_root), "label": "Release Smoke Preview"},
            headers=admin_headers,
        )
        if create_response.status_code != 201:
            raise RuntimeError(f"service preview registration failed: {create_response.text}")

        campaign = create_response.json()
        campaign_id = str(campaign["campaign_id"])

        list_response = client.get("/campaigns", headers=viewer_headers)
        if list_response.status_code != 200:
            raise RuntimeError(f"service preview campaign list failed: {list_response.text}")

        dashboard_root_response = client.get("/dashboard", headers=viewer_headers)
        if dashboard_root_response.status_code != 200:
            raise RuntimeError(
                f"service preview dashboard root failed: {dashboard_root_response.text}"
            )

        suggest_response = client.post(
            f"/campaigns/{campaign_id}/suggest",
            json={},
            headers=operator_headers,
        )
        if suggest_response.status_code != 200:
            raise RuntimeError(f"service preview suggest failed: {suggest_response.text}")
        suggestion = suggest_response.json()
        _require_keys(
            suggestion,
            ["schema_version", "trial_id", "params", "suggested_at"],
            context="service preview suggest",
        )

        objective_schema = json.loads(
            (project_root / "objective_schema.json").read_text(encoding="utf-8")
        )
        primary_objective = str(objective_schema["primary_objective"]["name"])
        ingest_response = client.post(
            f"/campaigns/{campaign_id}/ingest",
            json={
                "payload": {
                    "trial_id": suggestion["trial_id"],
                    "params": suggestion["params"],
                    "status": "ok",
                    "objectives": {primary_objective: 0.1234},
                }
            },
            headers=operator_headers,
        )
        if ingest_response.status_code != 200:
            raise RuntimeError(f"service preview ingest failed: {ingest_response.text}")

        status_response = client.get(
            f"/campaigns/{campaign_id}/status",
            headers=viewer_headers,
        )
        if status_response.status_code != 200:
            raise RuntimeError(f"service preview status failed: {status_response.text}")
        status_payload = status_response.json()
        if int(status_payload["observations"]) != 1:
            raise RuntimeError(
                "service preview expected one observation after ingest, "
                f"got {status_payload['observations']}"
            )

    run_bo = project_root / "run_bo.py"
    _run(
        [sys.executable, str(run_bo), "report", "--project-root", str(project_root)],
        cwd=REPO_ROOT,
    )

    with TestClient(app) as client:
        report_response = client.get(
            f"/campaigns/{campaign_id}/report",
            headers=viewer_headers,
        )
        if report_response.status_code != 200:
            raise RuntimeError(f"service preview report failed: {report_response.text}")
        report_payload = report_response.json()
        if int(report_payload["counts"]["observations"]) != 1:
            raise RuntimeError(
                "service preview report expected one observation, "
                f"got {report_payload['counts']['observations']}"
            )
        dashboard_campaign_response = client.get(
            f"/dashboard/campaigns/{campaign_id}",
            headers=viewer_headers,
        )
        if dashboard_campaign_response.status_code != 200:
            raise RuntimeError(
                f"service preview dashboard campaign failed: {dashboard_campaign_response.text}"
            )
        if f'data-current-campaign-id="{campaign_id}"' not in dashboard_campaign_response.text:
            raise RuntimeError("service preview dashboard campaign missing bound campaign id")
    print("[smoke] service preview passed")


def _smoke_service_coordination_preview(temp_root: Path, project_root: Path) -> None:
    print("[smoke] service coordination preview")
    _clean_state(project_root)
    _enable_service_preview(project_root, enable_multi_controller=True)

    registry_file = temp_root / "service_state" / "coordination_campaign_registry.json"
    app = create_app(
        build_service_config(
            registry_file,
            coordination_mode="sqlite_lease",
            coordination_lease_ttl_seconds=5.0,
        )
    )

    with TestClient(app) as client:
        create_response = client.post(
            "/campaigns",
            json={"root_path": str(project_root), "label": "Release Smoke Coordination Preview"},
        )
        if create_response.status_code != 201:
            raise RuntimeError(
                f"service coordination preview registration failed: {create_response.text}"
            )
        campaign_id = str(create_response.json()["campaign_id"])

        suggest_response = client.post(f"/campaigns/{campaign_id}/suggest", json={})
        if suggest_response.status_code != 200:
            raise RuntimeError(
                f"service coordination preview suggest failed: {suggest_response.text}"
            )
        suggestion = suggest_response.json()
        if int(suggestion["trial_id"]) != 1:
            raise RuntimeError(
                "service coordination preview expected first coordinated trial_id=1, "
                f"got {suggestion['trial_id']}"
            )

        with app.state.coordination_backend.acquire_campaign_lease(
            campaign_id,
            timeout_seconds=1.0,
            fail_fast=False,
        ):
            contention_response = client.post(
                f"/campaigns/{campaign_id}/suggest",
                json={"fail_fast": True},
            )
        if contention_response.status_code != 409:
            raise RuntimeError(
                "service coordination preview expected fail-fast contention to return 409, "
                f"got {contention_response.status_code}: {contention_response.text}"
            )
        payload = contention_response.json()
        if payload.get("error", {}).get("code") != "coordination_unavailable":
            raise RuntimeError(
                "service coordination preview expected coordination_unavailable payload, "
                f"got {payload}"
            )
    print("[smoke] service coordination preview passed")


def main() -> None:
    args = _parse_args()
    if args.demo_steps < 1:
        raise SystemExit("--demo-steps must be >= 1")
    if args.tiny_loop_steps < 1:
        raise SystemExit("--tiny-loop-steps must be >= 1")

    temp_root = Path(tempfile.mkdtemp(prefix="looptimum_release_smoke_"))
    print(f"[smoke] temp root: {temp_root}")

    try:
        temp_templates = _prepare_temp_templates(temp_root)
        for variant_name in VARIANTS:
            _smoke_variant(
                variant_name,
                temp_templates / variant_name,
                demo_steps=args.demo_steps,
            )
        _smoke_tiny_loop(args.tiny_loop_steps)
        _smoke_service_preview(temp_root, temp_templates / "bo_client_demo")
        _smoke_service_coordination_preview(temp_root, temp_templates / "bo_client_demo")
    finally:
        if args.keep_temp_dir:
            print(f"[smoke] kept temp root: {temp_root}")
        else:
            shutil.rmtree(temp_root, ignore_errors=True)

    print("[smoke] all release smoke checks passed")


if __name__ == "__main__":
    main()
