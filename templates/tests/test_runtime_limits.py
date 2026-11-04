"""Finite timing boundaries and portable CLI rejection before campaign mutation."""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location(
    "limits_runtime", ROOT / "templates/_shared/runtime.py"
)
RUNTIME = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(RUNTIME)


@pytest.mark.parametrize(
    "value", [float("nan"), float("inf"), -float("inf"), -1, True, "1", 10**400]
)
@pytest.mark.parametrize("field", ["lock_timeout_seconds", "max_pending_age_seconds"])
def test_invalid_configured_limits(value, field):
    resolve = getattr(RUNTIME, f"resolve_{field}")
    with pytest.raises(ValueError, match=field):
        resolve({field: value})


def test_default_zero_null_and_override_semantics():
    assert RUNTIME.resolve_lock_timeout_seconds({}) == 45.0
    assert RUNTIME.resolve_lock_timeout_seconds({"lock_timeout_seconds": 0}) == 0.0
    assert RUNTIME.resolve_lock_timeout_seconds({"lock_timeout_seconds": 2.5}) == 2.5
    assert RUNTIME.resolve_lock_timeout_seconds({"lock_timeout_seconds": None}, 0) == 0.0
    with pytest.raises(ValueError, match="lock_timeout_seconds"):
        RUNTIME.resolve_lock_timeout_seconds({"lock_timeout_seconds": None})
    assert RUNTIME.resolve_max_pending_age_seconds({}) == 86400.0
    for disabled in (0, None):
        assert (
            RUNTIME.resolve_max_pending_age_seconds({"max_pending_age_seconds": disabled}) is None
        )
    assert RUNTIME.resolve_max_pending_age_seconds({"max_pending_age_seconds": 2.5}) == 2.5


@pytest.mark.parametrize(
    "value", [float("nan"), float("inf"), -float("inf"), -1, True, "1", 10**400]
)
def test_invalid_lock_override(value):
    with pytest.raises(ValueError, match="--lock-timeout-seconds"):
        RUNTIME.resolve_lock_timeout_seconds({}, value)


@pytest.mark.parametrize(
    "value", [float("nan"), float("inf"), -float("inf"), 0, -1, True, "1", 10**400]
)
def test_invalid_stale_override(value):
    with pytest.raises(ValueError, match="--max-age-seconds"):
        RUNTIME.resolve_retire_max_age_seconds({}, value)


def test_stale_override_and_disabled_config():
    assert RUNTIME.resolve_retire_max_age_seconds({}, None) == 86400.0
    assert RUNTIME.resolve_retire_max_age_seconds({"max_pending_age_seconds": None}, 1.5) == 1.5
    for disabled in (0, None):
        with pytest.raises(ValueError, match="retire --stale requires"):
            RUNTIME.resolve_retire_max_age_seconds({"max_pending_age_seconds": disabled})


@pytest.mark.parametrize("value", [float("nan"), float("inf"), -float("inf"), 10**400])
@pytest.mark.parametrize("field", ["timeout_seconds", "poll_interval_seconds"])
def test_direct_lock_rejects_nonfinite_before_open(tmp_path, value, field):
    target = tmp_path / "missing" / "lock"
    kwargs = {"timeout_seconds": 1.0, field: value}
    with pytest.raises(ValueError, match=field):
        RUNTIME.ExclusiveFileLock(target, **kwargs)
    assert not target.parent.exists()


def test_direct_lock_preserves_finite_clamping(tmp_path):
    lock = RUNTIME.ExclusiveFileLock(
        tmp_path / "lock", timeout_seconds=-2, poll_interval_seconds=-1
    )
    assert lock.timeout_seconds == 0.0
    assert lock.poll_interval_seconds == 0.01


