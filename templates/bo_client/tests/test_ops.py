from __future__ import annotations

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
    assert "Looptimum Report" in report_md.read_text(encoding="utf-8")


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


def test_doctor_json_reports_backend_and_status(template_copy) -> None:
    out = run_cmd(template_copy, "doctor", "--json")
    payload = json.loads(out.stdout)

    assert payload["backend"]["configured"] in {"rbf_proxy", "gp"}
    assert payload["status"]["observations"] == 0
    assert payload["status"]["pending"] == 0
    assert "paths" in payload["status"]


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
