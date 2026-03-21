from __future__ import annotations

import csv
import json
import subprocess
import sys
import time
from pathlib import Path

import pytest
from conftest import parse_suggestion, run_cmd

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


def test_report_generates_json_and_markdown(template_copy) -> None:
    suggestion = parse_suggestion(run_cmd(template_copy, "suggest").stdout)
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
    assert report["objective"]["name"] == "loss"
    assert report["counts"]["observations"] == 1
    assert report["best"]["trial_id"] == suggestion["trial_id"]
    assert report["top_trials"][0]["trial_id"] == suggestion["trial_id"]
    assert isinstance(report["top_trials"][0]["suggested_at"], float)
    assert isinstance(report["top_trials"][0]["completed_at"], float)
    assert isinstance(report["top_trials"][0]["artifact_path"], str)
    assert report["terminal_trials"] == []
    assert report["objective_trace"][0]["artifact_path"] == report["top_trials"][0]["artifact_path"]
    assert "Looptimum Report" in report_md.read_text(encoding="utf-8")


def test_report_carries_traceability_for_failed_or_ejected_trials(template_copy) -> None:
    suggestion = parse_suggestion(run_cmd(template_copy, "suggest").stdout)
    payload = {
        "trial_id": suggestion["trial_id"],
        "params": suggestion["params"],
        "objectives": {"loss": None},
        "status": "timeout",
        "penalty_objective": 1234.0,
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
    assert isinstance(terminal["suggested_at"], float)
    assert isinstance(terminal["completed_at"], float)
    assert terminal["penalty_objective"] == 1234.0
    assert isinstance(terminal["artifact_path"], str)


def test_report_and_csv_handle_conditional_param_omission_across_trials(template_copy) -> None:
    (template_copy / "parameter_space.json").write_text(
        json.dumps(_conditional_parameter_space(), indent=2), encoding="utf-8"
    )
    cfg_path = template_copy / "bo_config.json"
    cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
    cfg["seed"] = 3
    cfg["initial_random_trials"] = 2
    cfg_path.write_text(json.dumps(cfg, indent=2), encoding="utf-8")

    first = parse_suggestion(run_cmd(template_copy, "suggest").stdout)
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

    second = parse_suggestion(run_cmd(template_copy, "suggest").stdout)
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
    suggestion = parse_suggestion(run_cmd(template_copy, "suggest").stdout)
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


def test_reset_requires_yes_in_non_interactive_mode(template_copy) -> None:
    run_cmd(template_copy, "suggest")
    out = run_cmd(template_copy, "reset", expect_ok=False)
    assert out.returncode != 0
    assert "re-run with --yes" in out.stderr
    assert (template_copy / "state" / "bo_state.json").exists()


def test_reset_archives_by_default_and_clears_runtime_artifacts(template_copy) -> None:
    _seed_runtime_artifacts_for_reset(template_copy)

    out = run_cmd(template_copy, "reset", "--yes")
    assert "Campaign reset completed." in out.stdout
    assert "Archive:" in out.stdout
    assert "Restore hint:" in out.stdout

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


def test_reset_no_archive_skips_archive_creation(template_copy) -> None:
    _seed_runtime_artifacts_for_reset(template_copy)

    out = run_cmd(template_copy, "reset", "--yes", "--no-archive")
    assert "Campaign reset completed." in out.stdout
    assert "Archive: disabled" in out.stdout
    assert not (template_copy / "state" / "reset_archives").exists()


def test_validate_warnings_exit_zero_and_strict_nonzero(template_copy) -> None:
    cfg_path = template_copy / "bo_config.json"
    cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
    cfg["max_pending_age_seconds"] = 60
    cfg_path.write_text(json.dumps(cfg, indent=2), encoding="utf-8")

    suggestion = parse_suggestion(run_cmd(template_copy, "suggest").stdout)
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

    # Keep pending state intact for this assertion context.
    state_after = json.loads(state_path.read_text(encoding="utf-8"))
    assert state_after["pending"][0]["trial_id"] == suggestion["trial_id"]


def test_validate_hard_failure_for_corrupt_state_file(template_copy) -> None:
    state_path = template_copy / "state" / "bo_state.json"
    state_path.write_text("{not valid json", encoding="utf-8")

    out = run_cmd(template_copy, "validate", expect_ok=False)
    assert out.returncode != 0
    assert "ERROR: state load failure:" in out.stdout


def test_validate_hard_failure_for_malformed_bo_config(template_copy) -> None:
    cfg_path = template_copy / "bo_config.json"
    cfg_path.write_text("{not valid json", encoding="utf-8")

    out = run_cmd(template_copy, "validate", expect_ok=False)
    assert out.returncode != 0
    assert "ERROR: config load failure:" in out.stdout


def test_validate_hard_failure_for_malformed_parameter_space(template_copy) -> None:
    space_path = template_copy / "parameter_space.json"
    space_path.write_text("{}", encoding="utf-8")

    out = run_cmd(template_copy, "validate", expect_ok=False)
    assert out.returncode != 0
    assert "ERROR: parameter_space validation failure:" in out.stdout
    assert "field=$.parameters" in out.stdout


def test_validate_accepts_conditional_parameter_space(template_copy) -> None:
    space_path = template_copy / "parameter_space.json"
    space_path.write_text(
        json.dumps(
            {
                "parameters": [
                    {"name": "optimizer", "type": "categorical", "choices": ["adam", "sgd"]},
                    {
                        "name": "momentum",
                        "type": "float",
                        "bounds": [0.0, 0.99],
                        "when": {"optimizer": "sgd"},
                    },
                ]
            },
            indent=2,
        ),
        encoding="utf-8",
    )

    out = run_cmd(template_copy, "validate")
    assert "Validation passed." in out.stdout


def test_validate_accepts_well_formed_constraints_contract(template_copy) -> None:
    constraints_path = template_copy / "constraints.json"
    constraints_path.write_text(
        json.dumps(
            {
                "bound_tightening": [{"param": "x1", "min": 0.2, "max": 0.8}],
                "linear_inequalities": [
                    {
                        "terms": [
                            {"param": "x1", "coefficient": 1.0},
                            {"param": "x2", "coefficient": 1.0},
                        ],
                        "operator": "<=",
                        "rhs": 1.5,
                    }
                ],
            },
            indent=2,
        ),
        encoding="utf-8",
    )

    out = run_cmd(template_copy, "validate")
    assert "Validation passed." in out.stdout


def test_validate_rejects_conditional_dependency_cycle(template_copy) -> None:
    space_path = template_copy / "parameter_space.json"
    space_path.write_text(
        json.dumps(
            {
                "parameters": [
                    {"name": "a", "type": "int", "bounds": [0, 1], "when": {"b": 1}},
                    {"name": "b", "type": "int", "bounds": [0, 1], "when": {"a": 1}},
                ]
            },
            indent=2,
        ),
        encoding="utf-8",
    )

    out = run_cmd(template_copy, "validate", expect_ok=False)
    assert out.returncode != 0
    assert "ERROR: parameter_space validation failure:" in out.stdout
    assert "conditional dependency cycle: a -> b -> a" in out.stdout


def test_validate_rejects_invalid_constraints_contract(template_copy) -> None:
    constraints_path = template_copy / "constraints.json"
    constraints_path.write_text(
        json.dumps(
            {
                "linear_inequalities": [
                    {
                        "terms": [{"param": "x1", "coefficient": 1.0}],
                        "operator": "<=",
                        "rhs": 0.4,
                    }
                ],
                "forbidden_combinations": [{"when": {"x1": []}}],
            },
            indent=2,
        ),
        encoding="utf-8",
    )

    out = run_cmd(template_copy, "validate", expect_ok=False)
    assert out.returncode != 0
    assert "ERROR: constraints validation failure:" in out.stdout
    assert "constraints.forbidden_combinations[0].when.x1 must not be empty" in out.stdout


def test_validate_hard_failure_for_duplicate_observation_trial_ids(template_copy) -> None:
    suggestion = parse_suggestion(run_cmd(template_copy, "suggest").stdout)
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


def test_validate_hard_failure_for_inconsistent_best_ranking(template_copy) -> None:
    first = parse_suggestion(run_cmd(template_copy, "suggest").stdout)
    first_payload = {
        "trial_id": first["trial_id"],
        "params": first["params"],
        "objectives": {"loss": 0.1},
        "status": "ok",
    }
    first_path = template_copy / "examples" / "_best_rank_first.json"
    first_path.write_text(json.dumps(first_payload, indent=2), encoding="utf-8")
    run_cmd(template_copy, "ingest", "--results-file", str(first_path))

    second = parse_suggestion(run_cmd(template_copy, "suggest").stdout)
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
        "state.best.trial_id must reference the optimal ok trial for objective direction"
        in out.stdout
    )


