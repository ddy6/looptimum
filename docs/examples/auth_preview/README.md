# Auth Preview Example Pack

Reference artifacts for the preview-only auth, RBAC, and OIDC surface mounted
on the local `service/` stack.

This pack is aligned to the current preview service behavior and keeps the
examples intentionally local-first:

- `local_dev_auth_users.json`: example HTTP Basic user config for `viewer`,
  `operator`, and `admin`
- `oidc_config.json`: example preview OIDC config with issuer, audience, and
  claim-to-role mapping
- `auth_required_response.json`: machine-readable `401` response for missing
  credentials on a protected preview route
- `insufficient_role_response.json`: machine-readable `403` response for a
  `viewer` attempting an `operator` route
- `auth_preview_disabled_response.json`: machine-readable `403` response when
  the service is auth-enabled but the campaign root has
  `enable_auth_preview = false`
- `authenticated_campaign_list_response.json`: successful `GET /campaigns`
  payload for an authenticated `viewer`
- `auth_audit_log.jsonl`: service-owned audit log examples covering one
  privileged action and two authorization failures

Captured flow represented here:

1. start the preview service in local-dev basic-auth mode
2. register one auth-enabled campaign as `admin`
3. read campaign inventory as `viewer`
4. deny a `viewer` attempt to call `suggest`
5. deny registration of a campaign root with `enable_auth_preview = false`
6. inspect the service-owned auth audit log under `service_state/`

Operational notes illustrated here:

- preview auth stays service-scoped; it does not change direct CLI/runtime
  usage inside a campaign root
- role enforcement is route-based: `viewer`, `operator`, then `admin`
- the audit log is a service sidecar and does not replace campaign runtime
  lifecycle logs
- the current OIDC path is preview-only and should be evaluated as a local or
  trusted-environment feature, not as a finalized production SSO boundary

These files are documentation examples, not stability guarantees.
