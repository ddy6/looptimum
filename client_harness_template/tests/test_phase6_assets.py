from __future__ import annotations

import csv
import json
import tomllib
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
GOLDEN_LOG = REPO_ROOT / "docs" / "examples" / "decision_trace" / "golden_acquisition_log.jsonl"
REGEN_SCRIPT = REPO_ROOT / "docs" / "examples" / "decision_trace" / "regenerate_golden_log.sh"
CI_WORKFLOW = REPO_ROOT / ".github" / "workflows" / "ci.yml"
PYPROJECT = REPO_ROOT / "pyproject.toml"
TYPE_SAFETY_DOC = REPO_ROOT / "docs" / "type-safety.md"
MULTI_OBJECTIVE_EXAMPLE = REPO_ROOT / "docs" / "examples" / "multi_objective"
BATCH_ASYNC_EXAMPLE = REPO_ROOT / "docs" / "examples" / "batch_async"
WARM_START_EXAMPLE = REPO_ROOT / "docs" / "examples" / "warm_start"
STARTERKIT_EXAMPLE = REPO_ROOT / "docs" / "examples" / "starterkit"
SERVICE_PREVIEW_EXAMPLE = REPO_ROOT / "docs" / "examples" / "service_api_preview"
DASHBOARD_PREVIEW_EXAMPLE = REPO_ROOT / "docs" / "examples" / "dashboard_preview"
AUTH_PREVIEW_EXAMPLE = REPO_ROOT / "docs" / "examples" / "auth_preview"


