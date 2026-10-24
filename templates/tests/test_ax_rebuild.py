"""Rebuild transaction tests use the same isolated deterministic worker as allocation tests."""

from __future__ import annotations

import copy
import json

import pytest
from test_ax_recovery import FAKE_WORKER, JOURNAL, campaign, invoke, rows, state


def seeded_campaign(tmp_path, variant="bo_client"):
    project = campaign(tmp_path, variant)
    first, second = json.loads(invoke(project, "suggest", "--count", "2", "--json-only").stdout)[
        "suggestions"
    ]
    (project / "result.json").write_text(
        json.dumps(
            {
                "trial_id": first["trial_id"],
                "params": first["params"],
                "objectives": {"loss": 0.2},
                "status": "ok",
            }
        )
    )
    invoke(
        project, "ingest", "--results-file", "result.json", "--lease-token", first["lease_token"]
    )
    invoke(
        project,
        "heartbeat",
        "--trial-id",
        str(second["trial_id"]),
        "--lease-token",
        second["lease_token"],
        "--heartbeat-note",
        "running",
    )
    return project


def unchanged_campaign_records(before, after):
    expected = {key: value for key, value in before.items() if key != "optimizer"}
    assert {key: value for key, value in after.items() if key != "optimizer"} == expected


@pytest.mark.parametrize("variant", ["bo_client", "bo_client_full"])
@pytest.mark.parametrize("damage", ["missing", "corrupt", "healthy"])
def test_rebuild_starts_new_lineage_without_allocating_or_editing_canonical_records(
    tmp_path, variant, damage
):
    project = seeded_campaign(tmp_path, variant)
    before = state(project)
    canonical_bytes = (project / "state/bo_state.json").read_bytes()
    source = project / before["optimizer"]["snapshot"]["path"]
    if damage == "missing":
        source.unlink()
    elif damage == "corrupt":
        source.write_bytes(b"\xff\x00damaged snapshot")
    original_bytes = source.read_bytes() if source.exists() else None
    manifests = {path: path.read_bytes() for path in (project / "state/trials").rglob("*.json")}
    csv_bytes = (project / "state/observations.csv").read_bytes()
    result = json.loads(
        invoke(project, "rebuild-optimizer", "--reason", "lost generation history").stdout
    )
    assert result["status"] == "rebuilt" and result["allocated_trials"] == 0
    current = state(project)
    unchanged_campaign_records(before, current)
    assert current["optimizer"]["lineage"] != before["optimizer"]["lineage"]
    assert current["optimizer"]["generation"] == 0
    recovery = current["optimizer"]["last_rebuild"]
    assert recovery["configuration_verified"] is True
    assert recovery["previous_snapshot"] == before["optimizer"]["snapshot"]
    assert recovery["previous_lineage"] == before["optimizer"]["lineage"]
    backup = project / recovery["backup_directory"]
    assert (backup / "state-before.json").read_bytes() == canonical_bytes
    if original_bytes is not None:
        assert source.read_bytes() == original_bytes
        assert (backup / "snapshot-before.bin").read_bytes() == original_bytes
    else:
        assert not (backup / "snapshot-before.bin").exists()
    assert (project / "state/observations.csv").read_bytes() == csv_bytes
    assert all(path.read_bytes() == contents for path, contents in manifests.items())
    receipt = json.loads((backup / "rebuild.json").read_text())
    assert receipt["snapshot"] == current["optimizer"]["snapshot"]
    snapshot = json.loads((project / receipt["snapshot"]["path"]).read_text())
    assert set(snapshot["mapping"]) == {"1", "2"}
    assert snapshot["last_rebuild"] == recovery
    request = json.loads((project / "ax_request.json").read_text())
    assert request["count"] == 0 and request["operation"] == "rebuild"
    events = [
        row for row in rows(project, "state/event_log.jsonl") if row["event"] == "optimizer_rebuilt"
    ]
    assert [row["rebuild_id"] for row in events] == [recovery["rebuild_id"]]
    invoke(project, "validate", "--strict")
    third = json.loads(invoke(project, "suggest", "--json-only").stdout)
    assert third["trial_id"] == 3
    assert state(project)["optimizer"]["lineage"] == recovery["lineage"]
    assert state(project)["optimizer"]["last_rebuild"] == recovery
    assert (
        rows(project, "state/acquisition_log.jsonl")[-1]["decision"]["optimizer_lineage"]
        == recovery["lineage"]
    )


