from __future__ import annotations

import csv
import json
from pathlib import Path

from conftest import parse_suggestion, run_cmd


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


def _configure_conditional_space(
    template_copy, *, seed: int, initial_random_trials: int = 1
) -> None:
    (template_copy / "parameter_space.json").write_text(
        json.dumps(_conditional_parameter_space(), indent=2), encoding="utf-8"
    )
    cfg_path = template_copy / "bo_config.json"
    cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
    cfg["seed"] = seed
    cfg["initial_random_trials"] = initial_random_trials
    cfg_path.write_text(json.dumps(cfg, indent=2), encoding="utf-8")


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


def test_ingest_rejects_legacy_result_schema_key(template_copy) -> None:
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

    out = run_cmd(template_copy, "ingest", "--results-file", str(path), expect_ok=False)
    assert "Unsupported config path key 'result_schema_file'" in out.stderr
    assert "use 'ingest_schema_file' instead" in out.stderr


def test_ingest_rejects_result_payload_schema_alias(template_copy) -> None:
    cfg_path = template_copy / "bo_config.json"
    cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
    cfg["paths"]["ingest_schema_file"] = "schemas/result_payload.schema.json"
    cfg_path.write_text(json.dumps(cfg, indent=2), encoding="utf-8")

    suggestion = parse_suggestion(run_cmd(template_copy, "suggest").stdout)
    result = {
        "trial_id": suggestion["trial_id"],
        "params": suggestion["params"],
        "objectives": {"loss": 0.05},
        "status": "ok",
    }
    path = template_copy / "examples" / "_ingest_alias_schema_file.json"
    path.write_text(json.dumps(result, indent=2), encoding="utf-8")

    out = run_cmd(template_copy, "ingest", "--results-file", str(path), expect_ok=False)
    assert "Unsupported ingest schema filename 'result_payload.schema.json'" in out.stderr
    assert "use 'ingest_payload.schema.json' instead" in out.stderr


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


def test_ingest_requires_matching_lease_token_when_enabled(template_copy) -> None:
    cfg_path = template_copy / "bo_config.json"
    cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
    cfg["worker_leases"]["enabled"] = True
    cfg_path.write_text(json.dumps(cfg, indent=2), encoding="utf-8")

    suggestion = parse_suggestion(run_cmd(template_copy, "suggest").stdout)
    lease_token = suggestion["lease_token"]
    payload = {
        "trial_id": suggestion["trial_id"],
        "params": suggestion["params"],
        "objectives": {"loss": 0.1},
        "status": "ok",
    }
    path = template_copy / "examples" / "_ingest_with_lease.json"
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    missing = run_cmd(template_copy, "ingest", "--results-file", str(path), expect_ok=False)
    assert missing.returncode != 0
    assert f"trial_id {suggestion['trial_id']} requires --lease-token for ingest" in missing.stderr

    wrong = run_cmd(
        template_copy,
        "ingest",
        "--results-file",
        str(path),
        "--lease-token",
        "wrong-token",
        expect_ok=False,
    )
    assert wrong.returncode != 0
    assert f"trial_id {suggestion['trial_id']} lease token mismatch for ingest" in wrong.stderr

    run_cmd(
        template_copy,
        "ingest",
        "--results-file",
        str(path),
        "--lease-token",
        lease_token,
    )

    state = json.loads((template_copy / "state" / "bo_state.json").read_text(encoding="utf-8"))
    observation = state["observations"][0]
    assert observation["lease_token"] == lease_token

    manifest_path = (
        template_copy / "state" / "trials" / f"trial_{suggestion['trial_id']}" / "manifest.json"
    )
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["lease_token"] == lease_token


def test_ingest_canonicalizes_inactive_conditional_params_for_state_and_csv(template_copy) -> None:
    _configure_conditional_space(template_copy, seed=0)
    suggestion = parse_suggestion(run_cmd(template_copy, "suggest").stdout)
    assert suggestion["params"]["gate"] == 0
    assert set(suggestion["params"]) == {"gate", "x"}

    payload = {
        "trial_id": suggestion["trial_id"],
        "params": {**suggestion["params"], "momentum": 0.55},
        "objectives": {"loss": 0.12},
        "status": "ok",
    }
    path = template_copy / "examples" / "_ingest_conditional_inactive_extra.json"
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    run_cmd(template_copy, "ingest", "--results-file", str(path))

    state = json.loads((template_copy / "state" / "bo_state.json").read_text(encoding="utf-8"))
    observation = state["observations"][0]
    assert observation["params"] == suggestion["params"]
    artifact_rel = observation["artifact_path"]
    artifact_payload = json.loads((template_copy / artifact_rel).read_text(encoding="utf-8"))
    assert artifact_payload["params"] == suggestion["params"]

    with (template_copy / "state" / "observations.csv").open(
        encoding="utf-8", newline=""
    ) as handle:
        rows = list(csv.DictReader(handle))
    assert rows[0]["param_gate"] == "0"
    assert rows[0]["param_x"] != ""
    assert "param_momentum" not in rows[0]


