from __future__ import annotations

from typing import Any

from fastapi import FastAPI, status
from fastapi.responses import HTMLResponse, JSONResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles

from service.config import ServiceConfig, build_service_config
from service.dashboard import ASSETS_DIR, render_dashboard_shell
from service.models import (
    CampaignDetailResponse,
    CampaignListResponse,
    CampaignRecord,
    CampaignRegistrationRequest,
    HealthResponse,
    IngestRequest,
    ResetRequest,
    RestoreRequest,
    SuggestRequest,
)
from service.registry import (
    CampaignConflictError,
    CampaignNotFoundError,
    CampaignRegistry,
    DashboardPreviewDisabledError,
    InvalidCampaignRootError,
    PreviewDisabledError,
    ServiceRegistryError,
    validate_dashboard_root,
)
from service.runtime import (
    DecisionTraceNotGeneratedError,
    ReportNotGeneratedError,
    RuntimeArtifactError,
    RuntimeCommandError,
    TrialNotFoundError,
    build_alert_payload,
    build_best_timeseries,
    build_campaign_detail,
    build_status_payload,
    build_trial_summaries,
    ingest_via_runtime,
    load_decision_trace_payload,
    load_decision_trace_text,
    load_report_markdown_text,
    load_report_payload,
    load_trial_detail,
    reset_via_runtime,
    restore_via_runtime,
    suggest_via_runtime,
)


def _error_payload(*, code: str, message: str) -> dict[str, Any]:
    return {"error": {"code": code, "message": message}}


def _error_response(exc: ServiceRegistryError) -> JSONResponse:
    if isinstance(exc, InvalidCampaignRootError):
        return JSONResponse(
            status_code=status.HTTP_400_BAD_REQUEST,
            content=_error_payload(code="invalid_campaign_root", message=str(exc)),
        )
    if isinstance(exc, PreviewDisabledError):
        return JSONResponse(
            status_code=status.HTTP_403_FORBIDDEN,
            content=_error_payload(code="service_preview_disabled", message=str(exc)),
        )
    if isinstance(exc, DashboardPreviewDisabledError):
        return JSONResponse(
            status_code=status.HTTP_403_FORBIDDEN,
            content=_error_payload(code="dashboard_preview_disabled", message=str(exc)),
        )
    if isinstance(exc, CampaignConflictError):
        return JSONResponse(
            status_code=status.HTTP_409_CONFLICT,
            content=_error_payload(code="campaign_conflict", message=str(exc)),
        )
    if isinstance(exc, CampaignNotFoundError):
        return JSONResponse(
            status_code=status.HTTP_404_NOT_FOUND,
            content=_error_payload(code="campaign_not_found", message=str(exc)),
        )
    if isinstance(exc, TrialNotFoundError):
        return JSONResponse(
            status_code=status.HTTP_404_NOT_FOUND,
            content=_error_payload(code="trial_not_found", message=str(exc)),
        )
    if isinstance(exc, ReportNotGeneratedError):
        return JSONResponse(
            status_code=status.HTTP_404_NOT_FOUND,
            content=_error_payload(code="report_not_generated", message=str(exc)),
        )
    if isinstance(exc, DecisionTraceNotGeneratedError):
        return JSONResponse(
            status_code=status.HTTP_404_NOT_FOUND,
            content=_error_payload(code="decision_trace_not_generated", message=str(exc)),
        )
    if isinstance(exc, RuntimeArtifactError):
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content=_error_payload(code="runtime_artifact_error", message=str(exc)),
        )
    if isinstance(exc, RuntimeCommandError):
        payload = _error_payload(code=exc.code, message=exc.message)
        if exc.stdout.strip():
            payload["error"]["stdout"] = exc.stdout
        if exc.stderr.strip():
            payload["error"]["stderr"] = exc.stderr
        return JSONResponse(status_code=exc.status_code, content=payload)
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content=_error_payload(code="registry_state_error", message=str(exc)),
    )


