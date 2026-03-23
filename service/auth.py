from __future__ import annotations

import base64
import binascii
import hmac
import json
import time
from pathlib import Path
from typing import Any, Literal

from fastapi import Request, status
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

from service.config import ServiceAuthConfig
from service.models import AuthAuditEvent, AuthenticatedPrincipal, LocalAuthUser, ServiceRole
from service.registry import ServiceRegistryError

_BASIC_REALM = 'Basic realm="Looptimum Service Preview"'
_HEALTH_PATH = "/health"
_ROLE_ORDER: dict[ServiceRole, int] = {"viewer": 0, "operator": 1, "admin": 2}


class ServiceAuthorizationError(ServiceRegistryError):
    pass


def _error_payload(*, code: str, message: str) -> dict[str, Any]:
    return {"error": {"code": code, "message": message}}


def _unauthorized_response(*, code: str, message: str) -> JSONResponse:
    return JSONResponse(
        status_code=status.HTTP_401_UNAUTHORIZED,
        content=_error_payload(code=code, message=message),
        headers={"WWW-Authenticate": _BASIC_REALM},
    )


def _append_jsonl(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, sort_keys=True))
        handle.write("\n")


def _decode_basic_authorization(header_value: str) -> tuple[str, str]:
    scheme, _, encoded = header_value.partition(" ")
    if scheme.lower() != "basic" or not encoded.strip():
        raise ValueError("Authorization header must use HTTP Basic auth")
    try:
        decoded = base64.b64decode(encoded.strip(), validate=True).decode("utf-8")
    except (ValueError, binascii.Error, UnicodeDecodeError) as exc:
        raise ValueError("Authorization header must contain valid base64 credentials") from exc
    username, separator, password = decoded.partition(":")
    if not separator or not username:
        raise ValueError("Authorization header must encode username:password credentials")
    return username, password


def _match_local_user(
    users: tuple[LocalAuthUser, ...], *, username: str, password: str
) -> LocalAuthUser | None:
    for user in users:
        if user.username != username:
            continue
        if hmac.compare_digest(user.password, password):
            return user
        return None
    return None


def resolve_local_dev_principal(
    auth_config: ServiceAuthConfig, authorization_header: str | None
) -> AuthenticatedPrincipal:
    if auth_config.mode != "basic":
        raise ValueError(f"unsupported auth mode for local-dev resolution: {auth_config.mode}")
    if authorization_header is None:
        raise ValueError("Authentication is required for this preview route")
    username, password = _decode_basic_authorization(authorization_header)
    user = _match_local_user(auth_config.local_users, username=username, password=password)
    if user is None:
        raise ValueError("Authentication failed for the provided preview credentials")
    return AuthenticatedPrincipal(username=user.username, role=user.role, auth_mode="basic")


def record_auth_audit_event(
    audit_log_file: Path,
    *,
    principal: AuthenticatedPrincipal | None,
    request: Request,
    event_type: Literal["authz_failure", "privileged_action"],
    action: str,
    outcome: Literal["allowed", "denied"],
    reason: str | None = None,
    campaign_id: str | None = None,
) -> None:
    event = AuthAuditEvent(
        event_type=event_type,
        recorded_at=time.time(),
        username=None if principal is None else principal.username,
        role=None if principal is None else principal.role,
        auth_mode=None if principal is None else principal.auth_mode,
        method=request.method,
        path=request.url.path,
        action=action,
        outcome=outcome,
        reason=reason,
        campaign_id=campaign_id,
    )
    _append_jsonl(audit_log_file, event.model_dump(mode="json"))


class ServiceAuthMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: Any) -> JSONResponse | Any:
        request.state.service_principal = None
        service_config = request.app.state.service_config
        auth_config = service_config.auth
        if auth_config.mode == "disabled" or request.url.path == _HEALTH_PATH:
            return await call_next(request)

        try:
            principal = resolve_local_dev_principal(
                auth_config,
                request.headers.get("Authorization"),
            )
        except ValueError as exc:
            message = str(exc)
            code = "auth_required"
            if "failed" in message or "valid base64" in message:
                code = "invalid_credentials"
            elif "HTTP Basic" in message:
                code = "unsupported_auth_scheme"
            return _unauthorized_response(code=code, message=message)

        request.state.service_principal = principal
        return await call_next(request)


def require_authenticated_principal(request: Request) -> AuthenticatedPrincipal | None:
    service_config = request.app.state.service_config
    if service_config.auth.mode == "disabled":
        return None
    principal = getattr(request.state, "service_principal", None)
    if isinstance(principal, AuthenticatedPrincipal):
        return principal
    raise RuntimeError("Service auth middleware did not attach a request principal")


def _require_role(request: Request, *, required_role: ServiceRole) -> AuthenticatedPrincipal | None:
    principal = require_authenticated_principal(request)
    if principal is None:
        return None
    if _ROLE_ORDER[principal.role] >= _ROLE_ORDER[required_role]:
        return principal

    record_auth_audit_event(
        request.app.state.service_config.auth_audit_log_file,
        principal=principal,
        request=request,
        event_type="authz_failure",
        action="route_access",
        outcome="denied",
        reason=f"requires_role={required_role}",
        campaign_id=request.path_params.get("campaign_id"),
    )
    raise ServiceAuthorizationError(
        f"authenticated principal role '{principal.role}' does not satisfy required role "
        f"'{required_role}' for {request.method} {request.url.path}"
    )


def require_viewer_principal(request: Request) -> AuthenticatedPrincipal | None:
    return _require_role(request, required_role="viewer")


def require_operator_principal(request: Request) -> AuthenticatedPrincipal | None:
    return _require_role(request, required_role="operator")


def require_admin_principal(request: Request) -> AuthenticatedPrincipal | None:
    return _require_role(request, required_role="admin")