@pytest.fixture(params=["bo_client", "bo_client_demo", "bo_client_full"])
def campaign(tmp_path, request):
    destination = tmp_path / request.param
    subprocess.run(
        [
            sys.executable,
            str(ROOT / "templates/_shared/vendor_copy.py"),
            str(ROOT / "templates" / request.param),
            str(destination),
        ],
        capture_output=True,
        text=True,
        check=True,
        timeout=15,
    )
    return destination


def command(campaign, *args):
    return subprocess.run(
        [sys.executable, "-B", str(campaign / "run_bo.py"), *args, "--project-root", str(campaign)],
        cwd=campaign.parent,
        capture_output=True,
        text=True,
        timeout=10,
    )


def state_files(campaign):
    return {
        p.relative_to(campaign).as_posix(): p.read_bytes()
        for p in (campaign / "state").rglob("*")
        if p.is_file()
    }


def set_config(campaign, field, value):
    path = campaign / "bo_config.json"
    config = json.loads(path.read_text())
    config[field] = value
    path.write_text(json.dumps(config))


@pytest.mark.parametrize("value", [float("nan"), float("inf"), -float("inf"), True, 10**400])
@pytest.mark.parametrize("field", ["lock_timeout_seconds", "max_pending_age_seconds"])
def test_invalid_config_validate_and_suggest_do_not_mutate(campaign, field, value):
    set_config(campaign, field, value)
    before = state_files(campaign)
    for action in ("validate", "suggest"):
        result = command(campaign, action)
        assert result.returncode != 0, result.stdout
        assert field in result.stdout + result.stderr
        assert "Traceback" not in result.stderr
        assert state_files(campaign) == before


def test_json_exponent_overflow_is_rejected(campaign):
    path = campaign / "bo_config.json"
    cfg = json.loads(path.read_text())
    cfg["lock_timeout_seconds"] = "overflow-placeholder"
    path.write_text(json.dumps(cfg).replace('"overflow-placeholder"', "1e309"))
    result = command(campaign, "validate")
    assert result.returncode != 0
    assert "lock_timeout_seconds" in result.stdout + result.stderr


@pytest.mark.parametrize("value", ["nan", "inf", "-inf", "-1", "1e309"])
def test_invalid_lock_cli_does_not_allocate(campaign, value):
    before = state_files(campaign)
    result = command(campaign, "suggest", f"--lock-timeout-seconds={value}")
    assert result.returncode != 0
    assert "--lock-timeout-seconds" in result.stderr
    assert state_files(campaign) == before


@pytest.mark.parametrize("value", ["nan", "inf", "-inf", "0", "-1", "1e309"])
def test_invalid_retire_cli_preserves_pending_and_events(campaign, value):
    result = command(campaign, "suggest", "--json-only")
    assert result.returncode == 0, result.stderr
    before = state_files(campaign)
    result = command(campaign, "retire", "--stale", f"--max-age-seconds={value}")
    assert result.returncode != 0
    assert "--max-age-seconds" in result.stderr
    assert state_files(campaign) == before


@pytest.mark.parametrize("disabled", [0, None])
def test_disabled_staleness_does_not_retire_and_requires_override(campaign, disabled):
    set_config(campaign, "max_pending_age_seconds", disabled)
    assert command(campaign, "suggest", "--json-only").returncode == 0
    state_path = campaign / "state/bo_state.json"
    state = json.loads(state_path.read_text())
    state["pending"][0]["suggested_at"] = 1
    state_path.write_text(json.dumps(state))
    assert command(campaign, "suggest", "--json-only").returncode == 0
    assert len(json.loads(state_path.read_text())["pending"]) == 2
    before = state_files(campaign)
    result = command(campaign, "retire", "--stale")
    assert result.returncode != 0
    assert "retire --stale requires" in result.stderr
    assert state_files(campaign) == before
    result = command(campaign, "retire", "--stale", "--max-age-seconds=60")
    assert result.returncode == 0, result.stderr
    after = json.loads(state_path.read_text())
    assert len(after["pending"]) == 1
    assert len(after["observations"]) == 1
