# Dashboard Preview Example Pack

Captured HTML and read-model payloads for the preview-only dashboard mounted
from the local `service/` stack.

This pack is generated against a temp `templates/bo_client_demo` campaign root
with:

- `feature_flags.enable_service_api_preview = true`
- `feature_flags.enable_dashboard_preview = true`

Included artifacts:

- `dashboard_root.html`: baseline `GET /dashboard` shell before a campaign is
  selected
- `dashboard_campaign.html`: `GET /dashboard/campaigns/{campaign_id}` shell for
  a registered campaign
- `campaign_list_response.json`: `GET /campaigns`
- `campaign_detail_response.json`: `GET /campaigns/{campaign_id}/detail`
- `trials_response.json`: `GET /campaigns/{campaign_id}/trials`
- `trial_detail_response.json`: `GET /campaigns/{campaign_id}/trials/1`
- `timeseries_best_response.json`: `GET /campaigns/{campaign_id}/timeseries/best`
- `alerts_response.json`: `GET /campaigns/{campaign_id}/alerts`
- `decision_trace_response.json`: `GET /campaigns/{campaign_id}/decision-trace`

Captured flow:

1. start the preview service
2. register a dashboard-enabled campaign root
3. issue two suggestions
4. ingest one successful result
5. run explicit CLI `report`
6. capture the dashboard HTML shell plus the read-only service payloads it
   consumes

Operational notes illustrated here:

- the dashboard remains read-only and API-backed only
- per-trial drilldown and progress views come from canonical runtime files via
  the preview API, not from a second service-owned cache
- export actions in the shell point at the canonical service export routes for
  `report.json`, `report.md`, and `decision-trace.jsonl`

These files are documentation examples, not stability guarantees.