@pytest.mark.parametrize("stage", ["rebuild_prepared", "rebuild_committed", "rebuild_event"])
def test_rebuild_process_exit_has_one_commit_point_and_idempotent_audit_repair(tmp_path, stage):
    project = seeded_campaign(tmp_path)
    before = state(project)
    stopped = invoke(
        project,
        "rebuild-optimizer",
        "--reason",
        "snapshot lost",
        success=False,
        env={"LOOPTIMUM_TEST_ALLOCATION_EXIT": stage},
    )
    assert stopped.returncode == 86 and stopped.stdout == ""
    if stage == "rebuild_prepared":
        assert state(project) == before
        assert not any(
            row["event"] == "optimizer_rebuilt" for row in rows(project, "state/event_log.jsonl")
        )
        assert (
            json.loads(invoke(project, "rebuild-optimizer", "--reason", "retry").stdout)["status"]
            == "rebuilt"
        )
        return
    current = state(project)
    unchanged_campaign_records(before, current)
    identifier = current["optimizer"]["last_rebuild"]["rebuild_id"]
    assert (
        json.loads(invoke(project, "status").stdout)["optimizer_recovery"]["status"] == "committed"
    )
    validation = invoke(project, "validate", "--strict", success=False)
    assert validation.returncode != 0 and "rebuild-optimizer" in validation.stdout
    # Completing audit publication must not require a working optimizer worker.
    request_before = (project / "ax_request.json").read_bytes()
    worker = project / "vendor/looptimum_shared/optimizer_ax_worker.py"
    worker.write_text("raise RuntimeError('worker must not run during audit repair')")
    recovered = json.loads(
        invoke(project, "rebuild-optimizer", "--reason", "finish committed rebuild").stdout
    )
    assert recovered["status"] == "recovered_rebuild"
    assert state(project)["optimizer"]["last_rebuild"]["rebuild_id"] == identifier
    assert "pending_rebuild_event" not in state(project)["optimizer"]
    assert (project / "ax_request.json").read_bytes() == request_before
    events = [
        row for row in rows(project, "state/event_log.jsonl") if row["event"] == "optimizer_rebuilt"
    ]
    assert len(events) == 1 and events[0]["rebuild_id"] == identifier
    worker.write_text(FAKE_WORKER)
    assert json.loads(invoke(project, "suggest", "--json-only").stdout)["trial_id"] == 3


@pytest.mark.parametrize(
    "basename,committed",
    [("bo_state.json", False), ("rebuild.json", False), ("event_log.jsonl", True)],
)
def test_rebuild_write_failure_preserves_the_previous_campaign_or_repairs_the_commit(
    tmp_path, basename, committed
):
    project = seeded_campaign(tmp_path)
    before = state(project)
    failed = invoke(
        project,
        "rebuild-optimizer",
        "--reason",
        "retry recovery",
        success=False,
        env={"LOOPTIMUM_TEST_ATOMIC_FAIL_BASENAME": basename},
    )
    assert failed.returncode != 0 and failed.stdout == ""
    if committed:
        assert "already committed" in failed.stderr
        identifier = state(project)["optimizer"]["last_rebuild"]["rebuild_id"]
        result = json.loads(invoke(project, "rebuild-optimizer", "--reason", "finish").stdout)
        assert result["status"] == "recovered_rebuild"
        assert result["rebuild"]["rebuild_id"] == identifier
    else:
        assert state(project) == before
    unchanged_campaign_records(before, state(project))


def test_rebuild_requires_existing_ax_campaign_reason_and_clean_allocation(tmp_path):
    project = campaign(tmp_path)
    failed = invoke(project, "rebuild-optimizer", "--reason", " ", success=False)
    assert failed.returncode != 0 and "non-empty --reason" in failed.stderr
    failed = invoke(project, "rebuild-optimizer", "--reason", "start", success=False)
    assert failed.returncode != 0 and "existing Ax campaign" in failed.stderr
    invoke(
        project,
        "suggest",
        "--json-only",
        success=False,
        env={"LOOPTIMUM_TEST_ALLOCATION_EXIT": "committed"},
    )
    canonical = (project / "state/bo_state.json").read_bytes()
    failed = invoke(project, "rebuild-optimizer", "--reason", "recover", success=False)
    assert "recover-allocation" in failed.stderr
    assert (project / "state/bo_state.json").read_bytes() == canonical and (
        project / JOURNAL
    ).exists()
    invoke(project, "recover-allocation")
    invoke(project, "rebuild-optimizer", "--reason", "recover")


def test_rebuild_rejects_semantic_changes_invalid_records_and_escaping_snapshot(tmp_path):
    project = seeded_campaign(tmp_path)
    before = state(project)
    canonical_path = project / "state/bo_state.json"
    config_path = project / "parameter_space.json"
    parameters = config_path.read_bytes()
    config_path.write_text(
        json.dumps({"parameters": [{"name": "x", "type": "float", "bounds": [0, 0.9]}]})
    )
    failed = invoke(project, "rebuild-optimizer", "--reason", "bounds edited", success=False)
    assert "configuration changed" in failed.stderr
    config_path.write_bytes(parameters)
    broken = copy.deepcopy(before)
    broken["pending"][0]["params"]["x"] = 2
    canonical_path.write_text(json.dumps(broken))
    assert (
        "outside its bounds"
        in invoke(project, "rebuild-optimizer", "--reason", "invalid point", success=False).stderr
    )
    broken = copy.deepcopy(before)
    broken["optimizer"]["snapshot"]["path"] = "../outside.json"
    canonical_path.write_text(json.dumps(broken))
    assert (
        "escapes the optimizer directory"
        in invoke(project, "rebuild-optimizer", "--reason", "invalid pointer", success=False).stderr
    )
    assert not (project / "state/optimizer/ax/rebuilds").exists()


