from __future__ import annotations

import csv
import json
import shutil
import subprocess
import sys
import time
from pathlib import Path

import pytest

_LOCK_HOLDER_SCRIPT = "\n".join(
    [
        "import fcntl",
        "import pathlib",
        "import sys",
        "import time",
        "path = pathlib.Path(sys.argv[1])",
        "path.parent.mkdir(parents=True, exist_ok=True)",
        "handle = path.open('a+', encoding='utf-8')",
        "fcntl.flock(handle.fileno(), fcntl.LOCK_EX)",
        "print('LOCKED', flush=True)",
        "time.sleep(30)",
    ]
)


def run_cmd(
    project_root: Path, *args: str, expect_ok: bool = True
) -> subprocess.CompletedProcess[str]:
    cmd = [sys.executable, "run_bo.py", *args]
    out = subprocess.run(cmd, cwd=project_root, capture_output=True, text=True)
    if expect_ok and out.returncode != 0:
        raise AssertionError(
            f"Command failed: {' '.join(cmd)}\nSTDOUT:\n{out.stdout}\nSTDERR:\n{out.stderr}"
        )
    return out


@pytest.fixture
def template_copy(tmp_path: Path) -> Path:
    src = Path(__file__).resolve().parents[1]
    dst = tmp_path / "template"
    subprocess.run(["cp", "-R", str(src), str(dst)], check=True)
    shared_src = src.parent / "_shared"
    if shared_src.exists():
        subprocess.run(["cp", "-R", str(shared_src), str(tmp_path / "_shared")], check=True)
    for p in [
        dst / "state" / "bo_state.json",
        dst / "state" / "observations.csv",
        dst / "state" / "acquisition_log.jsonl",
        dst / "state" / "event_log.jsonl",
        dst / "state" / ".looptimum.lock",
        dst / "state" / "report.json",
        dst / "state" / "report.md",
        dst / "examples" / "_demo_result.json",
    ]:
        if p.exists():
            p.unlink()
    trials_dir = dst / "state" / "trials"
    if trials_dir.exists():
        shutil.rmtree(trials_dir)
    return dst


def _parse_suggestion(stdout: str) -> dict:
    lines = [line for line in stdout.strip().splitlines() if line.strip()]
    return json.loads("\n".join(lines[:-1]))