def test_golden_acquisition_log_has_expected_shape_and_timestamps() -> None:
    assert GOLDEN_LOG.exists(), f"missing golden log: {GOLDEN_LOG}"
    lines = [
        json.loads(line)
        for line in GOLDEN_LOG.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    assert len(lines) == 8

    strategies: list[str] = []
    for idx, row in enumerate(lines, start=1):
        assert row["trial_id"] == idx
        assert row["timestamp"] == 1_700_000_000.0 + float(idx)
        decision = row["decision"]
        assert isinstance(decision, dict)
        assert "constraint_status" in decision
        status = decision["constraint_status"]
        assert status["enabled"] is False
        assert status["warning"] is None
        assert status["reject_counts"] == {}
        strategies.append(str(decision["strategy"]))
        if idx <= 6:
            assert decision["surrogate_backend"] is None
            assert status["phase"] == "initial-random"
        else:
            assert decision["surrogate_backend"] == "rbf_proxy"
            assert status["phase"] == "candidate-pool"

    assert strategies[:6] == ["initial_random"] * 6
    assert all(strategy == "surrogate_acquisition" for strategy in strategies[6:])


def test_regeneration_script_enforces_normalized_timestamp_export() -> None:
    assert REGEN_SCRIPT.exists(), f"missing regeneration script: {REGEN_SCRIPT}"
    script_text = REGEN_SCRIPT.read_text(encoding="utf-8")
    assert "--normalize-acquisition-timestamps" in script_text
    assert "--steps 8" in script_text


def test_ci_workflow_contains_blocking_mypy_job() -> None:
    assert CI_WORKFLOW.exists(), f"missing CI workflow: {CI_WORKFLOW}"
    text = CI_WORKFLOW.read_text(encoding="utf-8")
    assert "typecheck:" in text
    assert "Type Check (mypy, py3.12)" in text
    assert "python -m mypy" in text
    assert "python -m pytest -q templates client_harness_template/tests service/tests" in text
    assert "service/*.py" in text


def test_mypy_scope_and_type_safety_doc_are_present() -> None:
    assert PYPROJECT.exists(), f"missing pyproject: {PYPROJECT}"
    payload = tomllib.loads(PYPROJECT.read_text(encoding="utf-8"))
    tool_cfg = payload.get("tool", {})
    mypy_cfg = tool_cfg.get("mypy", {})
    files = mypy_cfg.get("files")
    assert isinstance(files, list)
    assert "service/*.py" in files
    assert "templates/_shared/*.py" in files
    assert "templates/bo_client/run_bo.py" in files
    assert "client_harness_template/run_one_eval.py" in files
    assert "client_harness_template/starterkit_*.py" in files
    assert mypy_cfg.get("disallow_untyped_defs") is True
    assert mypy_cfg.get("disallow_any_generics") is True

    assert TYPE_SAFETY_DOC.exists(), f"missing type-safety doc: {TYPE_SAFETY_DOC}"
    doc_text = TYPE_SAFETY_DOC.read_text(encoding="utf-8")
    assert "Type-checking tool: `mypy`." in doc_text
    assert "Initial blocking CI gate scope" in doc_text
    assert "`service/*.py`" in doc_text
    assert "`client_harness_template/starterkit_*.py`" in doc_text


def test_multi_objective_example_pack_has_expected_artifacts() -> None:
    assert MULTI_OBJECTIVE_EXAMPLE.exists(), (
        f"missing multi-objective example pack: {MULTI_OBJECTIVE_EXAMPLE}"
    )

    readme_path = MULTI_OBJECTIVE_EXAMPLE / "README.md"
    weighted_schema = MULTI_OBJECTIVE_EXAMPLE / "objective_schema.json"
    lexicographic_schema = MULTI_OBJECTIVE_EXAMPLE / "objective_schema_lexicographic.json"
    status_path = MULTI_OBJECTIVE_EXAMPLE / "status_after_ingest.json"
    report_path = MULTI_OBJECTIVE_EXAMPLE / "state" / "report.json"
    manifest_path = MULTI_OBJECTIVE_EXAMPLE / "state" / "trials" / "trial_1" / "manifest.json"

    for path in (
        readme_path,
        weighted_schema,
        lexicographic_schema,
        status_path,
        report_path,
        manifest_path,
    ):
        assert path.exists(), f"missing multi-objective example artifact: {path}"

    report_payload = json.loads(report_path.read_text(encoding="utf-8"))
    assert report_payload["objective_config"]["objective_names"] == ["loss", "throughput"]
    assert report_payload["pareto_front"]["trial_ids"] == [1, 2]
    assert report_payload["best"]["objective_vector"] == {"loss": 0.3, "throughput": 2.0}

    manifest_payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest_payload["scalarization_policy"] == "weighted_sum"
    assert manifest_payload["objective_vector"] == {"loss": 0.3, "throughput": 2.0}


def test_batch_async_example_pack_has_expected_artifacts() -> None:
    assert BATCH_ASYNC_EXAMPLE.exists(), f"missing batch/async example pack: {BATCH_ASYNC_EXAMPLE}"

    readme_path = BATCH_ASYNC_EXAMPLE / "README.md"
    config_path = BATCH_ASYNC_EXAMPLE / "bo_config.json"
    bundle_path = BATCH_ASYNC_EXAMPLE / "suggestion_bundle.json"
    jsonl_path = BATCH_ASYNC_EXAMPLE / "suggestions.jsonl"
    status_suggest_path = BATCH_ASYNC_EXAMPLE / "status_after_batch_suggest.json"
    status_ingest_path = BATCH_ASYNC_EXAMPLE / "status_after_ingest.json"
    report_path = BATCH_ASYNC_EXAMPLE / "state" / "report.json"
    manifest_path = BATCH_ASYNC_EXAMPLE / "state" / "trials" / "trial_1" / "manifest.json"

    for path in (
        readme_path,
        config_path,
        bundle_path,
        jsonl_path,
        status_suggest_path,
        status_ingest_path,
        report_path,
        manifest_path,
    ):
        assert path.exists(), f"missing batch/async example artifact: {path}"

    config_payload = json.loads(config_path.read_text(encoding="utf-8"))
    assert config_payload["batch_size"] == 2
    assert config_payload["max_pending_trials"] == 3
    assert config_payload["worker_leases"] == {"enabled": True}

    bundle_payload = json.loads(bundle_path.read_text(encoding="utf-8"))
    assert bundle_payload["count"] == 2
    assert [item["trial_id"] for item in bundle_payload["suggestions"]] == [1, 2]
    assert all(item["lease_token"] for item in bundle_payload["suggestions"])

    jsonl_payloads = [
        json.loads(line)
        for line in jsonl_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    assert [item["trial_id"] for item in jsonl_payloads] == [1, 2]
    assert [item["lease_token"] for item in jsonl_payloads] == [
        item["lease_token"] for item in bundle_payload["suggestions"]
    ]

    suggest_status = json.loads(status_suggest_path.read_text(encoding="utf-8"))
    assert suggest_status["pending"] == 2
    assert suggest_status["leased_pending"] == 2
    assert suggest_status["worker_leases_enabled"] is True

    ingest_status = json.loads(status_ingest_path.read_text(encoding="utf-8"))
    assert ingest_status["pending"] == 0
    assert ingest_status["leased_pending"] == 0
    assert ingest_status["best"]["trial_id"] == 2

    report_payload = json.loads(report_path.read_text(encoding="utf-8"))
    assert report_payload["counts"]["observations"] == 2
    assert report_payload["top_trials"][0]["trial_id"] == 2

    manifest_payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest_payload["lease_token"] == bundle_payload["suggestions"][0]["lease_token"]
    assert manifest_payload["heartbeat_count"] == 1
    assert manifest_payload["heartbeat_meta"] == {"worker": "worker-1", "queue": "batch"}


def test_warm_start_example_pack_has_expected_artifacts() -> None:
    assert WARM_START_EXAMPLE.exists(), f"missing warm-start example pack: {WARM_START_EXAMPLE}"

    readme_path = WARM_START_EXAMPLE / "README.md"
    config_path = WARM_START_EXAMPLE / "bo_config.json"
    search_space_path = WARM_START_EXAMPLE / "parameter_space.json"
    seed_path = WARM_START_EXAMPLE / "seed_import.jsonl"
    status_path = WARM_START_EXAMPLE / "status_after_import.json"
    exported_jsonl_path = WARM_START_EXAMPLE / "exported_observations.jsonl"
    exported_csv_path = WARM_START_EXAMPLE / "exported_observations.csv"
    state_path = WARM_START_EXAMPLE / "state" / "bo_state.json"
    event_log_path = WARM_START_EXAMPLE / "state" / "event_log.jsonl"
    report_path = WARM_START_EXAMPLE / "state" / "report.json"
    manifest_one_path = WARM_START_EXAMPLE / "state" / "trials" / "trial_1" / "manifest.json"
    manifest_two_path = WARM_START_EXAMPLE / "state" / "trials" / "trial_2" / "manifest.json"

    for path in (
        readme_path,
        config_path,
        search_space_path,
        seed_path,
        status_path,
        exported_jsonl_path,
        exported_csv_path,
        state_path,
        event_log_path,
        report_path,
        manifest_one_path,
        manifest_two_path,
    ):
        assert path.exists(), f"missing warm-start example artifact: {path}"

    import_reports = sorted((WARM_START_EXAMPLE / "state" / "import_reports").glob("*.json"))
    assert len(import_reports) == 1

    status_payload = json.loads(status_path.read_text(encoding="utf-8"))
    assert status_payload["observations"] == 2
    assert status_payload["pending"] == 0
    assert status_payload["next_trial_id"] == 3
    assert status_payload["best"]["trial_id"] == 2

    state_payload = json.loads(state_path.read_text(encoding="utf-8"))
    assert [row["trial_id"] for row in state_payload["observations"]] == [1, 2]
    assert state_payload["observations"][0]["source_trial_id"] == "legacy-11"
    assert state_payload["observations"][1]["source_trial_id"] == "legacy-12"

    report_payload = json.loads(report_path.read_text(encoding="utf-8"))
    assert report_payload["counts"]["observations"] == 2
    assert report_payload["best"]["trial_id"] == 2

    manifest_one = json.loads(manifest_one_path.read_text(encoding="utf-8"))
    manifest_two = json.loads(manifest_two_path.read_text(encoding="utf-8"))
    assert manifest_one["source_trial_id"] == "legacy-11"
    assert manifest_two["source_trial_id"] == "legacy-12"

    import_report_payload = json.loads(import_reports[0].read_text(encoding="utf-8"))
    assert import_report_payload["mode"] == "permissive"
    assert import_report_payload["accepted_count"] == 2
    assert import_report_payload["rejected_count"] == 1
    assert import_report_payload["accepted_trial_ids"] == [1, 2]
    assert import_report_payload["rejected_rows"][0]["row_number"] == 3
    assert import_report_payload["rejected_rows"][0]["source_trial_id"] == "legacy-13"

    exported_rows = [
        json.loads(line)
        for line in exported_jsonl_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    assert [row["trial_id"] for row in exported_rows] == [1, 2]
    assert [row["source_trial_id"] for row in exported_rows] == ["legacy-11", "legacy-12"]

    with exported_csv_path.open(encoding="utf-8", newline="") as handle:
        csv_rows = {int(row["trial_id"]): row for row in csv.DictReader(handle)}
    assert csv_rows[1]["source_trial_id"] == "legacy-11"
    assert csv_rows[1]["param_momentum"] == ""
    assert csv_rows[2]["source_trial_id"] == "legacy-12"
    assert csv_rows[2]["param_momentum"] == "0.4"

    event_rows = [
        json.loads(line)
        for line in event_log_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    event_names = [row["event"] for row in event_rows]
    assert "observations_imported" in event_names
    assert "observations_exported" in event_names


def test_starterkit_example_pack_has_expected_artifacts() -> None:
    assert STARTERKIT_EXAMPLE.exists(), f"missing starter-kit example pack: {STARTERKIT_EXAMPLE}"

    readme_path = STARTERKIT_EXAMPLE / "README.md"
    config_path = STARTERKIT_EXAMPLE / "starterkit_config.webhook.json"
    webhook_payload_path = STARTERKIT_EXAMPLE / "webhook_payload.json"
    suggestions_path = STARTERKIT_EXAMPLE / "starterkit_suggestions.jsonl"
    worker_plan_path = STARTERKIT_EXAMPLE / "queue_worker_plan.json"
    airflow_path = STARTERKIT_EXAMPLE / "airflow_dag.py"
    slurm_path = STARTERKIT_EXAMPLE / "slurm_worker_array.sh"
    mlflow_path = STARTERKIT_EXAMPLE / "mlflow_payload.json"
    wandb_path = STARTERKIT_EXAMPLE / "wandb_payload.json"

    for path in (
        readme_path,
        config_path,
        webhook_payload_path,
        suggestions_path,
        worker_plan_path,
        airflow_path,
        slurm_path,
        mlflow_path,
        wandb_path,
    ):
        assert path.exists(), f"missing starter-kit example artifact: {path}"

    config_payload = json.loads(config_path.read_text(encoding="utf-8"))
    assert config_payload["runtime"]["event_log_file"] == "/campaign/state/event_log.jsonl"
    assert config_payload["webhook"]["enabled"] is True
    assert config_payload["webhook"]["topics"] == [
        "suggested",
        "ingested",
        "failed",
        "reset",
        "restore",
    ]

    webhook_payload = json.loads(webhook_payload_path.read_text(encoding="utf-8"))
    assert webhook_payload["topic"] == "ingested"
    assert webhook_payload["trial_id"] == 2
    assert webhook_payload["payload"]["event"] == "ingest_applied"

    suggestions = [
        json.loads(line)
        for line in suggestions_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    assert [item["trial_id"] for item in suggestions] == [1, 2]
    assert all(item["lease_token"] for item in suggestions)

    worker_plan = json.loads(worker_plan_path.read_text(encoding="utf-8"))
    assert worker_plan["trial_id"] == 2
    assert worker_plan["lease_token"] == suggestions[1]["lease_token"]
    assert "--lease-token" in worker_plan["commands"]["ingest"]

    airflow_text = airflow_path.read_text(encoding="utf-8")
    assert "max_active_runs=1" in airflow_text
    assert "controller_suggest" in airflow_text
    assert "starterkit_queue_worker.py" in airflow_text

    slurm_text = slurm_path.read_text(encoding="utf-8")
    assert "SLURM_ARRAY_TASK_ID" in slurm_text
    assert "starterkit_queue_worker.py" in slurm_text

    mlflow_payload = json.loads(mlflow_path.read_text(encoding="utf-8"))
    assert mlflow_payload["metrics"]["looptimum.best_objective"] == 0.082
    assert mlflow_payload["tags"]["looptimum.best_trial_id"] == "2"
    assert mlflow_payload["snapshot"]["top_trials"][0]["trial_id"] == 2

    wandb_payload = json.loads(wandb_path.read_text(encoding="utf-8"))
    assert wandb_payload["config"]["objective_names"] == ["loss"]
    assert wandb_payload["summary"]["looptimum/top_trial_count"] == 2
    assert wandb_payload["history"]["looptimum/observations"] == 2.0


def test_service_preview_example_pack_has_expected_artifacts() -> None:
    assert SERVICE_PREVIEW_EXAMPLE.exists(), (
        f"missing service preview example pack: {SERVICE_PREVIEW_EXAMPLE}"
    )

    readme_path = SERVICE_PREVIEW_EXAMPLE / "README.md"
    health_path = SERVICE_PREVIEW_EXAMPLE / "health_response.json"
    create_request_path = SERVICE_PREVIEW_EXAMPLE / "campaign_create_request.json"
    create_response_path = SERVICE_PREVIEW_EXAMPLE / "campaign_create_response.json"
    list_response_path = SERVICE_PREVIEW_EXAMPLE / "campaign_list_response.json"
    detail_path = SERVICE_PREVIEW_EXAMPLE / "campaign_detail_response.json"
    suggest_request_path = SERVICE_PREVIEW_EXAMPLE / "suggest_request.json"
    suggest_response_path = SERVICE_PREVIEW_EXAMPLE / "suggest_response.json"
    suggest_jsonl_path = SERVICE_PREVIEW_EXAMPLE / "suggest_response.jsonl"
    ingest_request_path = SERVICE_PREVIEW_EXAMPLE / "ingest_request.json"
    ingest_response_path = SERVICE_PREVIEW_EXAMPLE / "ingest_response.json"
    status_path = SERVICE_PREVIEW_EXAMPLE / "status_after_ingest.json"
    report_path = SERVICE_PREVIEW_EXAMPLE / "report_response.json"

    for path in (
        readme_path,
        health_path,
        create_request_path,
        create_response_path,
        list_response_path,
        detail_path,
        suggest_request_path,
        suggest_response_path,
        suggest_jsonl_path,
        ingest_request_path,
        ingest_response_path,
        status_path,
        report_path,
    ):
        assert path.exists(), f"missing service preview example artifact: {path}"

    health_payload = json.loads(health_path.read_text(encoding="utf-8"))
    assert health_payload["ok"] is True
    assert health_payload["preview"] == "service_api_preview"

    create_payload = json.loads(create_response_path.read_text(encoding="utf-8"))
    assert create_payload["campaign_id"] == "bo_client_demo"
    assert create_payload["label"] == "Demo Preview Campaign"

    list_payload = json.loads(list_response_path.read_text(encoding="utf-8"))
    assert list_payload["campaigns"][0]["campaign_id"] == "bo_client_demo"

    detail_payload = json.loads(detail_path.read_text(encoding="utf-8"))
    assert detail_payload["campaign"]["campaign_id"] == "bo_client_demo"
    assert detail_payload["artifacts"]["report_json_exists"] is True

    suggest_payload = json.loads(suggest_response_path.read_text(encoding="utf-8"))
    assert suggest_payload["count"] == 2
    assert [item["trial_id"] for item in suggest_payload["suggestions"]] == [1, 2]

    jsonl_payloads = [
        json.loads(line)
        for line in suggest_jsonl_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    assert [item["trial_id"] for item in jsonl_payloads] == [1, 2]

    ingest_payload = json.loads(ingest_response_path.read_text(encoding="utf-8"))
    assert ingest_payload == {
        "message": "Ingested trial_id=1. Observations=1",
        "noop": False,
    }

    status_payload = json.loads(status_path.read_text(encoding="utf-8"))
    assert status_payload["observations"] == 1
    assert status_payload["pending"] == 1
    assert status_payload["best"]["trial_id"] == 1

    report_payload = json.loads(report_path.read_text(encoding="utf-8"))
    assert report_payload["counts"]["observations"] == 1
    assert report_payload["top_trials"][0]["trial_id"] == 1


def test_dashboard_preview_example_pack_has_expected_artifacts() -> None:
    assert DASHBOARD_PREVIEW_EXAMPLE.exists(), (
        f"missing dashboard preview example pack: {DASHBOARD_PREVIEW_EXAMPLE}"
    )

    readme_path = DASHBOARD_PREVIEW_EXAMPLE / "README.md"
    root_html_path = DASHBOARD_PREVIEW_EXAMPLE / "dashboard_root.html"
    campaign_html_path = DASHBOARD_PREVIEW_EXAMPLE / "dashboard_campaign.html"
    campaigns_path = DASHBOARD_PREVIEW_EXAMPLE / "campaign_list_response.json"
    detail_path = DASHBOARD_PREVIEW_EXAMPLE / "campaign_detail_response.json"
    trials_path = DASHBOARD_PREVIEW_EXAMPLE / "trials_response.json"
    trial_detail_path = DASHBOARD_PREVIEW_EXAMPLE / "trial_detail_response.json"
    timeseries_path = DASHBOARD_PREVIEW_EXAMPLE / "timeseries_best_response.json"
    alerts_path = DASHBOARD_PREVIEW_EXAMPLE / "alerts_response.json"
    decision_trace_path = DASHBOARD_PREVIEW_EXAMPLE / "decision_trace_response.json"

    for path in (
        readme_path,
        root_html_path,
        campaign_html_path,
        campaigns_path,
        detail_path,
        trials_path,
        trial_detail_path,
        timeseries_path,
        alerts_path,
        decision_trace_path,
    ):
        assert path.exists(), f"missing dashboard preview example artifact: {path}"

    root_html = root_html_path.read_text(encoding="utf-8")
    assert "Looptimum Dashboard Preview" in root_html
    assert 'data-current-campaign-id=""' in root_html
    assert "/dashboard/assets/dashboard.css" in root_html

    campaign_html = campaign_html_path.read_text(encoding="utf-8")
    assert 'data-current-campaign-id="bo_client_demo"' in campaign_html
    assert "best-timeseries-panel" in campaign_html
    assert "trial-detail-panel" in campaign_html

    campaigns_payload = json.loads(campaigns_path.read_text(encoding="utf-8"))
    assert campaigns_payload["campaigns"][0]["campaign_id"] == "bo_client_demo"

    detail_payload = json.loads(detail_path.read_text(encoding="utf-8"))
    assert detail_payload["campaign"]["campaign_id"] == "bo_client_demo"
    assert detail_payload["status"]["observations"] == 1

    trials_payload = json.loads(trials_path.read_text(encoding="utf-8"))
    assert trials_payload["count"] == 2
    assert trials_payload["counts"]["pending"] == 1
    assert trials_payload["trials"][0]["trial_id"] == 2

    trial_detail_payload = json.loads(trial_detail_path.read_text(encoding="utf-8"))
    assert trial_detail_payload["trial"]["trial_id"] == 1
    assert trial_detail_payload["trial"]["status"] == "ok"

    timeseries_payload = json.loads(timeseries_path.read_text(encoding="utf-8"))
    assert timeseries_payload["points"][0]["trial_id"] == 1
    assert timeseries_payload["points"][0]["is_improvement"] is True

    alerts_payload = json.loads(alerts_path.read_text(encoding="utf-8"))
    assert alerts_payload["pending_count"] == 1
    assert alerts_payload["decision_trace_available"] is True
    assert alerts_payload["report_available"] is True

    decision_trace_payload = json.loads(decision_trace_path.read_text(encoding="utf-8"))
    assert decision_trace_payload["available"] is True
    assert decision_trace_payload["count"] == 2


def test_auth_preview_example_pack_has_expected_artifacts() -> None:
    assert AUTH_PREVIEW_EXAMPLE.exists(), (
        f"missing auth preview example pack: {AUTH_PREVIEW_EXAMPLE}"
    )

    readme_path = AUTH_PREVIEW_EXAMPLE / "README.md"
    local_users_path = AUTH_PREVIEW_EXAMPLE / "local_dev_auth_users.json"
    oidc_config_path = AUTH_PREVIEW_EXAMPLE / "oidc_config.json"
    auth_required_path = AUTH_PREVIEW_EXAMPLE / "auth_required_response.json"
    insufficient_role_path = AUTH_PREVIEW_EXAMPLE / "insufficient_role_response.json"
    auth_preview_disabled_path = AUTH_PREVIEW_EXAMPLE / "auth_preview_disabled_response.json"
    authenticated_list_path = AUTH_PREVIEW_EXAMPLE / "authenticated_campaign_list_response.json"
    audit_log_path = AUTH_PREVIEW_EXAMPLE / "auth_audit_log.jsonl"

    for path in (
        readme_path,
        local_users_path,
        oidc_config_path,
        auth_required_path,
        insufficient_role_path,
        auth_preview_disabled_path,
        authenticated_list_path,
        audit_log_path,
    ):
        assert path.exists(), f"missing auth preview example artifact: {path}"

    local_users_payload = json.loads(local_users_path.read_text(encoding="utf-8"))
    assert [user["role"] for user in local_users_payload] == ["viewer", "operator", "admin"]
    assert [user["username"] for user in local_users_payload] == ["viewer", "operator", "admin"]

    oidc_payload = json.loads(oidc_config_path.read_text(encoding="utf-8"))
    assert oidc_payload["issuer"] == "https://issuer.example.test"
    assert oidc_payload["audience"] == "looptimum-preview"
    assert oidc_payload["role_mapping"]["group:admins"] == "admin"

    auth_required_payload = json.loads(auth_required_path.read_text(encoding="utf-8"))
    assert auth_required_payload["error"]["code"] == "auth_required"

    insufficient_role_payload = json.loads(insufficient_role_path.read_text(encoding="utf-8"))
    assert insufficient_role_payload["error"]["code"] == "insufficient_role"
    assert "required role 'operator'" in insufficient_role_payload["error"]["message"]

    auth_preview_disabled_payload = json.loads(
        auth_preview_disabled_path.read_text(encoding="utf-8")
    )
    assert auth_preview_disabled_payload["error"]["code"] == "auth_preview_disabled"

    authenticated_list_payload = json.loads(authenticated_list_path.read_text(encoding="utf-8"))
    assert authenticated_list_payload["campaigns"][0]["campaign_id"] == "bo_client_demo"

    audit_events = [
        json.loads(line)
        for line in audit_log_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    assert any(
        event["event_type"] == "privileged_action"
        and event["action"] == "register_campaign"
        and event["outcome"] == "allowed"
        for event in audit_events
    )
    assert any(
        event["event_type"] == "authz_failure"
        and event["action"] == "route_access"
        and event["reason"] == "requires_role=operator"
        for event in audit_events
    )
    assert any(
        event["event_type"] == "authz_failure"
        and event["action"] == "campaign_auth_preview_validation"
        and event["reason"] == "campaign_auth_preview_disabled"
        for event in audit_events
    )