def test_duplicate_ingest_replay_ignores_inactive_conditional_param_fields(template_copy) -> None:
    _configure_conditional_space(template_copy, seed=0)
    suggestion = parse_suggestion(run_cmd(template_copy, "suggest").stdout)
    payload = {
        "trial_id": suggestion["trial_id"],
        "params": {**suggestion["params"], "momentum": 0.33},
        "objectives": {"loss": 0.1},
        "status": "ok",
    }
    path = template_copy / "examples" / "_ingest_conditional_duplicate.json"
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    run_cmd(template_copy, "ingest", "--results-file", str(path))
    before = json.loads(run_cmd(template_copy, "status").stdout)

    replay = run_cmd(template_copy, "ingest", "--results-file", str(path))
    assert "No-op:" in replay.stdout

    after = json.loads(run_cmd(template_copy, "status").stdout)
    assert after == before


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


def test_non_ok_failure_reason_alias_maps_to_terminal_reason(template_copy) -> None:
    suggestion = parse_suggestion(run_cmd(template_copy, "suggest").stdout)
    payload = {
        "trial_id": suggestion["trial_id"],
        "params": suggestion["params"],
        "objectives": {"loss": None},
        "status": "failed",
        "failure_reason": "worker crashed",
    }
    path = template_copy / "examples" / "_ingest_failed_reason_alias.json"
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    out = run_cmd(template_copy, "ingest", "--results-file", str(path))
    assert "Deprecated ingest field 'failure_reason'" in out.stderr
    state = json.loads((template_copy / "state" / "bo_state.json").read_text(encoding="utf-8"))
    obs = state["observations"][0]
    assert obs["status"] == "failed"
    assert obs["objectives"]["loss"] is None
    assert obs["terminal_reason"] == "worker crashed"
    assert "failure_reason" not in obs


def test_non_ok_missing_reason_gets_status_fallback_terminal_reason(template_copy) -> None:
    suggestion = parse_suggestion(run_cmd(template_copy, "suggest").stdout)
    payload = {
        "trial_id": suggestion["trial_id"],
        "params": suggestion["params"],
        "objectives": {"loss": None},
        "status": "timeout",
    }
    path = template_copy / "examples" / "_ingest_timeout_fallback_reason.json"
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    run_cmd(template_copy, "ingest", "--results-file", str(path))
    state = json.loads((template_copy / "state" / "bo_state.json").read_text(encoding="utf-8"))
    obs = state["observations"][0]
    assert obs["status"] == "timeout"
    assert obs["objectives"]["loss"] is None
    assert obs["terminal_reason"] == "status=timeout"
    assert obs["penalty_objective"] is None
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


def test_non_ok_numeric_primary_objective_is_rejected(template_copy) -> None:
    suggestion = parse_suggestion(run_cmd(template_copy, "suggest").stdout)
    payload = {
        "trial_id": suggestion["trial_id"],
        "params": suggestion["params"],
        "objectives": {"loss": 1e12},
        "status": "failed",
    }
    path = template_copy / "examples" / "_ingest_failed_sentinel.json"
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    out = run_cmd(template_copy, "ingest", "--results-file", str(path), expect_ok=False)
    assert out.returncode != 0
    assert "field=$.objectives.loss" in out.stderr
    assert "null for non-ok status" in out.stderr


def test_ingest_rejects_missing_secondary_objective_for_multi_objective_ok_payload(
    template_copy,
) -> None:
    _write_weighted_sum_objective_schema(template_copy)
    suggestion = parse_suggestion(run_cmd(template_copy, "suggest").stdout)
    payload = {
        "trial_id": suggestion["trial_id"],
        "params": suggestion["params"],
        "objectives": {"loss": 0.1},
        "status": "ok",
    }
    path = template_copy / "examples" / "_ingest_multi_missing_secondary.json"
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    out = run_cmd(template_copy, "ingest", "--results-file", str(path), expect_ok=False)
    assert "$.objectives.throughput" in out.stderr
    assert "required configured objective present" in out.stderr


def test_ingest_rejects_non_null_objectives_for_multi_objective_non_ok_payload(
    template_copy,
) -> None:
    _write_weighted_sum_objective_schema(template_copy)
    suggestion = parse_suggestion(run_cmd(template_copy, "suggest").stdout)
    payload = {
        "trial_id": suggestion["trial_id"],
        "params": suggestion["params"],
        "objectives": {"loss": None, "throughput": 5.0},
        "status": "failed",
        "penalty_objective": 99.0,
    }
    path = template_copy / "examples" / "_ingest_multi_non_ok_non_null.json"
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    out = run_cmd(template_copy, "ingest", "--results-file", str(path), expect_ok=False)
    assert "$.objectives.throughput" in out.stderr
    assert "null for non-ok status on all configured objectives" in out.stderr
