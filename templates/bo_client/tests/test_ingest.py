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


def test_ingest_accepts_legacy_result_schema_key_with_deprecation(template_copy) -> None:
    cfg_path = template_copy / "bo_config.json"
    cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
    paths = cfg.setdefault("paths", {})
    ingest_rel = paths.pop("ingest_schema_file")
    paths["result_schema_file"] = ingest_rel
    cfg_path.write_text(json.dumps(cfg, indent=2), encoding="utf-8")

    suggestion = parse_suggestion(run_cmd(template_copy, "suggest").stdout)
    result = {
        "trial_id": suggestion["trial_id"],
        "params": suggestion["params"],
        "objectives": {"loss": 0.05},
        "status": "ok",
    }
    path = template_copy / "examples" / "_ingest_legacy_schema_key.json"
    path.write_text(json.dumps(result, indent=2), encoding="utf-8")

    out = run_cmd(template_copy, "ingest", "--results-file", str(path))
    assert "Deprecated config path key 'result_schema_file'" in out.stderr
    assert "removed in v0.4.0" in out.stderr


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
    assert "field=$.trial_id" in out.stderr
    assert "required field present" in out.stderr


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
    assert "params mismatch for pending trial_id" in out.stderr
    assert "$.params.x1 differs" in out.stderr


def test_duplicate_ingest_identical_replay_is_noop(template_copy) -> None:
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

    out = run_cmd(template_copy, "ingest", "--results-file", str(path))
    assert "No-op:" in out.stdout

    after = json.loads(run_cmd(template_copy, "status").stdout)
    assert after == before


def test_duplicate_ingest_conflicting_replay_is_rejected_with_diff(template_copy) -> None:
    suggestion = parse_suggestion(run_cmd(template_copy, "suggest").stdout)
    payload = {
        "trial_id": suggestion["trial_id"],
        "params": suggestion["params"],
        "objectives": {"loss": 0.1},
        "status": "ok",
    }
    path = template_copy / "examples" / "_ingest_duplicate_conflict.json"
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    run_cmd(template_copy, "ingest", "--results-file", str(path))
    payload["objectives"]["loss"] = 0.2
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    out = run_cmd(template_copy, "ingest", "--results-file", str(path), expect_ok=False)
    assert out.returncode != 0
    assert "conflicting duplicate ingest" in out.stderr
    assert "$.objectives.loss differs" in out.stderr


def test_ingest_accepts_success_alias_and_normalizes_to_ok(template_copy) -> None:
    suggestion = parse_suggestion(run_cmd(template_copy, "suggest").stdout)
    payload = {
        "trial_id": suggestion["trial_id"],
        "params": suggestion["params"],
        "objectives": {"loss": 0.09},
        "status": "success",
    }
    path = template_copy / "examples" / "_ingest_success_alias.json"
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    run_cmd(template_copy, "ingest", "--results-file", str(path))
    state = json.loads((template_copy / "state" / "bo_state.json").read_text(encoding="utf-8"))
    assert state["observations"][0]["status"] == "ok"


def test_non_ok_allows_null_objective_with_optional_penalty(template_copy) -> None:
    suggestion = parse_suggestion(run_cmd(template_copy, "suggest").stdout)
    payload = {
        "trial_id": suggestion["trial_id"],
        "params": suggestion["params"],
        "objectives": {"loss": None},
        "status": "timeout",
        "penalty_objective": 999.0,
    }
    path = template_copy / "examples" / "_ingest_timeout_null.json"
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    run_cmd(template_copy, "ingest", "--results-file", str(path))
    state = json.loads((template_copy / "state" / "bo_state.json").read_text(encoding="utf-8"))
    obs = state["observations"][0]
    assert obs["status"] == "timeout"
    assert obs["objectives"]["loss"] is None
    assert obs["penalty_objective"] == 999.0
    assert state["best"] is None


def test_non_ok_killed_allows_null_objective_with_optional_penalty(template_copy) -> None:
    suggestion = parse_suggestion(run_cmd(template_copy, "suggest").stdout)
    payload = {
        "trial_id": suggestion["trial_id"],
        "params": suggestion["params"],
        "objectives": {"loss": None},
        "status": "killed",
        "penalty_objective": 777.0,
    }
    path = template_copy / "examples" / "_ingest_killed_null.json"
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    run_cmd(template_copy, "ingest", "--results-file", str(path))
    state = json.loads((template_copy / "state" / "bo_state.json").read_text(encoding="utf-8"))
    obs = state["observations"][0]
    assert obs["status"] == "killed"
    assert obs["objectives"]["loss"] is None
    assert obs["penalty_objective"] == 777.0
    assert state["best"] is None


def test_non_ok_penalty_does_not_affect_best_ranking(template_copy) -> None:
    first = parse_suggestion(run_cmd(template_copy, "suggest").stdout)
    ok_payload = {
        "trial_id": first["trial_id"],
        "params": first["params"],
        "objectives": {"loss": 0.1},
        "status": "ok",
    }
    first_path = template_copy / "examples" / "_ingest_ok_for_best.json"
    first_path.write_text(json.dumps(ok_payload, indent=2), encoding="utf-8")
    run_cmd(template_copy, "ingest", "--results-file", str(first_path))

    second = parse_suggestion(run_cmd(template_copy, "suggest").stdout)
    failed_payload = {
        "trial_id": second["trial_id"],
        "params": second["params"],
        "objectives": {"loss": None},
        "status": "timeout",
        # Intentionally very good value for minimize to ensure it is ignored for ranking.
        "penalty_objective": -1.0e9,
    }
    second_path = template_copy / "examples" / "_ingest_timeout_ignored_for_best.json"
    second_path.write_text(json.dumps(failed_payload, indent=2), encoding="utf-8")
    run_cmd(template_copy, "ingest", "--results-file", str(second_path))

    state = json.loads((template_copy / "state" / "bo_state.json").read_text(encoding="utf-8"))
    assert len(state["observations"]) == 2
    assert state["best"]["trial_id"] == first["trial_id"]
    assert state["best"]["objective_value"] == 0.1


def test_non_ok_sentinel_objective_is_accepted_with_deprecation(template_copy) -> None:
    suggestion = parse_suggestion(run_cmd(template_copy, "suggest").stdout)
    payload = {
        "trial_id": suggestion["trial_id"],
        "params": suggestion["params"],
        "objectives": {"loss": 1e12},
        "status": "failed",
    }
    path = template_copy / "examples" / "_ingest_failed_sentinel.json"
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    out = run_cmd(template_copy, "ingest", "--results-file", str(path))
    assert "Deprecated" in out.stderr
    state = json.loads((template_copy / "state" / "bo_state.json").read_text(encoding="utf-8"))
    obs = state["observations"][0]
    assert obs["objectives"]["loss"] is None
    assert obs["penalty_objective"] == 1e12
