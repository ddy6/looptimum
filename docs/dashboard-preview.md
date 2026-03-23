# Dashboard Preview

This page documents the preview-only operator UI mounted from the local
`service/` stack. It is a read-only dashboard over the preview API, not a
second runtime or state authority.

## Scope Boundary

- preview only: this UI is not part of the stable `v0.3.x` compatibility
  guarantee
- API-backed only: the dashboard reads through the preview service endpoints
  and does not read campaign state files directly
- read-only in Workstream 11: it does not expose `suggest`, `ingest`, `reset`,
  or `restore` controls
- local operator mode: no auth, RBAC, SSO, or multi-controller coordination is
  introduced here

## Startup

From repo root:

```bash
LOOPTIMUM_SERVICE_REGISTRY_FILE=service_state/campaign_registry.json \
python -m uvicorn service.app:create_app --factory
```

Required campaign-side flags:

```json
{
  "feature_flags": {
    "enable_service_api_preview": true,
    "enable_dashboard_preview": true
  }
}
```

`enable_service_api_preview` is still required for registration and service API
access. `enable_dashboard_preview` is additionally required for campaign-bound
dashboard routes such as `/dashboard/campaigns/<campaign_id>`.

## Route Surface

Current preview UI routes:

- `GET /dashboard`
- `GET /dashboard/campaigns/{campaign_id}`

The dashboard shell fetches the following read-only service endpoints:

- `GET /health`
- `GET /campaigns`
- `GET /campaigns/{campaign_id}/detail`
- `GET /campaigns/{campaign_id}/trials`
- `GET /campaigns/{campaign_id}/trials/{trial_id}`
- `GET /campaigns/{campaign_id}/timeseries/best`
- `GET /campaigns/{campaign_id}/alerts`
- `GET /campaigns/{campaign_id}/decision-trace`
- `GET /campaigns/{campaign_id}/exports/report.json`
- `GET /campaigns/{campaign_id}/exports/report.md`
- `GET /campaigns/{campaign_id}/exports/decision-trace.jsonl`

## Operator Workflow

Typical local preview flow:

1. start the preview service
2. register a campaign root with service preview enabled
3. open `/dashboard`
4. choose a registered campaign
5. inspect progress, alerts, per-trial detail, and export links without
   leaving the preview service

The dashboard is intended for monitoring and troubleshooting:

- campaign list and high-level status headline
- best-over-time progression from canonical runtime artifacts
- stale/pending alert context
- per-trial params, objectives, and decision metadata
- direct downloads of canonical report and decision-trace artifacts

## Responsive and Accessibility Notes

- the shell keeps semantic landmarks (`header`, `main`, `nav`, `section`,
  `article`) and explicit labels for the campaign rail and chart region
- health and state messages use lightweight live-region semantics where useful
- layout collapses to a single-column stack at narrower widths using the
  shipped static CSS only; no frontend build or component framework is required

## Example Pack

Reference dashboard HTML and read-model payloads:

- [`examples/dashboard_preview/README.md`](./examples/dashboard_preview/README.md)

That pack includes captured shell HTML plus the JSON responses the dashboard
uses for trials, alerts, decision trace, and best-over-time rendering.
