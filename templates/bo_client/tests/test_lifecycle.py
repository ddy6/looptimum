from __future__ import annotations

import json
import time

from conftest import parse_suggestion, run_cmd


def _read_state(template_copy):
    return json.loads((template_copy / "state" / "bo_state.json").read_text(encoding="utf-8"))


def _read_manifest(template_copy, trial_id: int):
    path = template_copy / "state" / "trials" / f"trial_{trial_id}" / "manifest.json"
    return json.loads(path.read_text(encoding="utf-8"))


def _read_events(template_copy):
    path = template_copy / "state" / "event_log.jsonl"
    lines = [line.strip() for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    return [json.loads(line) for line in lines]


def test_cancel_moves_pending_to_killed_observation_and_manifest(template_copy) -> None:
    suggestion = parse_suggestion(run_cmd(template_copy, "suggest").stdout)
    out = run_cmd(template_copy, "cancel", "--trial-id", str(suggestion["trial_id"]))
    assert "Canceled trial_id=1" in out.stdout

    state = _read_state(template_copy)
    assert len(state["pending"]) == 0
    assert len(state["observations"]) == 1
    obs = state["observations"][0]
    assert obs["status"] == "killed"
    assert obs["terminal_reason"] == "canceled"
    assert obs["objectives"]["loss"] is None

    manifest = _read_manifest(template_copy, 1)
    assert manifest["status"] == "killed"
    assert manifest["terminal_reason"] == "canceled"

    events = _read_events(template_copy)
    assert any(e["event"] == "trial_canceled" and e["trial_id"] == 1 for e in events)


def test_heartbeat_updates_pending_and_manifest(template_copy) -> None:
    suggestion = parse_suggestion(run_cmd(template_copy, "suggest").stdout)
    run_cmd(
        template_copy,
        "heartbeat",
        "--trial-id",
        str(suggestion["trial_id"]),
        "--heartbeat-note",
        "running",
        "--heartbeat-meta-json",
        '{"worker":"node-a"}',
    )

    state = _read_state(template_copy)
    pending = state["pending"][0]
    assert pending["trial_id"] == suggestion["trial_id"]
    assert pending["heartbeat_count"] == 1
    assert pending["heartbeat_note"] == "running"
    assert pending["heartbeat_meta"] == {"worker": "node-a"}
    assert isinstance(pending["last_heartbeat_at"], float)

    manifest = _read_manifest(template_copy, suggestion["trial_id"])
    assert manifest["status"] == "pending"
    assert manifest["heartbeat_count"] == 1
    assert manifest["heartbeat_note"] == "running"
    assert manifest["heartbeat_meta"] == {"worker": "node-a"}

    events = _read_events(template_copy)
    assert any(
        e["event"] == "heartbeat" and e["trial_id"] == suggestion["trial_id"] for e in events
    )


def test_retire_stale_command_retires_pending_trial(template_copy) -> None:
    suggestion = parse_suggestion(run_cmd(template_copy, "suggest").stdout)
    state_path = template_copy / "state" / "bo_state.json"
    state = json.loads(state_path.read_text(encoding="utf-8"))
    state["pending"][0]["suggested_at"] = time.time() - 3600
    state_path.write_text(json.dumps(state, indent=2), encoding="utf-8")

    out = run_cmd(template_copy, "retire", "--stale", "--max-age-seconds", "60")
    assert "Retired 1 pending trial(s)" in out.stdout

    state_after = _read_state(template_copy)
    assert len(state_after["pending"]) == 0
    assert len(state_after["observations"]) == 1
    obs = state_after["observations"][0]
    assert obs["trial_id"] == suggestion["trial_id"]
    assert obs["status"] == "killed"
    assert obs["terminal_reason"] == "retired_stale"


def test_suggest_auto_retires_stale_pending(template_copy) -> None:
    cfg_path = template_copy / "bo_config.json"
    cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
    cfg["max_pending_age_seconds"] = 60
    cfg_path.write_text(json.dumps(cfg, indent=2), encoding="utf-8")

    first = parse_suggestion(run_cmd(template_copy, "suggest").stdout)
    state_path = template_copy / "state" / "bo_state.json"
    state = json.loads(state_path.read_text(encoding="utf-8"))
    state["pending"][0]["suggested_at"] = time.time() - 3600
    state_path.write_text(json.dumps(state, indent=2), encoding="utf-8")

    second = parse_suggestion(run_cmd(template_copy, "suggest").stdout)
    assert second["trial_id"] == first["trial_id"] + 1

    state_after = _read_state(template_copy)
    assert len(state_after["observations"]) == 1
    assert len(state_after["pending"]) == 1
    stale_obs = state_after["observations"][0]
    assert stale_obs["trial_id"] == first["trial_id"]
    assert stale_obs["terminal_reason"] == "retired_stale_auto"
    assert stale_obs["status"] == "killed"
    assert state_after["pending"][0]["trial_id"] == second["trial_id"]


def test_ingest_writes_trial_manifest_and_payload_copy(template_copy) -> None:
    suggestion = parse_suggestion(run_cmd(template_copy, "suggest").stdout)
    payload = {
        "trial_id": suggestion["trial_id"],
        "params": suggestion["params"],
        "objectives": {"loss": 0.123},
        "status": "ok",
    }
    path = template_copy / "examples" / "_phase5_ingest_payload.json"
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    run_cmd(template_copy, "ingest", "--results-file", str(path))

    manifest = _read_manifest(template_copy, suggestion["trial_id"])
    assert manifest["status"] == "ok"
    assert manifest["objective_value"] == 0.123
    artifact_rel = manifest["artifacts"]["ingest_payload"]
    artifact_abs = template_copy / artifact_rel
    assert artifact_abs.exists()


def test_status_preserves_legacy_keys_and_adds_phase5_fields(template_copy) -> None:
    payload = json.loads(run_cmd(template_copy, "status").stdout)
    for key in ("observations", "pending", "next_trial_id", "best"):
        assert key in payload
    for key in ("stale_pending", "observations_by_status", "paths"):
        assert key in payload
    assert "event_log_file" in payload["paths"]
    assert "trials_dir" in payload["paths"]