def create_app(config: ServiceConfig | None = None) -> FastAPI:
    service_config = config or build_service_config()
    registry = CampaignRegistry(service_config.registry_file)

    app = FastAPI(
        title="Looptimum Service API Preview",
        version="0.4.0-preview",
        docs_url="/docs",
        redoc_url=None,
    )
    app.mount("/dashboard/assets", StaticFiles(directory=ASSETS_DIR), name="dashboard-assets")

    @app.exception_handler(ServiceRegistryError)
    async def handle_registry_error(_request: Any, exc: ServiceRegistryError) -> JSONResponse:
        return _error_response(exc)

    @app.get("/health", response_model=HealthResponse)
    def get_health() -> HealthResponse:
        return HealthResponse(
            ok=True,
            preview="service_api_preview",
            registry_file=str(service_config.registry_file),
            campaign_count=len(registry.list_campaigns()),
        )

    @app.get("/dashboard", response_class=HTMLResponse)
    def get_dashboard_root() -> HTMLResponse:
        return HTMLResponse(render_dashboard_shell())

    @app.get("/dashboard/campaigns/{campaign_id}", response_class=HTMLResponse)
    def get_dashboard_campaign(campaign_id: str) -> HTMLResponse:
        record = registry.get_campaign(campaign_id)
        validate_dashboard_root(record.root_path)
        return HTMLResponse(render_dashboard_shell(current_campaign_id=record.campaign_id))

    @app.get("/campaigns", response_model=CampaignListResponse)
    def list_campaigns() -> CampaignListResponse:
        return CampaignListResponse(campaigns=registry.list_campaigns())

    @app.post("/campaigns", response_model=CampaignRecord, status_code=status.HTTP_201_CREATED)
    def create_campaign(payload: CampaignRegistrationRequest) -> CampaignRecord:
        return registry.register_campaign(payload)

    @app.get("/campaigns/{campaign_id}", response_model=CampaignRecord)
    def get_campaign(campaign_id: str) -> CampaignRecord:
        return registry.get_campaign(campaign_id)

    @app.get("/campaigns/{campaign_id}/detail", response_model=CampaignDetailResponse)
    def get_campaign_detail(campaign_id: str) -> CampaignDetailResponse:
        return build_campaign_detail(registry.get_campaign(campaign_id))

    @app.get("/campaigns/{campaign_id}/status")
    def get_campaign_status(campaign_id: str) -> dict[str, Any]:
        return build_status_payload(registry.get_campaign_root(campaign_id))

    @app.get("/campaigns/{campaign_id}/report")
    def get_campaign_report(campaign_id: str) -> dict[str, Any]:
        return load_report_payload(registry.get_campaign_root(campaign_id))

    @app.get("/campaigns/{campaign_id}/trials")
    def get_campaign_trials(campaign_id: str) -> dict[str, Any]:
        return build_trial_summaries(registry.get_campaign_root(campaign_id))

    @app.get("/campaigns/{campaign_id}/trials/{trial_id}")
    def get_campaign_trial_detail(campaign_id: str, trial_id: int) -> dict[str, Any]:
        return load_trial_detail(registry.get_campaign_root(campaign_id), trial_id)

    @app.get("/campaigns/{campaign_id}/timeseries/best")
    def get_campaign_best_timeseries(campaign_id: str) -> dict[str, Any]:
        return build_best_timeseries(registry.get_campaign_root(campaign_id))

    @app.get("/campaigns/{campaign_id}/alerts")
    def get_campaign_alerts(campaign_id: str) -> dict[str, Any]:
        return build_alert_payload(registry.get_campaign_root(campaign_id))

    @app.get("/campaigns/{campaign_id}/decision-trace")
    def get_campaign_decision_trace(campaign_id: str) -> dict[str, Any]:
        return load_decision_trace_payload(registry.get_campaign_root(campaign_id))

    @app.get("/campaigns/{campaign_id}/exports/report.json")
    def export_campaign_report_json(campaign_id: str) -> JSONResponse:
        payload = load_report_payload(registry.get_campaign_root(campaign_id))
        return JSONResponse(
            content=payload,
            headers={"Content-Disposition": (f'attachment; filename="{campaign_id}-report.json"')},
        )

    @app.get("/campaigns/{campaign_id}/exports/report.md")
    def export_campaign_report_markdown(campaign_id: str) -> PlainTextResponse:
        text, _relative_path = load_report_markdown_text(registry.get_campaign_root(campaign_id))
        return PlainTextResponse(
            text,
            media_type="text/markdown",
            headers={"Content-Disposition": (f'attachment; filename="{campaign_id}-report.md"')},
        )

    @app.get("/campaigns/{campaign_id}/exports/decision-trace.jsonl")
    def export_campaign_decision_trace(campaign_id: str) -> PlainTextResponse:
        text, _relative_path = load_decision_trace_text(registry.get_campaign_root(campaign_id))
        return PlainTextResponse(
            text,
            media_type="application/x-ndjson",
            headers={
                "Content-Disposition": (
                    f'attachment; filename="{campaign_id}-decision-trace.jsonl"'
                )
            },
        )

    @app.post("/campaigns/{campaign_id}/suggest", response_model=None)
    def suggest_for_campaign(
        campaign_id: str,
        payload: SuggestRequest | None = None,
    ) -> Any:
        request = payload or SuggestRequest()
        response_payload, ndjson_output = suggest_via_runtime(
            registry.get_campaign_root(campaign_id),
            count=request.count,
            output_mode=request.output_mode,
            lock_timeout_seconds=request.lock_timeout_seconds,
            fail_fast=request.fail_fast,
        )
        if ndjson_output is not None:
            return PlainTextResponse(ndjson_output, media_type="application/x-ndjson")
        if response_payload is None:
            return {}
        return response_payload

    @app.post("/campaigns/{campaign_id}/ingest")
    def ingest_for_campaign(campaign_id: str, payload: IngestRequest) -> dict[str, Any]:
        return ingest_via_runtime(
            registry.get_campaign_root(campaign_id),
            payload=payload.payload,
            lease_token=payload.lease_token,
            lock_timeout_seconds=payload.lock_timeout_seconds,
            fail_fast=payload.fail_fast,
        )

    @app.post("/campaigns/{campaign_id}/reset")
    def reset_campaign(campaign_id: str, payload: ResetRequest) -> dict[str, Any]:
        return reset_via_runtime(
            registry.get_campaign_root(campaign_id),
            yes=payload.yes,
            archive=payload.archive,
            lock_timeout_seconds=payload.lock_timeout_seconds,
            fail_fast=payload.fail_fast,
        )

    @app.post("/campaigns/{campaign_id}/restore")
    def restore_campaign(campaign_id: str, payload: RestoreRequest) -> dict[str, Any]:
        return restore_via_runtime(
            registry.get_campaign_root(campaign_id),
            archive_id=payload.archive_id,
            yes=payload.yes,
            lock_timeout_seconds=payload.lock_timeout_seconds,
            fail_fast=payload.fail_fast,
        )

    return app
