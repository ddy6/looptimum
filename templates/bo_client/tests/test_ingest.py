from __future__ import annotations

import json

from conftest import parse_suggestion, run_cmd


def test_ingest_accepts_valid_payload(template_copy) -> None:
    suggestion = parse_suggestion(run_cmd(template_copy, "suggest").stdout)
    result = {
        "trial_id": suggestion["trial_id"],
        "params": suggestion["params"],
        "objectives": {"loss": 0.05},
        "status": "ok",
    }
    path = template_copy / "examples" / "_ingest_valid.json"
    path.write_text(json.dumps(result, indent=2), encoding="utf-8")

    run_cmd(template_copy, "ingest", "--results-file", str(path))
    status = json.loads(run_cmd(template_copy, "status").stdout)
    assert status["observations"] == 1
    assert status["pending"] == 0


def test_ingest_rejects_schema_violation(template_copy) -> None:
    suggestion = parse_suggestion(run_cmd(template_copy, "suggest").stdout)
    bad = {
        "params": suggestion["params"],
        "objectives": {"loss": 0.4},
        "status": "ok",
    }
    path = template_copy / "examples" / "_ingest_missing_trial_id.json"
    path.write_text(json.dumps(bad, indent=2), encoding="utf-8")

    out = run_cmd(template_copy, "ingest", "--results-file", str(path), expect_ok=False)
    assert out.returncode != 0
    assert "$.trial_id is required" in out.stderr


def test_ingest_rejects_param_mismatch(template_copy) -> None:
    suggestion = parse_suggestion(run_cmd(template_copy, "suggest").stdout)
    bad = {
        "trial_id": suggestion["trial_id"],
        "params": {"x1": 0.0, "x2": 0.0},
        "objectives": {"loss": 0.4},
        "status": "ok",
    }
    path = template_copy / "examples" / "_ingest_param_mismatch.json"
    path.write_text(json.dumps(bad, indent=2), encoding="utf-8")

    out = run_cmd(template_copy, "ingest", "--results-file", str(path), expect_ok=False)
    assert out.returncode != 0
    assert "params do not match" in out.stderr


def test_duplicate_ingest_is_rejected_without_state_corruption(template_copy) -> None:
    suggestion = parse_suggestion(run_cmd(template_copy, "suggest").stdout)
    payload = {
        "trial_id": suggestion["trial_id"],
        "params": suggestion["params"],
        "objectives": {"loss": 0.1},
        "status": "ok",
    }
    path = template_copy / "examples" / "_ingest_duplicate.json"
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    run_cmd(template_copy, "ingest", "--results-file", str(path))
    before = json.loads(run_cmd(template_copy, "status").stdout)

    out = run_cmd(template_copy, "ingest", "--results-file", str(path), expect_ok=False)
    assert out.returncode != 0
    assert "is not pending" in out.stderr

    after = json.loads(run_cmd(template_copy, "status").stdout)
    assert after == before
