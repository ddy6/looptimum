from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


def invoke(
    project: Path, *args: str, failure: str | None = None
) -> subprocess.CompletedProcess[str]:
    env = dict(os.environ)
    if failure:
        env["LOOPTIMUM_TEST_ATOMIC_FAIL_BASENAME"] = failure
    return subprocess.run(
        [sys.executable, "run_bo.py", *args],
        cwd=project,
        env=env,
        text=True,
        capture_output=True,
        timeout=20,
    )


def campaign(tmp_path: Path, variant: str) -> Path:
    project = tmp_path / "campaign"
    result = subprocess.run(
        [
            sys.executable,
            str(ROOT / "templates/_shared/vendor_copy.py"),
            str(ROOT / "templates" / variant),
            str(project),
        ],
        capture_output=True,
        text=True,
        timeout=20,
    )
    assert result.returncode == 0, result.stderr
    cfg = json.loads((project / "bo_config.json").read_text())
    for key in (
        "state_file",
        "observations_csv",
        "event_log_file",
        "acquisition_log_file",
        "trials_dir",
        "lock_file",
        "report_json_file",
        "report_md_file",
        "optimizer_dir",
    ):
        if key in cfg["paths"]:
            cfg["paths"][key] = cfg["paths"][key].replace("state/", "custom/")
    cfg["paths"]["optimizer_dir"] = "custom/optimizer"
    (project / "bo_config.json").write_text(json.dumps(cfg))
    return project


@pytest.mark.parametrize("variant", ["bo_client", "bo_client_demo", "bo_client_full"])
@pytest.mark.parametrize("terminal", ["failed", "killed", "timeout"])
@pytest.mark.parametrize("penalty", [None, 12.5])
def test_ingest_interruption_replay_and_archive_restore_preserve_terminal_observation(
    tmp_path: Path, variant: str, terminal: str, penalty: float | None
) -> None:
    project = campaign(tmp_path, variant)
    suggestion = invoke(project, "suggest", "--json-only")
    assert suggestion.returncode == 0, suggestion.stderr
    trial = json.loads(suggestion.stdout)
    objective = json.loads((project / "objective_schema.json").read_text())["primary_objective"][
        "name"
    ]
    payload = {
        "trial_id": trial["trial_id"],
        "params": trial["params"],
        "objectives": {objective: None},
        "status": terminal,
        "terminal_reason": "bounded fixture",
    }
    if penalty is not None:
        payload["penalty_objective"] = penalty
    result_path = project / "result.json"
    result_path.write_text(json.dumps(payload))
    failed = invoke(project, "ingest", "--results-file", str(result_path), failure="bo_state.json")
    assert failed.returncode != 0
    assert "Injected atomic write failure" in failed.stderr
    before_retry = json.loads((project / "custom/bo_state.json").read_text())
    assert len(before_retry["pending"]) == 1 and before_retry["observations"] == []
    applied = invoke(project, "ingest", "--results-file", str(result_path))
    assert applied.returncode == 0, applied.stderr
    canonical_path = project / "custom/bo_state.json"
    canonical_bytes = canonical_path.read_bytes()
    canonical = json.loads(canonical_bytes)
    assert len(canonical["observations"]) == 1 and not canonical["pending"]
    assert canonical["observations"][0]["status"] == terminal
    assert canonical["observations"][0]["penalty_objective"] == penalty
    assert canonical["next_trial_id"] == 2
    replay = invoke(project, "ingest", "--results-file", str(result_path))
    assert replay.returncode == 0 and "No-op:" in replay.stdout
    assert canonical_path.read_bytes() == canonical_bytes
    payload["terminal_reason"] = "conflicting fixture"
    result_path.write_text(json.dumps(payload))
    assert invoke(project, "ingest", "--results-file", str(result_path)).returncode != 0
    assert canonical_path.read_bytes() == canonical_bytes
    report = invoke(project, "report")
    assert report.returncode == 0, report.stderr
    reset = invoke(project, "reset", "--yes")
    assert reset.returncode == 0, reset.stderr
    archives = list((project / "custom/reset_archives").iterdir())
    assert len(archives) == 1
    restored = invoke(project, "restore", "--archive-id", archives[0].name, "--yes")
    assert restored.returncode == 0, restored.stderr
    restored_state = json.loads(canonical_path.read_text())
    assert restored_state["observations"] == canonical["observations"]
    assert restored_state["next_trial_id"] == 2 and not restored_state["pending"]


def test_portable_demo_rejects_ax_configuration_and_state_without_ax_modules(
    tmp_path: Path,
) -> None:
    project = campaign(tmp_path, "bo_client_demo")
    vendor = project / "vendor/looptimum_shared"
    assert not (vendor / "optimizer_ax.py").exists()
    assert not (vendor / "optimizer_ax_worker.py").exists()
    assert not (vendor / "gp_fit.py").exists()
    assert invoke(project, "validate").returncode == 0
    cfg_path = project / "bo_config.json"
    cfg = json.loads(cfg_path.read_text())
    cfg["optimizer"] = {"backend": "ax"}
    cfg_path.write_text(json.dumps(cfg))
    rejected = invoke(project, "suggest", "--json-only")
    assert rejected.returncode != 0 and "bo_client_demo" in rejected.stderr
    cfg.pop("optimizer")
    cfg_path.write_text(json.dumps(cfg))
    assert invoke(project, "suggest", "--json-only").returncode == 0
    state_path = project / "custom/bo_state.json"
    state = json.loads(state_path.read_text())
    state["schema_version"] = "0.4.0"
    state["optimizer"] = {"backend": "ax", "format_version": 1}
    state_path.write_text(json.dumps(state))
    rejected = invoke(project, "validate")
    assert rejected.returncode != 0 and "optimizer state" in rejected.stdout
