from __future__ import annotations

import base64
import binascii
import hmac
from typing import Any

from fastapi import Request, status
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

from service.config import ServiceAuthConfig
from service.models import AuthenticatedPrincipal, LocalAuthUser

_BASIC_REALM = 'Basic realm="Looptimum Service Preview"'
_HEALTH_PATH = "/health"


def _error_payload(*, code: str, message: str) -> dict[str, Any]:
    return {"error": {"code": code, "message": message}}


def _unauthorized_response(*, code: str, message: str) -> JSONResponse:
    return JSONResponse(
        status_code=status.HTTP_401_UNAUTHORIZED,
        content=_error_payload(code=code, message=message),
        headers={"WWW-Authenticate": _BASIC_REALM},
    )


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
