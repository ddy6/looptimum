from __future__ import annotations

import json
import sys
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from service.app import create_app
from service.config import ServiceConfigError, build_service_config
from service.coordination import SQLiteLeaseCoordinationBackend
from service.runtime import (
    RuntimeArtifactError,
    load_report_payload,
    resolve_runtime_lock_timeout_seconds,
)
from service.tests.test_mutations import _prepare_variant_copy


@pytest.mark.parametrize(
    "error",
    [
        {"type": "RuntimeCommandError", "message": "broken"},
        {
            "type": "RuntimeCommandError",
            "message": "broken",
            "code": "bad",
            "status_code": "400",
            "stdout": "",
            "stderr": "",
        },
        {
            "type": "RuntimeCommandError",
            "message": "broken",
            "code": "bad",
            "status_code": 200,
            "stdout": "",
            "stderr": "",
        },
    ],
)
def test_malformed_worker_error_is_a_controlled_service_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, error: dict
) -> None:
    import subprocess

    from service import runtime

    root = _prepare_variant_copy(tmp_path, "bo_client", target_name="malformed")
    monkeypatch.setattr(
        runtime.subprocess,
        "run",
        lambda *args, **kwargs: subprocess.CompletedProcess(
            args, 0, json.dumps({"ok": False, "error": error}), ""
        ),
    )
    with pytest.raises(RuntimeArtifactError, match="invalid response"):
        load_report_payload(root)


@pytest.mark.parametrize("value", [float("nan"), float("inf"), -float("inf"), 10**400, True])
def test_nonfinite_coordination_config_does_not_create_state(tmp_path: Path, value: object) -> None:
    with pytest.raises((ServiceConfigError, ValueError)):
        build_service_config(tmp_path / "registry.json", coordination_lease_ttl_seconds=value)
    with pytest.raises((ServiceConfigError, ValueError)):
        SQLiteLeaseCoordinationBackend(tmp_path / "lease.sqlite", value)
    assert not list(tmp_path.iterdir())


@pytest.mark.parametrize("value", [float("nan"), float("inf"), -1.0, 10**400, True])
def test_invalid_lease_wait_fails_before_database_creation(tmp_path: Path, value: object) -> None:
    backend = SQLiteLeaseCoordinationBackend(tmp_path / "lease.sqlite", 1.0)
    with pytest.raises(ValueError):
        with backend.acquire_campaign_lease("campaign", timeout_seconds=value, fail_fast=True):
            pytest.fail("invalid timeout acquired a lease")
    assert not list(tmp_path.iterdir())


def _custom_campaign(tmp_path: Path, name: str, seed: int) -> Path:
    root = _prepare_variant_copy(tmp_path, "bo_client", target_name=name)
    proxy = root / "surrogate_proxy.py"
    proxy.write_text(proxy.read_text() + f"\nCAMPAIGN_SEED = {seed}\n")
    entrypoint = root / "run_bo.py"
    entrypoint.write_text(
        entrypoint.read_text()
        + """
from surrogate_proxy import CAMPAIGN_SEED
_original_load_contract = load_contract_document
def load_contract_document(root, kind):
    document, path = _original_load_contract(root, kind)
    if kind == "bo_config":
        document["seed"] = CAMPAIGN_SEED
        document["lock_timeout_seconds"] = float(CAMPAIGN_SEED)
        document["paths"]["report_json_file"] = f"reports/{CAMPAIGN_SEED}.json"
    return document, path
"""
    )
    (root / "reports").mkdir()
    (root / "reports" / f"{seed}.json").write_text(json.dumps({"campaign_seed": seed}))
    return root


@pytest.mark.parametrize("reverse", [False, True])
def test_concurrent_campaigns_isolate_commands_reads_and_imports(
    tmp_path: Path, reverse: bool
) -> None:
    roots = [_custom_campaign(tmp_path, "first", 101), _custom_campaign(tmp_path, "second", 202)]
    if reverse:
        roots.reverse()
    original_streams = sys.stdout, sys.stderr
    original_path = list(sys.path)
    original_proxy = sys.modules.get("surrogate_proxy")
    app = create_app(build_service_config(tmp_path / "registry.json"))
    with TestClient(app) as client:
        ids = [
            client.post("/campaigns", json={"root_path": str(root)}).json()["campaign_id"]
            for root in roots
        ]
        barrier = threading.Barrier(2)

        def exercise(index: int) -> tuple[float, dict]:
            barrier.wait(timeout=10)
            response = client.post(f"/campaigns/{ids[index]}/suggest", json={})
            assert response.status_code == 200, response.text
            assert response.json()["trial_id"] == 1
            status = client.get(f"/campaigns/{ids[index]}/status")
            assert status.status_code == 200 and status.json()["pending"] == 1
            root = roots[index]
            return resolve_runtime_lock_timeout_seconds(root), load_report_payload(root)

        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(exercise, range(2)))
    expected = [202, 101] if reverse else [101, 202]
    for root, seed, (timeout, report) in zip(roots, expected, results):
        assert timeout == seed
        assert report == {"campaign_seed": seed}
        assert json.loads((root / "state/bo_state.json").read_text())["meta"]["seed"] == seed
    assert (sys.stdout, sys.stderr) == original_streams
    assert sys.path == original_path
    assert sys.modules.get("surrogate_proxy") is original_proxy


def test_same_campaign_parallel_service_allocations_are_unique(tmp_path: Path) -> None:
    root = _prepare_variant_copy(tmp_path, "bo_client", target_name="same")
    app = create_app(build_service_config(tmp_path / "registry.json"))
    original_streams = sys.stdout, sys.stderr
    with TestClient(app) as client:
        campaign_id = client.post("/campaigns", json={"root_path": str(root)}).json()["campaign_id"]
        barrier = threading.Barrier(3)

        def suggest(_: int) -> int:
            barrier.wait(timeout=10)
            response = client.post(f"/campaigns/{campaign_id}/suggest", json={})
            assert response.status_code == 200, response.text
            return response.json()["trial_id"]

        with ThreadPoolExecutor(max_workers=3) as pool:
            assert sorted(pool.map(suggest, range(3))) == [1, 2, 3]
    assert (sys.stdout, sys.stderr) == original_streams
    state = json.loads((root / "state/bo_state.json").read_text())
    assert len(state["pending"]) == 3 and state["next_trial_id"] == 4


@pytest.mark.parametrize("body", ["print('broken {')", "print('')", "__import__('os')._exit(9)"])
def test_bad_or_killed_worker_is_not_a_successful_empty_suggestion(
    tmp_path: Path, body: str
) -> None:
    root = _prepare_variant_copy(tmp_path, "bo_client", target_name="bad")
    entrypoint = root / "run_bo.py"
    entrypoint.write_text(entrypoint.read_text() + f"\ndef cmd_suggest(args):\n    {body}\n")
    app = create_app(build_service_config(tmp_path / "registry.json"))
    with TestClient(app) as client:
        campaign_id = client.post("/campaigns", json={"root_path": str(root)}).json()["campaign_id"]
        response = client.post(f"/campaigns/{campaign_id}/suggest", json={})
        assert response.status_code >= 400
        assert "error" in response.json()
