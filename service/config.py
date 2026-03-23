from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from pydantic import TypeAdapter, ValidationError

from service.models import LocalAuthUser

SERVICE_REGISTRY_FILE_ENV = "LOOPTIMUM_SERVICE_REGISTRY_FILE"
SERVICE_AUTH_MODE_ENV = "LOOPTIMUM_SERVICE_AUTH_MODE"
SERVICE_AUTH_USERS_ENV = "LOOPTIMUM_SERVICE_AUTH_USERS"
DEFAULT_SERVICE_REGISTRY_FILE = "service_state/campaign_registry.json"
ServiceAuthMode = Literal["disabled", "basic"]


class ServiceConfigError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class ServiceAuthConfig:
    mode: ServiceAuthMode
    local_users: tuple[LocalAuthUser, ...] = ()


@dataclass(frozen=True, slots=True)
class ServiceConfig:
    registry_file: Path
    auth: ServiceAuthConfig


def resolve_registry_file(path: str | Path | None = None) -> Path:
    raw = str(path) if path is not None else os.environ.get(SERVICE_REGISTRY_FILE_ENV)
    selected = raw if raw and raw.strip() else DEFAULT_SERVICE_REGISTRY_FILE
    candidate = Path(selected).expanduser()
    if candidate.is_absolute():
        return candidate.resolve()
    return (Path.cwd() / candidate).resolve()


def _normalize_auth_mode(value: str | None) -> ServiceAuthMode:
    raw = value.strip().lower() if value is not None else "disabled"
    if raw not in {"disabled", "basic"}:
        raise ServiceConfigError("service auth mode must be one of: disabled, basic")
    if raw == "disabled":
        return "disabled"
    return "basic"


def _normalize_auth_users(
    value: str | list[dict[str, Any]] | list[LocalAuthUser] | None,
) -> tuple[LocalAuthUser, ...]:
    if value is None:
        return ()
    parsed_value: Any
    if isinstance(value, str):
        raw = value.strip()
        if not raw:
            return ()
        try:
            parsed_value = TypeAdapter(list[dict[str, Any]]).validate_json(raw)
        except ValidationError as exc:
            raise ServiceConfigError(
                "service auth users env/config must be a JSON array of user objects"
            ) from exc
    else:
        parsed_value = value

    try:
        users = tuple(TypeAdapter(list[LocalAuthUser]).validate_python(parsed_value))
    except ValidationError as exc:
        raise ServiceConfigError(
            "service auth users must have username, password, and role"
        ) from exc
    usernames = [user.username for user in users]
    duplicates = sorted({username for username in usernames if usernames.count(username) > 1})
    if duplicates:
        raise ServiceConfigError(
            f"service auth users must have unique usernames; duplicates: {', '.join(duplicates)}"
        )
    return users


def build_service_auth_config(
    *,
    auth_mode: str | None = None,
    auth_users: str | list[dict[str, Any]] | list[LocalAuthUser] | None = None,
) -> ServiceAuthConfig:
    mode = _normalize_auth_mode(
        auth_mode if auth_mode is not None else os.environ.get(SERVICE_AUTH_MODE_ENV)
    )
    users = _normalize_auth_users(
        auth_users if auth_users is not None else os.environ.get(SERVICE_AUTH_USERS_ENV)
    )
    if mode == "basic" and not users:
        raise ServiceConfigError("basic service auth mode requires at least one configured user")
    if mode == "disabled":
        return ServiceAuthConfig(mode="disabled")
    return ServiceAuthConfig(mode="basic", local_users=users)


def build_service_config(
    path: str | Path | None = None,
    *,
    auth_mode: str | None = None,
    auth_users: str | list[dict[str, Any]] | list[LocalAuthUser] | None = None,
) -> ServiceConfig:
    return ServiceConfig(
        registry_file=resolve_registry_file(path),
        auth=build_service_auth_config(auth_mode=auth_mode, auth_users=auth_users),
    )
