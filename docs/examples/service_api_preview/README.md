# Service API Preview Example Pack

Generated reference artifacts for the preview-only local FastAPI wrapper in
`service/`, captured against a temp `templates/bo_client_demo` campaign root.

This pack shows the current preview surface:

- `health_response.json`: baseline `GET /health` response
- `campaign_create_request.json`: sample `POST /campaigns` request body
- `campaign_create_response.json`: campaign registration response
- `campaign_list_response.json`: `GET /campaigns` inventory after one
  registration
- `campaign_detail_response.json`: `GET /campaigns/{campaign_id}/detail`
  response after one ingest plus explicit report generation
- `suggest_request.json`: sample batch `POST .../suggest` request
- `suggest_response.json`: default bundle JSON response for count `> 1`
- `suggest_response.jsonl`: equivalent NDJSON response for worker-oriented
  consumption
- `ingest_request.json`: canonical `POST .../ingest` request body
- `ingest_response.json`: ingest success response
- `status_after_ingest.json`: `GET .../status` response after one ingest
- `report_response.json`: `GET .../report` response after explicit CLI `report`

The captured flow is:

1. start the local preview service with a registry file
2. register a campaign root with `enable_service_api_preview = true`
3. call `suggest` with `count = 2`
4. ingest one successful result payload
5. run the explicit CLI `report` command
6. read back `status`, `detail`, and `report` through the service

Operational notes illustrated here:

- the preview service is a wrapper over the file-backed runtime, not a second
  state authority
- `report` remains explicit and artifact-backed; the service reads
  `state/report.json` but does not generate it
- bundle JSON and NDJSON expose the same canonical suggestion objects
- the registry stores campaign metadata only and does not duplicate optimizer
  state

These files are documentation examples, not API stability guarantees.