def _start_lock_holder(lock_path: Path) -> subprocess.Popen[str]:
    holder = subprocess.Popen(
        [sys.executable, "-c", _LOCK_HOLDER_SCRIPT, str(lock_path)],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    assert holder.stdout is not None
    ready = holder.stdout.readline().strip()
    assert ready == "LOCKED"
    return holder


def _stop_lock_holder(holder: subprocess.Popen[str]) -> None:
    if holder.poll() is None:
        holder.terminate()
        try:
            holder.wait(timeout=5)
        except subprocess.TimeoutExpired:
            holder.kill()
            holder.wait(timeout=5)


def _conditional_parameter_space() -> dict:
    return {
        "parameters": [
            {
                "name": "momentum",
                "type": "float",
                "bounds": [0.0, 0.99],
                "when": {"gate": 1},
            },
            {"name": "x", "type": "float", "bounds": [0.0, 1.0]},
            {"name": "gate", "type": "int", "bounds": [0, 1]},
        ]
    }


def _write_weighted_sum_objective_schema(project_root: Path) -> None:
    (project_root / "objective_schema.json").write_text(
        json.dumps(
            {
                "primary_objective": {"name": "loss", "direction": "minimize"},
                "secondary_objectives": [{"name": "throughput", "direction": "maximize"}],
                "scalarization": {
                    "policy": "weighted_sum",
                    "weights": {"loss": 1.0, "throughput": 1.0},
                },
            },
            indent=2,
        ),
        encoding="utf-8",
    )


def test_report_generates_json_and_markdown(template_copy: Path) -> None:
    suggestion = _parse_suggestion(run_cmd(template_copy, "suggest").stdout)
    payload = {
        "trial_id": suggestion["trial_id"],
        "params": suggestion["params"],
        "objectives": {"loss": 0.25},
        "status": "ok",
    }
    path = template_copy / "examples" / "_report_result.json"
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    run_cmd(template_copy, "ingest", "--results-file", str(path))

    out = run_cmd(template_copy, "report", "--top-n", "3")
    assert "Generated report files:" in out.stdout
    report_json = template_copy / "state" / "report.json"
    report_md = template_copy / "state" / "report.md"
    assert report_json.exists()
    assert report_md.exists()
    report = json.loads(report_json.read_text(encoding="utf-8"))
    assert report["counts"]["observations"] == 1
    assert report["best"]["trial_id"] == suggestion["trial_id"]
    assert isinstance(report["top_trials"][0]["suggested_at"], float)
    assert isinstance(report["top_trials"][0]["completed_at"], float)
    assert isinstance(report["top_trials"][0]["artifact_path"], str)
    assert report["terminal_trials"] == []
    assert "Looptimum Report" in report_md.read_text(encoding="utf-8")


def test_report_includes_multi_objective_pareto_and_manifest_metadata(
    template_copy: Path,
) -> None:
    _write_weighted_sum_objective_schema(template_copy)

    first = _parse_suggestion(run_cmd(template_copy, "suggest").stdout)
    first_payload = {
        "trial_id": first["trial_id"],
        "params": first["params"],
        "objectives": {"loss": 0.3, "throughput": 2.0},
        "status": "ok",
    }
    first_path = template_copy / "examples" / "_report_multi_objective_first.json"
    first_path.write_text(json.dumps(first_payload, indent=2), encoding="utf-8")
    run_cmd(template_copy, "ingest", "--results-file", str(first_path))

    second = _parse_suggestion(run_cmd(template_copy, "suggest").stdout)
    second_payload = {
        "trial_id": second["trial_id"],
        "params": second["params"],
        "objectives": {"loss": 0.2, "throughput": 1.0},
        "status": "ok",
    }
    second_path = template_copy / "examples" / "_report_multi_objective_second.json"
    second_path.write_text(json.dumps(second_payload, indent=2), encoding="utf-8")
    run_cmd(template_copy, "ingest", "--results-file", str(second_path))

    run_cmd(template_copy, "report", "--top-n", "5")
    report = json.loads((template_copy / "state" / "report.json").read_text(encoding="utf-8"))
    report_md = (template_copy / "state" / "report.md").read_text(encoding="utf-8")

    assert report["objective"]["best_objective_name"] == "scalarized"
    assert report["objective"]["scalarization_policy"] == "weighted_sum"
    assert report["objective_config"]["objective_names"] == ["loss", "throughput"]
    assert report["best"]["trial_id"] == first["trial_id"]
    assert report["best"]["objective_vector"] == first_payload["objectives"]

    top_by_trial = {int(row["trial_id"]): row for row in report["top_trials"]}
    assert top_by_trial[first["trial_id"]]["objective_value"] == 0.3
    assert top_by_trial[first["trial_id"]]["scalarized_objective"] == pytest.approx(-0.85)
    assert top_by_trial[first["trial_id"]]["objective_vector"] == first_payload["objectives"]
    assert top_by_trial[second["trial_id"]]["objective_vector"] == second_payload["objectives"]

    assert report["pareto_front"]["trial_ids"] == [first["trial_id"], second["trial_id"]]
    trace_by_trial = {int(row["trial_id"]): row for row in report["objective_trace"]}
    assert trace_by_trial[first["trial_id"]]["objective_vector"] == first_payload["objectives"]
    assert trace_by_trial[second["trial_id"]]["objective_vector"] == second_payload["objectives"]

    manifest = json.loads(
        (
            template_copy / "state" / "trials" / f"trial_{first['trial_id']}" / "manifest.json"
        ).read_text(encoding="utf-8")
    )
    assert manifest["objective_name"] == "loss"
    assert manifest["objective_vector"] == first_payload["objectives"]
    assert manifest["scalarization_policy"] == "weighted_sum"
    assert manifest["scalarized_objective"] == pytest.approx(-0.85)

    assert "Pareto Front" in report_md
    assert "weighted_sum" in report_md


def test_report_includes_terminal_traceability_fields_for_timeout_trial(
    template_copy: Path,
) -> None:
    suggestion = _parse_suggestion(run_cmd(template_copy, "suggest").stdout)
    payload = {
        "trial_id": suggestion["trial_id"],
        "params": suggestion["params"],
        "objectives": {"loss": None},
        "status": "timeout",
        "penalty_objective": 4321.0,
    }
    path = template_copy / "examples" / "_report_timeout_result.json"
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    run_cmd(template_copy, "ingest", "--results-file", str(path))

    run_cmd(template_copy, "report", "--top-n", "3")
    report = json.loads((template_copy / "state" / "report.json").read_text(encoding="utf-8"))
    assert len(report["terminal_trials"]) == 1
    terminal = report["terminal_trials"][0]
    assert terminal["trial_id"] == suggestion["trial_id"]
    assert terminal["status"] == "timeout"
    assert terminal["terminal_reason"] == "status=timeout"
    assert terminal["penalty_objective"] == 4321.0
    assert isinstance(terminal["suggested_at"], float)
    assert isinstance(terminal["completed_at"], float)
    assert isinstance(terminal["artifact_path"], str)


def test_report_and_csv_handle_conditional_param_omission_across_trials(
    template_copy: Path,
) -> None:
    (template_copy / "parameter_space.json").write_text(
        json.dumps(_conditional_parameter_space(), indent=2), encoding="utf-8"
    )
    cfg_path = template_copy / "bo_config.json"
    cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
    cfg["seed"] = 3
    cfg["initial_random_trials"] = 2
    cfg_path.write_text(json.dumps(cfg, indent=2), encoding="utf-8")

    first = _parse_suggestion(run_cmd(template_copy, "suggest").stdout)
    assert first["params"]["gate"] == 0
    first_payload = {
        "trial_id": first["trial_id"],
        "params": {**first["params"], "momentum": 0.41},
        "objectives": {"loss": 0.3},
        "status": "ok",
    }
    first_path = template_copy / "examples" / "_report_conditional_first.json"
    first_path.write_text(json.dumps(first_payload, indent=2), encoding="utf-8")
    run_cmd(template_copy, "ingest", "--results-file", str(first_path))

    second = _parse_suggestion(run_cmd(template_copy, "suggest").stdout)
    assert second["params"]["gate"] == 1
    assert set(second["params"]) == {"gate", "momentum", "x"}
    second_payload = {
        "trial_id": second["trial_id"],
        "params": second["params"],
        "objectives": {"loss": 0.2},
        "status": "ok",
    }
    second_path = template_copy / "examples" / "_report_conditional_second.json"
    second_path.write_text(json.dumps(second_payload, indent=2), encoding="utf-8")
    run_cmd(template_copy, "ingest", "--results-file", str(second_path))

    run_cmd(template_copy, "report", "--top-n", "3")

    with (template_copy / "state" / "observations.csv").open(
        encoding="utf-8", newline=""
    ) as handle:
        rows = {int(row["trial_id"]): row for row in csv.DictReader(handle)}
    assert rows[first["trial_id"]]["param_momentum"] == ""
    assert rows[second["trial_id"]]["param_momentum"] != ""

    report = json.loads((template_copy / "state" / "report.json").read_text(encoding="utf-8"))
    top_by_trial = {int(row["trial_id"]): row for row in report["top_trials"]}
    assert top_by_trial[first["trial_id"]]["params"] == first["params"]
    assert top_by_trial[second["trial_id"]]["params"] == second["params"]


def _seed_runtime_artifacts_for_reset(template_copy: Path) -> None:
    suggestion = _parse_suggestion(run_cmd(template_copy, "suggest").stdout)
    payload = {
        "trial_id": suggestion["trial_id"],
        "params": suggestion["params"],
        "objectives": {"loss": 0.42},
        "status": "ok",
    }
    result_path = template_copy / "examples" / "_reset_seed_result.json"
    result_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    run_cmd(template_copy, "ingest", "--results-file", str(result_path))
    run_cmd(template_copy, "report", "--top-n", "3")
    (template_copy / "examples" / "_demo_result.json").write_text("{}", encoding="utf-8")


def test_reset_requires_yes_in_non_interactive_mode(template_copy: Path) -> None:
    run_cmd(template_copy, "suggest")
    out = run_cmd(template_copy, "reset", expect_ok=False)
    assert out.returncode != 0
    assert "re-run with --yes" in out.stderr
    assert (template_copy / "state" / "bo_state.json").exists()


def test_reset_archives_by_default_and_clears_runtime_artifacts(template_copy: Path) -> None:
    _seed_runtime_artifacts_for_reset(template_copy)

    out = run_cmd(template_copy, "reset", "--yes")
    assert "Campaign reset completed." in out.stdout
    assert "Archive:" in out.stdout

    assert not (template_copy / "state" / "bo_state.json").exists()
    assert not (template_copy / "state" / "observations.csv").exists()
    assert not (template_copy / "state" / "acquisition_log.jsonl").exists()
    assert not (template_copy / "state" / ".looptimum.lock").exists()
    assert not (template_copy / "state" / "report.json").exists()
    assert not (template_copy / "state" / "report.md").exists()
    assert not (template_copy / "state" / "trials").exists()
    assert not (template_copy / "examples" / "_demo_result.json").exists()

    event_log = template_copy / "state" / "event_log.jsonl"
    assert event_log.exists()
    lines = event_log.read_text(encoding="utf-8").splitlines()
    assert any('"event": "campaign_reset"' in line for line in lines)

    archives_root = template_copy / "state" / "reset_archives"
    archives = sorted(path for path in archives_root.iterdir() if path.is_dir())
    assert len(archives) == 1
    archive_dir = archives[0]
    assert (archive_dir / "state" / "bo_state.json").exists()
    assert (archive_dir / "state" / "trials").exists()
    assert (archive_dir / "examples" / "_demo_result.json").exists()


def test_validate_warnings_exit_zero_and_strict_nonzero(template_copy: Path) -> None:
    cfg_path = template_copy / "bo_config.json"
    cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
    cfg["max_pending_age_seconds"] = 60
    cfg_path.write_text(json.dumps(cfg, indent=2), encoding="utf-8")

    _parse_suggestion(run_cmd(template_copy, "suggest").stdout)
    state_path = template_copy / "state" / "bo_state.json"
    state = json.loads(state_path.read_text(encoding="utf-8"))
    state["pending"][0]["suggested_at"] = time.time() - 3600
    state_path.write_text(json.dumps(state, indent=2), encoding="utf-8")

    out = run_cmd(template_copy, "validate")
    assert out.returncode == 0
    assert "WARNING:" in out.stdout

    strict = run_cmd(template_copy, "validate", "--strict", expect_ok=False)
    assert strict.returncode != 0
    assert "WARNING:" in strict.stdout


def test_validate_hard_failure_for_corrupt_state_file(template_copy: Path) -> None:
    state_path = template_copy / "state" / "bo_state.json"
    state_path.write_text("{not valid json", encoding="utf-8")
    out = run_cmd(template_copy, "validate", expect_ok=False)
    assert out.returncode != 0
    assert "ERROR: state load failure:" in out.stdout


def test_validate_hard_failure_for_malformed_bo_config(template_copy: Path) -> None:
    cfg_path = template_copy / "bo_config.json"
    cfg_path.write_text("{not valid json", encoding="utf-8")

    out = run_cmd(template_copy, "validate", expect_ok=False)
    assert out.returncode != 0
    assert "ERROR: config load failure:" in out.stdout


def test_validate_hard_failure_for_invalid_max_pending_trials(template_copy: Path) -> None:
    cfg_path = template_copy / "bo_config.json"
    cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
    cfg["max_pending_trials"] = 0
    cfg_path.write_text(json.dumps(cfg, indent=2), encoding="utf-8")

    out = run_cmd(template_copy, "validate", expect_ok=False)
    assert out.returncode != 0
    assert "ERROR: config validation failure: max_pending_trials must be >= 1" in out.stdout


def test_validate_hard_failure_for_invalid_worker_leases_config(template_copy: Path) -> None:
    cfg_path = template_copy / "bo_config.json"
    cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
    cfg["worker_leases"] = {"enabled": "yes"}
    cfg_path.write_text(json.dumps(cfg, indent=2), encoding="utf-8")

    out = run_cmd(template_copy, "validate", expect_ok=False)
    assert out.returncode != 0
    assert "ERROR: config validation failure: worker_leases.enabled must be a boolean" in out.stdout


def test_validate_hard_failure_for_malformed_parameter_space(template_copy: Path) -> None:
    space_path = template_copy / "parameter_space.json"
    space_path.write_text("{}", encoding="utf-8")

    out = run_cmd(template_copy, "validate", expect_ok=False)
    assert out.returncode != 0
    assert "ERROR: parameter_space validation failure:" in out.stdout
    assert "field=$.parameters" in out.stdout


def test_validate_hard_failure_for_duplicate_observation_trial_ids(template_copy: Path) -> None:
    suggestion = _parse_suggestion(run_cmd(template_copy, "suggest").stdout)
    payload = {
        "trial_id": suggestion["trial_id"],
        "params": suggestion["params"],
        "objectives": {"loss": 0.25},
        "status": "ok",
    }
    path = template_copy / "examples" / "_dup_obs_validate.json"
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    run_cmd(template_copy, "ingest", "--results-file", str(path))

    state_path = template_copy / "state" / "bo_state.json"
    state = json.loads(state_path.read_text(encoding="utf-8"))
    state["observations"].append(dict(state["observations"][0]))
    state_path.write_text(json.dumps(state, indent=2), encoding="utf-8")

    out = run_cmd(template_copy, "validate", expect_ok=False)
    assert out.returncode != 0
    assert "state.observations contains duplicate trial_id values" in out.stdout


def test_validate_hard_failure_for_inconsistent_best_ranking(template_copy: Path) -> None:
    first = _parse_suggestion(run_cmd(template_copy, "suggest").stdout)
    first_payload = {
        "trial_id": first["trial_id"],
        "params": first["params"],
        "objectives": {"loss": 0.1},
        "status": "ok",
    }
    first_path = template_copy / "examples" / "_best_rank_first.json"
    first_path.write_text(json.dumps(first_payload, indent=2), encoding="utf-8")
    run_cmd(template_copy, "ingest", "--results-file", str(first_path))

    second = _parse_suggestion(run_cmd(template_copy, "suggest").stdout)
    second_payload = {
        "trial_id": second["trial_id"],
        "params": second["params"],
        "objectives": {"loss": 0.3},
        "status": "ok",
    }
    second_path = template_copy / "examples" / "_best_rank_second.json"
    second_path.write_text(json.dumps(second_payload, indent=2), encoding="utf-8")
    run_cmd(template_copy, "ingest", "--results-file", str(second_path))

    state_path = template_copy / "state" / "bo_state.json"
    state = json.loads(state_path.read_text(encoding="utf-8"))
    state["best"] = {
        "trial_id": second["trial_id"],
        "objective_name": "loss",
        "objective_value": 0.3,
        "updated_at": state["best"]["updated_at"],
    }
    state_path.write_text(json.dumps(state, indent=2), encoding="utf-8")

    out = run_cmd(template_copy, "validate", expect_ok=False)
    assert out.returncode != 0
    assert (
        "state.best.trial_id must reference the optimal ok trial for the configured scalarization policy"
        in out.stdout
    )


def test_validate_hard_failure_for_corrupt_event_log_jsonl(template_copy: Path) -> None:
    event_log_path = template_copy / "state" / "event_log.jsonl"
    event_log_path.parent.mkdir(parents=True, exist_ok=True)
    event_log_path.write_text("{invalid json\n", encoding="utf-8")

    out = run_cmd(template_copy, "validate", expect_ok=False)
    assert out.returncode != 0
    assert "event_log_file line 1 invalid JSON:" in out.stdout


def test_validate_hard_failure_for_missing_trial_manifest(template_copy: Path) -> None:
    trial_dir_path = template_copy / "state" / "trials" / "trial_123"
    trial_dir_path.mkdir(parents=True, exist_ok=True)

    out = run_cmd(template_copy, "validate", expect_ok=False)
    assert out.returncode != 0
    assert "missing manifest for trial directory:" in out.stdout


def test_doctor_json_reports_backend_and_status(template_copy: Path) -> None:
    out = run_cmd(template_copy, "doctor", "--json")
    payload = json.loads(out.stdout)
    assert payload["backend"]["configured"] == "rbf_proxy"
    assert payload["status"]["observations"] == 0
    assert payload["status"]["pending"] == 0
    assert "paths" in payload["status"]


def test_ingest_atomic_write_injection_preserves_last_good_state(
    template_copy: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    suggestion = _parse_suggestion(run_cmd(template_copy, "suggest").stdout)
    payload = {
        "trial_id": suggestion["trial_id"],
        "params": suggestion["params"],
        "objectives": {"loss": 0.31},
        "status": "ok",
    }
    result_path = template_copy / "examples" / "_atomic_fail_ingest.json"
    result_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    state_path = template_copy / "state" / "bo_state.json"
    before = json.loads(state_path.read_text(encoding="utf-8"))
    monkeypatch.setenv("LOOPTIMUM_TEST_ATOMIC_FAIL_BASENAME", "bo_state.json")

    out = run_cmd(template_copy, "ingest", "--results-file", str(result_path), expect_ok=False)
    assert out.returncode != 0
    assert "Injected atomic write failure" in out.stderr

    after = json.loads(state_path.read_text(encoding="utf-8"))
    assert after == before

    monkeypatch.delenv("LOOPTIMUM_TEST_ATOMIC_FAIL_BASENAME", raising=False)
    run_cmd(template_copy, "ingest", "--results-file", str(result_path))
    replay = run_cmd(template_copy, "ingest", "--results-file", str(result_path))
    assert "No-op:" in replay.stdout
    status = json.loads(run_cmd(template_copy, "status").stdout)
    assert status["observations"] == 1
    assert status["pending"] == 0


def test_suggest_fail_fast_on_lock_contention_reports_clean_error(template_copy: Path) -> None:
    if sys.platform == "win32":
        pytest.skip("fcntl lock semantics are POSIX-only")

    holder = _start_lock_holder(template_copy / "state" / ".looptimum.lock")
    try:
        out = run_cmd(
            template_copy,
            "suggest",
            "--fail-fast",
            "--lock-timeout-seconds",
            "0",
            expect_ok=False,
        )
    finally:
        _stop_lock_holder(holder)

    assert out.returncode != 0
    assert "Could not acquire lock" in out.stderr
    assert "Traceback" not in out.stderr


def test_suggest_timeout_on_lock_contention_reports_clean_error(template_copy: Path) -> None:
    if sys.platform == "win32":
        pytest.skip("fcntl lock semantics are POSIX-only")

    holder = _start_lock_holder(template_copy / "state" / ".looptimum.lock")
    try:
        out = run_cmd(
            template_copy,
            "suggest",
            "--lock-timeout-seconds",
            "0.1",
            expect_ok=False,
        )
    finally:
        _stop_lock_holder(holder)

    assert out.returncode != 0
    assert "Could not acquire lock (timeout)" in out.stderr
    assert "Traceback" not in out.stderr


def test_batched_suggest_fail_fast_on_lock_contention_has_no_side_effects(
    template_copy: Path,
) -> None:
    if sys.platform == "win32":
        pytest.skip("fcntl lock semantics are POSIX-only")

    holder = _start_lock_holder(template_copy / "state" / ".looptimum.lock")
    try:
        out = run_cmd(
            template_copy,
            "suggest",
            "--count",
            "3",
            "--jsonl",
            "--fail-fast",
            "--lock-timeout-seconds",
            "0",
            expect_ok=False,
        )
    finally:
        _stop_lock_holder(holder)

    assert out.returncode != 0
    assert "Could not acquire lock (fail-fast)" in out.stderr
    assert not (template_copy / "state" / "bo_state.json").exists()
    assert not (template_copy / "state" / "acquisition_log.jsonl").exists()
    assert not (template_copy / "state" / "event_log.jsonl").exists()
    assert not (template_copy / "state" / "trials").exists()


def test_lease_heartbeat_fail_fast_on_lock_contention_preserves_pending_state(
    template_copy: Path,
) -> None:
    if sys.platform == "win32":
        pytest.skip("fcntl lock semantics are POSIX-only")

    cfg_path = template_copy / "bo_config.json"
    cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
    cfg["worker_leases"]["enabled"] = True
    cfg_path.write_text(json.dumps(cfg, indent=2), encoding="utf-8")

    suggestion = _parse_suggestion(run_cmd(template_copy, "suggest").stdout)
    trial_id = suggestion["trial_id"]
    lease_token = suggestion["lease_token"]
    state_path = template_copy / "state" / "bo_state.json"
    manifest_path = template_copy / "state" / "trials" / f"trial_{trial_id}" / "manifest.json"
    before_state = json.loads(state_path.read_text(encoding="utf-8"))
    before_manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

    holder = _start_lock_holder(template_copy / "state" / ".looptimum.lock")
    try:
        out = run_cmd(
            template_copy,
            "heartbeat",
            "--trial-id",
            str(trial_id),
            "--lease-token",
            lease_token,
            "--heartbeat-note",
            "lock-contended",
            "--fail-fast",
            "--lock-timeout-seconds",
            "0",
            expect_ok=False,
        )
    finally:
        _stop_lock_holder(holder)

    assert out.returncode != 0
    assert "Could not acquire lock (fail-fast)" in out.stderr
    after_state = json.loads(state_path.read_text(encoding="utf-8"))
    after_manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert after_state == before_state
    assert after_manifest == before_manifest


def test_read_commands_work_while_mutation_lock_is_held(template_copy: Path) -> None:
    if sys.platform == "win32":
        pytest.skip("fcntl lock semantics are POSIX-only")

    holder = _start_lock_holder(template_copy / "state" / ".looptimum.lock")
    try:
        status = run_cmd(template_copy, "status")
        validate = run_cmd(template_copy, "validate")
        doctor = run_cmd(template_copy, "doctor", "--json")
    finally:
        _stop_lock_holder(holder)

    status_payload = json.loads(status.stdout)
    doctor_payload = json.loads(doctor.stdout)
    assert status_payload["observations"] == 0
    assert "Validation passed." in validate.stdout
    assert doctor_payload["status"]["observations"] == 0


@pytest.mark.parametrize(
    ("command", "extra_args"),
    [
        ("suggest", []),
        ("ingest", []),
        ("cancel", ["--trial-id", "1"]),
        ("retire", ["--trial-id", "1"]),
        ("heartbeat", ["--trial-id", "1"]),
        ("report", []),
    ],
)
def test_all_mutating_commands_fail_fast_when_lock_is_held(
    template_copy: Path, command: str, extra_args: list[str]
) -> None:
    if sys.platform == "win32":
        pytest.skip("fcntl lock semantics are POSIX-only")

    holder = _start_lock_holder(template_copy / "state" / ".looptimum.lock")
    try:
        out = run_cmd(
            template_copy,
            command,
            "--fail-fast",
            "--lock-timeout-seconds",
            "0",
            *extra_args,
            expect_ok=False,
        )
    finally:
        _stop_lock_holder(holder)

    assert out.returncode != 0
    assert "Could not acquire lock (fail-fast)" in out.stderr
    assert "Traceback" not in out.stderr