def test_older_metadata_without_fingerprint_is_marked_unverified(tmp_path):
    project = seeded_campaign(tmp_path)
    canonical = state(project)
    for key in ("fingerprint", "lineage", "generation"):
        del canonical["optimizer"][key]
    (project / "state/bo_state.json").write_text(json.dumps(canonical))
    (project / canonical["optimizer"]["snapshot"]["path"]).unlink()
    result = json.loads(
        invoke(project, "rebuild-optimizer", "--reason", "old snapshot unavailable").stdout
    )
    assert result["rebuild"]["configuration_verified"] is False
    assert result["rebuild"]["previous_lineage"] is None
    assert state(project)["optimizer"]["fingerprint"]


def test_next_suggest_finishes_committed_rebuild_before_generation(tmp_path):
    project = seeded_campaign(tmp_path)
    invoke(
        project,
        "rebuild-optimizer",
        "--reason",
        "recover",
        success=False,
        env={"LOOPTIMUM_TEST_ALLOCATION_EXIT": "rebuild_committed"},
    )
    identifier = state(project)["optimizer"]["last_rebuild"]["rebuild_id"]
    assert json.loads(invoke(project, "suggest", "--json-only").stdout)["trial_id"] == 3
    assert "pending_rebuild_event" not in state(project)["optimizer"]
    assert state(project)["optimizer"]["last_rebuild"]["rebuild_id"] == identifier


def test_rebuild_obeys_campaign_lock_and_preserves_worker_failures(tmp_path):
    import fcntl

    project = seeded_campaign(tmp_path)
    canonical = (project / "state/bo_state.json").read_bytes()
    with (project / "state/.looptimum.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        failed = invoke(
            project, "rebuild-optimizer", "--reason", "recover", "--fail-fast", success=False
        )
        assert failed.returncode != 0 and "lock" in failed.stderr.lower()
    (project / "vendor/looptimum_shared/optimizer_ax_worker.py").write_text(
        "raise RuntimeError('worker crashed')"
    )
    failed = invoke(project, "rebuild-optimizer", "--reason", "recover", success=False)
    assert "worker exited unsuccessfully" in failed.stderr
    assert (project / "state/bo_state.json").read_bytes() == canonical
    assert not (project / "state/optimizer/ax/rebuilds").exists()


def test_explicit_rebuild_records_environment_transition_and_survives_reset_restore(tmp_path):
    import hashlib

    project = seeded_campaign(tmp_path)
    canonical = state(project)
    pointer = canonical["optimizer"]["snapshot"]
    snapshot = json.loads((project / pointer["path"]).read_text())
    snapshot["versions"]["botorch"] = "previous-stack"
    digest = hashlib.sha256(
        json.dumps(snapshot, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    pointer["path"] = f"state/optimizer/ax/snapshots/{digest}.json"
    pointer["sha256"] = digest
    (project / pointer["path"]).write_text(json.dumps(snapshot))
    (project / "state/bo_state.json").write_text(json.dumps(canonical))
    assert "dependency versions changed" in invoke(project, "suggest", success=False).stderr
    result = json.loads(
        invoke(project, "rebuild-optimizer", "--reason", "repaired environment").stdout
    )
    recovery = result["rebuild"]
    assert recovery["previous_versions"]["botorch"] == "previous-stack"
    assert recovery["versions"]["botorch"] is None
    backup = project / recovery["backup_directory"]
    state_bytes = (project / "state/bo_state.json").read_bytes()
    snapshot_bytes = (backup / "snapshot-before.bin").read_bytes()
    invoke(project, "reset", "--yes")
    archive = next((project / "state/reset_archives").iterdir())
    invoke(project, "restore", "--archive-id", archive.name, "--yes")
    assert (project / "state/bo_state.json").read_bytes() == state_bytes
    assert (backup / "snapshot-before.bin").read_bytes() == snapshot_bytes
    invoke(project, "validate", "--strict")


def test_invalid_pending_rebuild_event_does_not_block_canonical_operations(tmp_path):
    project = seeded_campaign(tmp_path)
    invoke(
        project,
        "rebuild-optimizer",
        "--reason",
        "recover",
        success=False,
        env={"LOOPTIMUM_TEST_ALLOCATION_EXIT": "rebuild_committed"},
    )
    canonical = state(project)
    canonical["optimizer"]["pending_rebuild_event"]["reason"] = "edited"
    (project / "state/bo_state.json").write_text(json.dumps(canonical))
    status = json.loads(invoke(project, "status").stdout)
    assert status["optimizer_recovery"]["status"] == "invalid"
    assert (
        "Invalid pending optimizer rebuild event"
        in invoke(project, "suggest", success=False).stderr
    )
    invoke(project, "cancel", "--trial-id", "2")
    assert state(project)["pending"] == []