def test_validate_hard_failure_for_corrupt_event_log_jsonl(template_copy) -> None:
    event_log_path = template_copy / "state" / "event_log.jsonl"
    event_log_path.parent.mkdir(parents=True, exist_ok=True)
    event_log_path.write_text("{invalid json\n", encoding="utf-8")

    out = run_cmd(template_copy, "validate", expect_ok=False)
    assert out.returncode != 0
    assert "event_log_file line 1 invalid JSON:" in out.stdout


def test_validate_hard_failure_for_missing_trial_manifest(template_copy) -> None:
    trial_dir_path = template_copy / "state" / "trials" / "trial_123"
    trial_dir_path.mkdir(parents=True, exist_ok=True)

    out = run_cmd(template_copy, "validate", expect_ok=False)
    assert out.returncode != 0
    assert "missing manifest for trial directory:" in out.stdout


def test_validate_hard_failure_for_manifest_missing_traceability_field(template_copy) -> None:
    suggestion = parse_suggestion(run_cmd(template_copy, "suggest").stdout)
    payload = {
        "trial_id": suggestion["trial_id"],
        "params": suggestion["params"],
        "objectives": {"loss": 0.21},
        "status": "ok",
    }
    result_path = template_copy / "examples" / "_manifest_traceability.json"
    result_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    run_cmd(template_copy, "ingest", "--results-file", str(result_path))

    manifest_path = (
        template_copy / "state" / "trials" / f"trial_{suggestion['trial_id']}" / "manifest.json"
    )
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest.pop("artifact_path", None)
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    out = run_cmd(template_copy, "validate", expect_ok=False)
    assert out.returncode != 0
    assert "manifest missing required field 'artifact_path'" in out.stdout


def test_doctor_json_reports_backend_and_status(template_copy) -> None:
    out = run_cmd(template_copy, "doctor", "--json")
    payload = json.loads(out.stdout)

    assert payload["backend"]["configured"] in {"rbf_proxy", "gp"}
    assert payload["status"]["observations"] == 0
    assert payload["status"]["pending"] == 0
    assert "paths" in payload["status"]


def test_ingest_atomic_write_injection_preserves_last_good_state(
    template_copy, monkeypatch
) -> None:
    suggestion = parse_suggestion(run_cmd(template_copy, "suggest").stdout)
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


def test_suggest_fail_fast_on_lock_contention_reports_clean_error(template_copy) -> None:
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


def test_suggest_timeout_on_lock_contention_reports_clean_error(template_copy) -> None:
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


def test_read_commands_work_while_mutation_lock_is_held(template_copy) -> None:
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
    template_copy, command: str, extra_args: list[str]
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
