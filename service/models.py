from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

REGISTRY_SCHEMA_VERSION = "0.1.0-preview"
ServiceRole = Literal["viewer", "operator", "admin"]


class CampaignRecord(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    campaign_id: str
    root_path: str
    label: str
    created_at: float


class LocalAuthUser(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    username: str
    password: str
    role: ServiceRole


class AuthenticatedPrincipal(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    username: str
    role: ServiceRole
    auth_mode: Literal["basic", "oidc"]


class RegistrySnapshot(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str = REGISTRY_SCHEMA_VERSION
    campaigns: list[CampaignRecord] = Field(default_factory=list)


class CampaignRegistrationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    root_path: str
    campaign_id: str | None = None
    label: str | None = None


class CampaignListResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    campaigns: list[CampaignRecord]


class CampaignDetailResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    campaign: CampaignRecord
    status: dict[str, Any]
    paths: dict[str, str]
    artifacts: dict[str, bool]


class SuggestRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    count: int | None = None
    output_mode: Literal["json", "jsonl"] = "json"
    lock_timeout_seconds: float | None = None
    fail_fast: bool = False


class IngestRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    payload: dict[str, Any]
    lease_token: str | None = None
    lock_timeout_seconds: float | None = None
    fail_fast: bool = False


class ResetRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    yes: bool = False
    archive: bool | None = None
    lock_timeout_seconds: float | None = None
    fail_fast: bool = False


class RestoreRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    archive_id: str
    yes: bool = False
    lock_timeout_seconds: float | None = None
    fail_fast: bool = False


class HealthResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ok: bool
    preview: str
    registry_file: str
    campaign_count: int
