from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

REGISTRY_SCHEMA_VERSION = "0.1.0-preview"


class CampaignRecord(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    campaign_id: str
    root_path: str
    label: str
    created_at: float


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


class HealthResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ok: bool
    preview: str
    registry_file: str
    campaign_count: int
