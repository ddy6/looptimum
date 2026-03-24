from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal, cast

from pydantic import TypeAdapter, ValidationError

from service.models import LocalAuthUser, ServiceCoordinationMode, ServiceRole

SERVICE_REGISTRY_FILE_ENV = "LOOPTIMUM_SERVICE_REGISTRY_FILE"
SERVICE_AUTH_MODE_ENV = "LOOPTIMUM_SERVICE_AUTH_MODE"
SERVICE_AUTH_USERS_ENV = "LOOPTIMUM_SERVICE_AUTH_USERS"
SERVICE_OIDC_CONFIG_ENV = "LOOPTIMUM_SERVICE_OIDC_CONFIG"
SERVICE_AUTH_AUDIT_LOG_FILE_ENV = "LOOPTIMUM_SERVICE_AUTH_AUDIT_LOG_FILE"
SERVICE_COORDINATION_MODE_ENV = "LOOPTIMUM_SERVICE_COORDINATION_MODE"
SERVICE_COORDINATION_SQLITE_FILE_ENV = "LOOPTIMUM_SERVICE_COORDINATION_SQLITE_FILE"
SERVICE_COORDINATION_LEASE_TTL_SECONDS_ENV = "LOOPTIMUM_SERVICE_COORDINATION_LEASE_TTL_SECONDS"
DEFAULT_SERVICE_REGISTRY_FILE = "service_state/campaign_registry.json"
DEFAULT_SERVICE_AUTH_AUDIT_LOG_FILE = "service_state/auth_audit_log.jsonl"
DEFAULT_SERVICE_COORDINATION_SQLITE_FILE = "service_state/coordination.sqlite3"
DEFAULT_SERVICE_COORDINATION_LEASE_TTL_SECONDS = 30.0
ServiceAuthMode = Literal["disabled", "basic", "oidc"]


class ServiceConfigError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class ServiceOidcConfig:
    issuer: str
    audience: str
    subject_claim: str = "sub"
    role_claim: str = "roles"
    role_mapping: dict[str, ServiceRole] | None = None


@dataclass(frozen=True, slots=True)
class ServiceAuthConfig:
    mode: ServiceAuthMode
    local_users: tuple[LocalAuthUser, ...] = ()
    oidc: ServiceOidcConfig | None = None


@dataclass(frozen=True, slots=True)
class ServiceCoordinationConfig:
    mode: ServiceCoordinationMode
    sqlite_file: Path
    lease_ttl_seconds: float


@dataclass(frozen=True, slots=True)
class ServiceConfig:
    registry_file: Path
    auth_audit_log_file: Path
    auth: ServiceAuthConfig
    coordination: ServiceCoordinationConfig


def resolve_registry_file(path: str | Path | None = None) -> Path:
    raw = str(path) if path is not None else os.environ.get(SERVICE_REGISTRY_FILE_ENV)
    selected = raw if raw and raw.strip() else DEFAULT_SERVICE_REGISTRY_FILE
    candidate = Path(selected).expanduser()
    if candidate.is_absolute():
        return candidate.resolve()
    return (Path.cwd() / candidate).resolve()


def resolve_auth_audit_log_file(registry_file: Path, path: str | Path | None = None) -> Path:
    raw = str(path) if path is not None else os.environ.get(SERVICE_AUTH_AUDIT_LOG_FILE_ENV)
    selected = raw if raw and raw.strip() else str(registry_file.parent / "auth_audit_log.jsonl")
    candidate = Path(selected).expanduser()
    if candidate.is_absolute():
        return candidate.resolve()
    return (Path.cwd() / candidate).resolve()


def resolve_coordination_sqlite_file(registry_file: Path, path: str | Path | None = None) -> Path:
    raw = str(path) if path is not None else os.environ.get(SERVICE_COORDINATION_SQLITE_FILE_ENV)
    selected = raw if raw and raw.strip() else str(registry_file.parent / "coordination.sqlite3")
    candidate = Path(selected).expanduser()
    if candidate.is_absolute():
        return candidate.resolve()
    return (Path.cwd() / candidate).resolve()


def _as_positive_float(value: Any, *, field_name: str) -> float:
    try:
        normalized = float(value)
    except (TypeError, ValueError) as exc:
        raise ServiceConfigError(f"{field_name} must be a positive number") from exc
    if normalized <= 0.0:
        raise ServiceConfigError(f"{field_name} must be > 0")
    return normalized


def _normalize_auth_mode(value: str | None) -> ServiceAuthMode:
    raw = value.strip().lower() if value is not None else "disabled"
    if raw not in {"disabled", "basic", "oidc"}:
        raise ServiceConfigError("service auth mode must be one of: disabled, basic, oidc")
    if raw == "disabled":
        return "disabled"
    if raw == "basic":
        return "basic"
    return "oidc"


def _normalize_coordination_mode(value: str | None) -> ServiceCoordinationMode:
    raw = value.strip().lower() if value is not None else "file_lock"
    if raw not in {"file_lock", "sqlite_lease"}:
        raise ServiceConfigError(
            "service coordination mode must be one of: file_lock, sqlite_lease"
        )
    if raw == "file_lock":
        return "file_lock"
    return "sqlite_lease"


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


