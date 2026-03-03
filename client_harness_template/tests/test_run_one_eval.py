from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
RUN_ONE_EVAL = REPO_ROOT / "client_harness_template" / "run_one_eval.py"


def _run_cmd(*args: str, expect_ok: bool = True) -> subprocess.CompletedProcess[str]:
    out = subprocess.run(
        [sys.executable, str(RUN_ONE_EVAL), *args],
        capture_output=True,
        text=True,
    )
    if expect_ok and out.returncode != 0:
        raise AssertionError(
            f"Command failed: {' '.join(args)}\nSTDOUT:\n{out.stdout}\nSTDERR:\n{out.stderr}"
        )
    return out


def _write_suggestion(path: Path) -> None:
    payload = {
        "trial_id": 1,
        "params": {"x1": 0.2, "x2": 0.7},
        "suggested_at": 1738886400.0,
    }
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def _write_raising_objective(path: Path) -> None:
    path.write_text(
        "def evaluate(params):\n    raise RuntimeError('synthetic failure')\n",
        encoding="utf-8",
    )


def _write_ok_objective(path: Path) -> None:
    path.write_text(
        "def evaluate(params):\n    return 0.123\n",
        encoding="utf-8",
    )


def _write_objective_schema(path: Path, *, name: str, direction: str) -> None:
    payload = {
        "primary_objective": {
            "name": name,
            "direction": direction,
            "tolerance": 0.0,
            "failure_handling": "record_and_continue",
        },
        "secondary_objectives": [],
    }
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def test_failed_payload_default_sentinel_for_minimize(tmp_path: Path) -> None:
    suggestion = tmp_path / "suggestion.json"
    objective = tmp_path / "objective_raise.py"
    result = tmp_path / "result.json"
    _write_suggestion(suggestion)
    _write_raising_objective(objective)

    _run_cmd(str(suggestion), str(result), "--objective-module", str(objective))
    payload = json.loads(result.read_text(encoding="utf-8"))
    assert payload["status"] == "failed"
    assert payload["objectives"]["loss"] == 1.0e12


def test_failed_payload_default_sentinel_for_maximize(tmp_path: Path) -> None:
    suggestion = tmp_path / "suggestion.json"
    objective = tmp_path / "objective_raise.py"
    result = tmp_path / "result.json"
    _write_suggestion(suggestion)
    _write_raising_objective(objective)

    _run_cmd(
        str(suggestion),
        str(result),
        "--objective-module",
        str(objective),
        "--objective-direction",
        "maximize",
    )
    payload = json.loads(result.read_text(encoding="utf-8"))
    assert payload["status"] == "failed"
    assert payload["objectives"]["loss"] == -1.0e12


def test_objective_schema_drives_name_and_direction_defaults(tmp_path: Path) -> None:
    suggestion = tmp_path / "suggestion.json"
    objective = tmp_path / "objective_raise.py"
    schema = tmp_path / "objective_schema.yaml"
    result = tmp_path / "result.json"
    _write_suggestion(suggestion)
    _write_raising_objective(objective)
    _write_objective_schema(schema, name="score", direction="maximize")

    _run_cmd(
        str(suggestion),
        str(result),
        "--objective-module",
        str(objective),
        "--objective-schema",
        str(schema),
    )
    payload = json.loads(result.read_text(encoding="utf-8"))
    assert payload["status"] == "failed"
    assert payload["objectives"]["score"] == -1.0e12


def test_explicit_failure_sentinel_overrides_direction_default(tmp_path: Path) -> None:
    suggestion = tmp_path / "suggestion.json"
    objective = tmp_path / "objective_raise.py"
    result = tmp_path / "result.json"
    _write_suggestion(suggestion)
    _write_raising_objective(objective)

    _run_cmd(
        str(suggestion),
        str(result),
        "--objective-module",
        str(objective),
        "--objective-direction",
        "maximize",
        "--failure-sentinel",
        "-123.0",
    )
    payload = json.loads(result.read_text(encoding="utf-8"))
    assert payload["status"] == "failed"
    assert payload["objectives"]["loss"] == -123.0


def test_objective_schema_name_applies_on_successful_eval(tmp_path: Path) -> None:
    suggestion = tmp_path / "suggestion.json"
    objective = tmp_path / "objective_ok.py"
    schema = tmp_path / "objective_schema.yaml"
    result = tmp_path / "result.json"
    _write_suggestion(suggestion)
    _write_ok_objective(objective)
    _write_objective_schema(schema, name="score", direction="maximize")

    _run_cmd(
        str(suggestion),
        str(result),
        "--objective-module",
        str(objective),
        "--objective-schema",
        str(schema),
    )
    payload = json.loads(result.read_text(encoding="utf-8"))
    assert payload["status"] == "ok"
    assert payload["objectives"] == {"score": 0.123}
