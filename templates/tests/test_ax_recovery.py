"""Real controller exits with a deterministic worker; no optional dependencies required."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
JOURNAL = "state/optimizer/ax/allocation.json"
FAKE_WORKER = """
import json
import sys
from pathlib import Path
from optimizer_backend import canonical_digest, dependency_versions

request = json.load(sys.stdin)
Path("ax_request.json").write_text(json.dumps(request))
candidates = []
mapping = dict(request["mapping"])
signatures = dict(request["signatures"])
for row in request["records"]:
    mapping.setdefault(str(row["trial_id"]), row["trial_id"] - 1)
    signatures[str(row["trial_id"])] = row["signature"]
for offset in range(request["count"]):
    trial_id = request["next_trial_id"] + offset
    params = {p["name"]: trial_id / 100 for p in request["parameters"]}
    mapping[str(trial_id)] = trial_id - 1
    signatures[str(trial_id)] = canonical_digest(
        {"params": params, "status": "pending", "objectives": None}
    )
    candidates.append({"params": params, "ax_trial_index": trial_id - 1, "generation_node": "test"})
print(json.dumps({"ok": True, "result": {
    "snapshot": {"test_generation": request["generation"]},
    "mapping": mapping, "signatures": signatures, "candidates": candidates,
    "versions": {name: None for name in dependency_versions()}, "attempts": 1,
}}))
"""


def invoke(project, *args, success=True, env=None):
    result = subprocess.run(
        [sys.executable, "-S", "run_bo.py", *args],
        cwd=project,
        text=True,
        capture_output=True,
        env={**os.environ, **(env or {})},
        timeout=15,
    )
    if success:
        assert result.returncode == 0, result.stdout + result.stderr
    return result


def campaign(tmp_path, variant="bo_client"):
    project = tmp_path / "controller"
    subprocess.run(
        [
            sys.executable,
            str(ROOT / "templates/_shared/vendor_copy.py"),
            str(ROOT / "templates" / variant),
            str(project),
        ],
        capture_output=True,
        check=True,
    )
    config_path = project / "bo_config.json"
    config = json.loads(config_path.read_text())
    config["optimizer"] = {"backend": "ax", "ax": {}}
    config["worker_leases"] = {"enabled": True}
    config["max_pending_age_seconds"] = None
    config_path.write_text(json.dumps(config))
    (project / "parameter_space.json").write_text(
        json.dumps(
            {
                "parameters": [
                    {"name": "x", "type": "float", "bounds": [0, 1]},
                ]
            }
        )
    )
    (project / "objective_schema.json").write_text(
        json.dumps(
            {
                "primary_objective": {"name": "loss", "direction": "minimize"},
            }
        )
    )
    (project / "vendor/looptimum_shared/optimizer_ax_worker.py").write_text(FAKE_WORKER)
    (project / "state").mkdir(exist_ok=True)
    (project / "state/observations.csv").write_text("")
    return project


def state(project):
    return json.loads((project / "state/bo_state.json").read_text())


def rows(project, path):
    file = project / path
    return [json.loads(line) for line in file.read_text().splitlines()] if file.exists() else []


@pytest.mark.parametrize("variant", ["bo_client", "bo_client_full"])
@pytest.mark.parametrize("stage", ["prepared", "committed", "manifests", "decisions", "events"])
def test_process_exit_repairs_exactly_once_without_ax(tmp_path, variant, stage):
    project = campaign(tmp_path, variant)
    stopped = invoke(
        project,
        "suggest",
        "--count",
        "2",
        "--json-only",
        success=False,
        env={"LOOPTIMUM_TEST_ALLOCATION_EXIT": stage},
    )
    assert stopped.returncode == 86 and stopped.stdout == ""
    journal_bytes = (project / JOURNAL).read_bytes()
    status = json.loads(invoke(project, "status").stdout)
    assert status["allocation_recovery"]["status"] == (
        "prepared" if stage == "prepared" else "committed"
    )
    assert (project / JOURNAL).read_bytes() == journal_bytes  # Reads never repair.
    validation = invoke(project, "validate", "--strict", success=False)
    assert validation.returncode != 0 and "recover-allocation" in validation.stdout
    health = invoke(project, "health", "--strict", success=False)
    assert health.returncode != 0
    assert any("recover-allocation" in item for item in json.loads(health.stdout)["warnings"])
    before = (project / "state/bo_state.json").read_bytes() if stage != "prepared" else None
    repaired = json.loads(invoke(project, "recover-allocation").stdout)
    assert repaired["trial_ids"] == [1, 2]
    assert not (project / JOURNAL).exists()
    assert json.loads(invoke(project, "recover-allocation").stdout)["status"] == "clean"
    if stage == "prepared":
        assert repaired["status"] == "discarded_preparation"
        assert not (project / "state/bo_state.json").exists()
        assert not (project / "state/trials").exists()
        assert rows(project, "state/acquisition_log.jsonl") == []
        assert not any(
            row["event"] == "suggestion_created" for row in rows(project, "state/event_log.jsonl")
        )
        assert json.loads(invoke(project, "suggest", "--json-only").stdout)["trial_id"] == 1
    else:
        assert repaired["status"] == "repaired"
        assert (project / "state/bo_state.json").read_bytes() == before
        assert [row["trial_id"] for row in state(project)["pending"]] == [1, 2]
        decisions = rows(project, "state/acquisition_log.jsonl")
        events = [
            row
            for row in rows(project, "state/event_log.jsonl")
            if row["event"] == "suggestion_created"
        ]
        assert [row["trial_id"] for row in decisions] == [1, 2]
        assert [row["trial_id"] for row in events] == [1, 2]
        assert {row["allocation_id"] for row in decisions + events} == {repaired["allocation_id"]}
        for pending in state(project)["pending"]:
            manifest = json.loads(
                (project / f"state/trials/trial_{pending['trial_id']}/manifest.json").read_text()
            )
            assert manifest["lease_token"] == pending["lease_token"]
            assert manifest["params"] == pending["params"]
        invoke(project, "validate", "--strict")
        assert json.loads(invoke(project, "suggest", "--json-only").stdout)["trial_id"] == 3


def test_recovery_itself_can_exit_and_next_suggest_finishes_publication(tmp_path):
    project = campaign(tmp_path)
    invoke(
        project,
        "suggest",
        "--json-only",
        success=False,
        env={"LOOPTIMUM_TEST_ALLOCATION_EXIT": "committed"},
    )
    stopped = invoke(
        project,
        "recover-allocation",
        success=False,
        env={"LOOPTIMUM_TEST_ALLOCATION_EXIT": "decisions"},
    )
    assert stopped.returncode == 86
    next_trial = json.loads(invoke(project, "suggest", "--json-only").stdout)
    assert next_trial["trial_id"] == 2
    assert [row["trial_id"] for row in rows(project, "state/acquisition_log.jsonl")] == [1, 2]
    invoke(project, "validate", "--strict")


@pytest.mark.parametrize("variant", ["bo_client", "bo_client_full"])
def test_recovery_preserves_ingested_result_and_later_heartbeat(tmp_path, variant):
    project = campaign(tmp_path, variant)
    invoke(
        project,
        "suggest",
        "--count",
        "2",
        "--json-only",
        success=False,
        env={"LOOPTIMUM_TEST_ALLOCATION_EXIT": "committed"},
    )
    first, second = state(project)["pending"]
    payload = {
        "trial_id": first["trial_id"],
        "params": first["params"],
        "objectives": {"loss": 0.12},
        "status": "ok",
    }
    (project / "result.json").write_text(json.dumps(payload))
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
        "still running",
    )
    canonical = (project / "state/bo_state.json").read_bytes()
    # A broken optimizer snapshot must not prevent repair or delivery of results.
    (project / state(project)["optimizer"]["snapshot"]["path"]).write_text("{}")
    invoke(project, "recover-allocation")
    assert (project / "state/bo_state.json").read_bytes() == canonical
    manifest = json.loads((project / "state/trials/trial_1/manifest.json").read_text())
    assert manifest["status"] == "ok" and manifest["objective_value"] == 0.12
    assert manifest["artifact_path"] == "state/trials/trial_1/ingest_payload.json"
    other = json.loads((project / "state/trials/trial_2/manifest.json").read_text())
    assert other["status"] == "pending" and other["heartbeat_note"] == "still running"


@pytest.mark.parametrize(
    "basename,committed",
    [
        ("allocation.json", False),
        ("bo_state.json", False),
        ("manifest.json", True),
        ("acquisition_log.jsonl", True),
    ],
)
def test_write_failures_have_an_unambiguous_commit_boundary(tmp_path, basename, committed):
    project = campaign(tmp_path)
    failure = invoke(
        project,
        "suggest",
        "--json-only",
        success=False,
        env={"LOOPTIMUM_TEST_ATOMIC_FAIL_BASENAME": basename},
    )
    assert failure.returncode != 0 and failure.stdout == ""
    assert (project / "state/bo_state.json").exists() is committed
    if committed:
        assert "allocation committed" in failure.stderr
    else:
        assert not (project / "state/trials").exists()
        assert not rows(project, "state/acquisition_log.jsonl")
    invoke(project, "recover-allocation")
    next_trial = json.loads(invoke(project, "suggest", "--json-only").stdout)
    assert next_trial["trial_id"] == (2 if committed else 1)


@pytest.mark.parametrize("variant", ["bo_client", "bo_client_full"])
def test_auto_retirement_is_committed_when_generation_times_out(tmp_path, variant):
    project = campaign(tmp_path, variant)
    first = json.loads(invoke(project, "suggest", "--json-only").stdout)
    config_path = project / "bo_config.json"
    config = json.loads(config_path.read_text())
    config["max_pending_age_seconds"] = 0.000001
    config["optimizer"]["ax"]["generation_timeout_seconds"] = 0.05
    config_path.write_text(json.dumps(config))
    worker = project / "vendor/looptimum_shared/optimizer_ax_worker.py"
    worker.write_text("import time\ntime.sleep(60)\n")
    failed = invoke(project, "suggest", "--json-only", success=False)
    assert failed.returncode != 0 and "generation timed out" in failed.stderr
    current = state(project)
    assert current["pending"] == [] and current["next_trial_id"] == 2
    assert current["observations"][0]["trial_id"] == first["trial_id"]
    assert current["observations"][0]["terminal_reason"] == "retired_stale_auto"
    invoke(project, "validate")


def test_corrupt_journal_blocks_generation_but_not_canonical_operations(tmp_path):
    project = campaign(tmp_path)
    invoke(
        project,
        "suggest",
        "--json-only",
        success=False,
        env={"LOOPTIMUM_TEST_ALLOCATION_EXIT": "committed"},
    )
    journal = project / JOURNAL
    broken = json.loads(journal.read_text())
    broken["allocation"]["suggestions"][0]["params"]["x"] = 0.99
    journal.write_text(json.dumps(broken))
    assert (
        json.loads(invoke(project, "status").stdout)["allocation_recovery"]["status"] == "invalid"
    )
    assert "digest mismatch" in invoke(project, "suggest", success=False).stderr
    assert "digest mismatch" in invoke(project, "recover-allocation", success=False).stderr
    invoke(project, "cancel", "--trial-id", "1")
    assert state(project)["observations"][0]["status"] == "killed"
    assert journal.exists()


@pytest.mark.parametrize("policy,expected", [("weighted_sum", -7.0), ("weighted_tchebycheff", 1.5)])
def test_exact_scalar_bridge_preserves_vectors_import_provenance_and_best(
    tmp_path, policy, expected
):
    project = campaign(tmp_path)
    scalarization = {"policy": policy, "weights": {"loss": 1, "throughput": 3}}
    if policy == "weighted_tchebycheff":
        scalarization["reference_point"] = {"loss": 1, "throughput": 12}
    (project / "objective_schema.json").write_text(
        json.dumps(
            {
                "primary_objective": {"name": "loss", "direction": "minimize"},
                "secondary_objectives": [{"name": "throughput", "direction": "maximize"}],
                "scalarization": scalarization,
            }
        )
    )
    imported = [
        {
            "trial_id": 41,
            "params": {"x": 0.2},
            "objectives": {"loss": 2, "throughput": 10},
            "status": "ok",
        },
        {
            "trial_id": 99,
            "params": {"x": 0.8},
            "objectives": {"loss": 8, "throughput": 2},
            "status": "ok",
        },
        {
            "trial_id": 108,
            "params": {"x": 0.9},
            "objectives": {"loss": None, "throughput": None},
            "status": "failed",
            "penalty_objective": 1000000,
        },
    ]
    (project / "seed.jsonl").write_text("".join(json.dumps(row) + "\n" for row in imported))
    invoke(project, "import-observations", "--input-file", "seed.jsonl")
    invoke(project, "suggest", "--json-only")
    request = json.loads((project / "ax_request.json").read_text())
    assert request["direction"] == "minimize"
    assert request["records"][0]["value"] == pytest.approx(expected)
    assert request["records"][2]["value"] is None  # Reporting penalty never trains the model.
    observed = state(project)
    assert observed["observations"][0]["objectives"] == imported[0]["objectives"]
    assert [row["source_trial_id"] for row in observed["observations"]] == [41, 99, 108]
    assert observed["best"]["trial_id"] == 1
    assert observed["best"]["objective_value"] == pytest.approx(expected)


@pytest.mark.parametrize("change", ["bounds", "objective", "seed", "options", "versions"])
def test_semantic_and_environment_changes_block_before_worker_runs(tmp_path, change):
    project = campaign(tmp_path)
    invoke(project, "suggest", "--json-only")
    request_before = (project / "ax_request.json").read_bytes()
    if change == "bounds":
        (project / "parameter_space.json").write_text(
            json.dumps(
                {
                    "parameters": [
                        {"name": "x", "type": "float", "bounds": [0, 0.5]},
                    ]
                }
            )
        )
    elif change == "objective":
        (project / "objective_schema.json").write_text(
            json.dumps(
                {
                    "primary_objective": {"name": "loss", "direction": "maximize"},
                }
            )
        )
    elif change == "options":
        config_path = project / "bo_config.json"
        config = json.loads(config_path.read_text())
        config["optimizer"]["ax"] = {"initialization_budget": 3}
        config_path.write_text(json.dumps(config))
    else:
        canonical = state(project)
        if change == "seed":
            canonical["meta"]["seed"] += 1
        else:
            # Recompute the digest so this tests version validation, not corruption handling.
            import hashlib

            pointer = canonical["optimizer"]["snapshot"]
            snapshot = json.loads((project / pointer["path"]).read_text())
            snapshot["versions"]["numpy"] = "different-version"
            digest = hashlib.sha256(
                json.dumps(snapshot, sort_keys=True, separators=(",", ":")).encode()
            ).hexdigest()
            pointer["path"] = f"state/optimizer/ax/snapshots/{digest}.json"
            pointer["sha256"] = digest
            (project / pointer["path"]).write_text(json.dumps(snapshot))
        (project / "state/bo_state.json").write_text(json.dumps(canonical))
    before = (project / "state/bo_state.json").read_bytes()
    failed = invoke(project, "suggest", "--json-only", success=False)
    assert failed.returncode != 0
    assert (
        "dependency versions changed" if change == "versions" else "configuration changed"
    ) in failed.stderr
    assert (project / "state/bo_state.json").read_bytes() == before
    assert (project / "ax_request.json").read_bytes() == request_before


@pytest.mark.parametrize(
    "worker_source,expected",
    [
        ("raise RuntimeError('worker crashed')", "worker exited unsuccessfully"),
        ("print('not JSON')", "invalid JSON"),
        ('print(\'{"ok":false,"error":"fit failed","error_type":"RuntimeError"}\')', "fit failed"),
    ],
)
def test_worker_failures_leave_no_public_allocation(tmp_path, worker_source, expected):
    project = campaign(tmp_path)
    (project / "vendor/looptimum_shared/optimizer_ax_worker.py").write_text(worker_source)
    failed = invoke(project, "suggest", "--json-only", success=False)
    assert failed.returncode != 0 and expected in failed.stderr
    assert failed.stdout == ""
    assert not (project / "state/bo_state.json").exists()
    assert not (project / JOURNAL).exists()
    assert not (project / "state/trials").exists()


def test_recovery_obeys_campaign_lock_and_rejects_a_different_history(tmp_path):
    project = campaign(tmp_path)
    invoke(
        project,
        "suggest",
        "--json-only",
        success=False,
        env={"LOOPTIMUM_TEST_ALLOCATION_EXIT": "committed"},
    )
    import fcntl

    with (project / "state/.looptimum.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        blocked = invoke(project, "recover-allocation", "--fail-fast", success=False)
        assert blocked.returncode != 0 and "lock" in blocked.stderr.lower()
    canonical = state(project)
    canonical["pending"][0]["params"]["x"] = 0.999
    (project / "state/bo_state.json").write_text(json.dumps(canonical))
    failed = invoke(project, "recover-allocation", success=False)
    assert "disagrees with committed canonical trials" in failed.stderr
    assert (project / JOURNAL).exists()


@pytest.mark.parametrize("variant", ["bo_client", "bo_client_full"])
def test_reset_restore_keeps_unfinished_allocation_and_snapshot_together(tmp_path, variant):
    project = campaign(tmp_path, variant)
    invoke(
        project,
        "suggest",
        "--json-only",
        success=False,
        env={"LOOPTIMUM_TEST_ALLOCATION_EXIT": "committed"},
    )
    canonical = (project / "state/bo_state.json").read_bytes()
    journal = (project / JOURNAL).read_bytes()
    pointer = state(project)["optimizer"]["snapshot"]["path"]
    snapshot = (project / pointer).read_bytes()
    invoke(project, "reset", "--yes")
    assert not (project / JOURNAL).exists() and not (project / pointer).exists()
    archive = next((project / "state/reset_archives").iterdir())
    assert (archive / JOURNAL).read_bytes() == journal
    invoke(project, "restore", "--archive-id", archive.name, "--yes")
    assert (project / "state/bo_state.json").read_bytes() == canonical
    assert (project / JOURNAL).read_bytes() == journal
    assert (project / pointer).read_bytes() == snapshot
    invoke(project, "recover-allocation")
    assert state(project)["pending"][0]["trial_id"] == 1
    invoke(project, "validate", "--strict")


def test_recovery_requires_original_objective_and_preserves_conflicting_logs(tmp_path):
    project = campaign(tmp_path)
    invoke(
        project,
        "suggest",
        "--json-only",
        success=False,
        env={"LOOPTIMUM_TEST_ALLOCATION_EXIT": "decisions"},
    )
    objective_path = project / "objective_schema.json"
    objective = objective_path.read_bytes()
    objective_path.write_text(
        json.dumps(
            {
                "primary_objective": {"name": "loss", "direction": "maximize"},
            }
        )
    )
    failed = invoke(project, "recover-allocation", success=False)
    assert "objective configuration" in failed.stderr
    objective_path.write_bytes(objective)
    log = project / "state/acquisition_log.jsonl"
    entries = rows(project, "state/acquisition_log.jsonl")
    entries[0]["decision"]["strategy"] = "edited"
    edited = json.dumps(entries[0]) + "\n"
    log.write_text(edited)
    failed = invoke(project, "recover-allocation", success=False)
    assert "Conflicting allocation records" in failed.stderr
    assert log.read_text() == edited and (project / JOURNAL).exists()


def test_malformed_checksummed_journal_does_not_break_status(tmp_path):
    import hashlib

    project = campaign(tmp_path)
    invoke(
        project,
        "suggest",
        "--json-only",
        success=False,
        env={"LOOPTIMUM_TEST_ALLOCATION_EXIT": "committed"},
    )
    journal_path = project / JOURNAL
    envelope = json.loads(journal_path.read_text())
    del envelope["allocation"]["snapshot"]
    envelope["sha256"] = hashlib.sha256(
        json.dumps(
            envelope["allocation"],
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
    ).hexdigest()
    journal_path.write_text(json.dumps(envelope))
    assert (
        json.loads(invoke(project, "status").stdout)["allocation_recovery"]["status"] == "invalid"
    )
    invoke(project, "cancel", "--trial-id", "1")
    assert state(project)["observations"][0]["status"] == "killed"