def _normalize_oidc_config(
    value: str | dict[str, Any] | ServiceOidcConfig | None,
) -> ServiceOidcConfig | None:
    if value is None:
        return None
    if isinstance(value, ServiceOidcConfig):
        return value
    parsed_value: dict[str, Any]
    if isinstance(value, str):
        raw = value.strip()
        if not raw:
            return None
        try:
            parsed_value = TypeAdapter(dict[str, Any]).validate_json(raw)
        except ValidationError as exc:
            raise ServiceConfigError(
                "service OIDC config env/config must be a JSON object"
            ) from exc
    else:
        parsed_value = value
    if not isinstance(parsed_value, dict):
        raise ServiceConfigError("service OIDC config must be a JSON object")

    issuer = str(parsed_value.get("issuer", "")).strip()
    audience = str(parsed_value.get("audience", "")).strip()
    subject_claim = str(parsed_value.get("subject_claim", "sub")).strip()
    role_claim = str(parsed_value.get("role_claim", "roles")).strip()
    raw_role_mapping = parsed_value.get("role_mapping")
    role_mapping: dict[str, ServiceRole] = {
        "viewer": "viewer",
        "operator": "operator",
        "admin": "admin",
    }
    if raw_role_mapping is not None:
        if not isinstance(raw_role_mapping, dict):
            raise ServiceConfigError("service OIDC role_mapping must be an object when provided")
        role_mapping = {}
        for raw_key, raw_value in raw_role_mapping.items():
            key = str(raw_key).strip()
            value_text = str(raw_value).strip()
            if not key:
                raise ServiceConfigError("service OIDC role_mapping keys must be non-empty")
            if value_text not in {"viewer", "operator", "admin"}:
                raise ServiceConfigError(
                    "service OIDC role_mapping values must be one of: viewer, operator, admin"
                )
            role_mapping[key] = cast(ServiceRole, value_text)

    if not issuer:
        raise ServiceConfigError("service OIDC config requires a non-empty issuer")
    if not audience:
        raise ServiceConfigError("service OIDC config requires a non-empty audience")
    if not subject_claim:
        raise ServiceConfigError("service OIDC config requires a non-empty subject_claim")
    if not role_claim:
        raise ServiceConfigError("service OIDC config requires a non-empty role_claim")

    return ServiceOidcConfig(
        issuer=issuer,
        audience=audience,
        subject_claim=subject_claim,
        role_claim=role_claim,
        role_mapping=role_mapping,
    )


def build_service_auth_config(
    *,
    auth_mode: str | None = None,
    auth_users: str | list[dict[str, Any]] | list[LocalAuthUser] | None = None,
    oidc_config: str | dict[str, Any] | ServiceOidcConfig | None = None,
) -> ServiceAuthConfig:
    mode = _normalize_auth_mode(
        auth_mode if auth_mode is not None else os.environ.get(SERVICE_AUTH_MODE_ENV)
    )
    users = _normalize_auth_users(
        auth_users if auth_users is not None else os.environ.get(SERVICE_AUTH_USERS_ENV)
    )
    oidc = _normalize_oidc_config(
        oidc_config if oidc_config is not None else os.environ.get(SERVICE_OIDC_CONFIG_ENV)
    )
    if mode == "basic" and not users:
        raise ServiceConfigError("basic service auth mode requires at least one configured user")
    if mode == "oidc" and oidc is None:
        raise ServiceConfigError("oidc service auth mode requires explicit OIDC config")
    if mode == "disabled":
        return ServiceAuthConfig(mode="disabled")
    if mode == "basic":
        return ServiceAuthConfig(mode="basic", local_users=users)
    return ServiceAuthConfig(mode="oidc", oidc=oidc)


def build_service_coordination_config(
    registry_file: Path,
    *,
    coordination_mode: str | None = None,
    coordination_sqlite_file: str | Path | None = None,
    coordination_lease_ttl_seconds: float | str | None = None,
) -> ServiceCoordinationConfig:
    mode = _normalize_coordination_mode(
        coordination_mode
        if coordination_mode is not None
        else os.environ.get(SERVICE_COORDINATION_MODE_ENV)
    )
    sqlite_file = resolve_coordination_sqlite_file(registry_file, coordination_sqlite_file)
    ttl_raw: Any = (
        coordination_lease_ttl_seconds
        if coordination_lease_ttl_seconds is not None
        else os.environ.get(SERVICE_COORDINATION_LEASE_TTL_SECONDS_ENV)
    )
    if ttl_raw is None or (isinstance(ttl_raw, str) and not ttl_raw.strip()):
        ttl_raw = DEFAULT_SERVICE_COORDINATION_LEASE_TTL_SECONDS
    lease_ttl_seconds = _as_positive_float(
        ttl_raw,
        field_name="service coordination lease ttl",
    )
    return ServiceCoordinationConfig(
        mode=mode,
        sqlite_file=sqlite_file,
        lease_ttl_seconds=lease_ttl_seconds,
    )


def build_service_config(
    path: str | Path | None = None,
    *,
    auth_mode: str | None = None,
    auth_users: str | list[dict[str, Any]] | list[LocalAuthUser] | None = None,
    oidc_config: str | dict[str, Any] | ServiceOidcConfig | None = None,
    auth_audit_log_file: str | Path | None = None,
    coordination_mode: str | None = None,
    coordination_sqlite_file: str | Path | None = None,
    coordination_lease_ttl_seconds: float | str | None = None,
) -> ServiceConfig:
    registry_file = resolve_registry_file(path)
    return ServiceConfig(
        registry_file=registry_file,
        auth_audit_log_file=resolve_auth_audit_log_file(
            registry_file,
            path=auth_audit_log_file,
        ),
        auth=build_service_auth_config(
            auth_mode=auth_mode,
            auth_users=auth_users,
            oidc_config=oidc_config,
        ),
        coordination=build_service_coordination_config(
            registry_file,
            coordination_mode=coordination_mode,
            coordination_sqlite_file=coordination_sqlite_file,
            coordination_lease_ttl_seconds=coordination_lease_ttl_seconds,
        ),
    )
