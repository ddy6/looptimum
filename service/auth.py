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

from service.config import ServiceAuthConfig, ServiceOidcConfig
from service.models import AuthAuditEvent, AuthenticatedPrincipal, LocalAuthUser, ServiceRole
from service.registry import ServiceRegistryError

_BASIC_REALM = 'Basic realm="Looptimum Service Preview"'
_BEARER_REALM = 'Bearer realm="Looptimum Service Preview"'
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


def _bearer_unauthorized_response(*, code: str, message: str) -> JSONResponse:
    return JSONResponse(
        status_code=status.HTTP_401_UNAUTHORIZED,
        content=_error_payload(code=code, message=message),
        headers={"WWW-Authenticate": _BEARER_REALM},
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


def _decode_bearer_authorization(header_value: str) -> str:
    scheme, _, token = header_value.partition(" ")
    if scheme.lower() != "bearer" or not token.strip():
        raise ValueError("Authorization header must use Bearer auth")
    return token.strip()


def _decode_base64url_segment(segment: str) -> bytes:
    padded = segment + "=" * ((4 - len(segment) % 4) % 4)
    try:
        return base64.urlsafe_b64decode(padded.encode("ascii"))
    except (ValueError, binascii.Error) as exc:
        raise ValueError("Bearer token must contain valid base64url-encoded JWT segments") from exc


def _decode_unverified_jwt_claims(token: str) -> dict[str, Any]:
    parts = token.split(".")
    if len(parts) != 3:
        raise ValueError("Bearer token must be a JWT with three dot-separated segments")
    _header, payload_segment, _signature = parts
    try:
        payload = json.loads(_decode_base64url_segment(payload_segment).decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("Bearer token payload must decode to a JSON object") from exc
    if not isinstance(payload, dict):
        raise ValueError("Bearer token payload must decode to a JSON object")
    return payload


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


def _normalize_token_audience(raw_value: Any) -> list[str]:
    if isinstance(raw_value, str):
        value = raw_value.strip()
        return [] if not value else [value]
    if isinstance(raw_value, list):
        audiences: list[str] = []
        for item in raw_value:
            if not isinstance(item, str):
                raise ValueError(
                    "OIDC bearer token audience claim must be a string or string array"
                )
            normalized = item.strip()
            if normalized:
                audiences.append(normalized)
        return audiences
    raise ValueError("OIDC bearer token audience claim must be a string or string array")


def _resolve_role_from_claims(
    oidc_config: ServiceOidcConfig, claims: dict[str, Any]
) -> ServiceRole:
    raw_roles = claims.get(oidc_config.role_claim)
    role_values: list[str] = []
    if isinstance(raw_roles, str):
        normalized = raw_roles.strip()
        if normalized:
            role_values.append(normalized)
    elif isinstance(raw_roles, list):
        for item in raw_roles:
            if isinstance(item, str):
                normalized = item.strip()
                if normalized:
                    role_values.append(normalized)
    else:
        raise ValueError(
            f"OIDC bearer token must include a string or string-array '{oidc_config.role_claim}' claim"
        )

    mapped_roles: list[ServiceRole] = []
    role_mapping = oidc_config.role_mapping or {}
    for role_value in role_values:
        mapped = role_mapping.get(role_value)
        if mapped is not None:
            mapped_roles.append(mapped)
    if not mapped_roles:
        raise ValueError(
            f"OIDC bearer token roles did not map to a service role via claim '{oidc_config.role_claim}'"
        )
    return max(mapped_roles, key=lambda role: _ROLE_ORDER[role])


def resolve_oidc_principal(
    auth_config: ServiceAuthConfig, authorization_header: str | None
) -> AuthenticatedPrincipal:
    if auth_config.mode != "oidc" or auth_config.oidc is None:
        raise ValueError(f"unsupported auth mode for OIDC resolution: {auth_config.mode}")
    if authorization_header is None:
        raise ValueError("Authentication is required for this preview route")
    token = _decode_bearer_authorization(authorization_header)
    claims = _decode_unverified_jwt_claims(token)
    oidc_config = auth_config.oidc

    issuer = claims.get("iss")
    if not isinstance(issuer, str) or issuer.strip() != oidc_config.issuer:
        raise ValueError("OIDC bearer token issuer did not match the configured issuer")

    audiences = _normalize_token_audience(claims.get("aud"))
    if oidc_config.audience not in audiences:
        raise ValueError("OIDC bearer token audience did not match the configured audience")

    subject = claims.get(oidc_config.subject_claim)
    if not isinstance(subject, str) or not subject.strip():
        raise ValueError(
            f"OIDC bearer token must include a non-empty '{oidc_config.subject_claim}' claim"
        )

    role = _resolve_role_from_claims(oidc_config, claims)
    return AuthenticatedPrincipal(username=subject.strip(), role=role, auth_mode="oidc")


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
            if auth_config.mode == "basic":
                principal = resolve_local_dev_principal(
                    auth_config,
                    request.headers.get("Authorization"),
                )
            elif auth_config.mode == "oidc":
                principal = resolve_oidc_principal(
                    auth_config,
                    request.headers.get("Authorization"),
                )
            else:
                raise ValueError(f"unsupported service auth mode: {auth_config.mode}")
        except ValueError as exc:
            message = str(exc)
            code = "auth_required"
            if auth_config.mode == "basic":
                if "failed" in message or "valid base64" in message:
                    code = "invalid_credentials"
                elif "HTTP Basic" in message:
                    code = "unsupported_auth_scheme"
                return _unauthorized_response(code=code, message=message)
            if "issuer" in message or "audience" in message or "claim" in message:
                code = "invalid_token_claims"
            elif "JWT" in message or "base64url" in message:
                code = "invalid_bearer_token"
            elif "Bearer auth" in message:
                code = "unsupported_auth_scheme"
            return _bearer_unauthorized_response(code=code, message=message)

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
