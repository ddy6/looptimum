from __future__ import annotations

import json
import re
import threading
import time
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from service.models import CampaignRecord, CampaignRegistrationRequest, RegistrySnapshot

_CAMPAIGN_ID_PATTERN = re.compile(r"[^a-z0-9_-]+")
_REQUIRED_CAMPAIGN_FILES = (
    "bo_config.json",
    "objective_schema.json",
    "parameter_space.json",
    "run_bo.py",
)


class ServiceRegistryError(ValueError):
    pass


class InvalidCampaignRootError(ServiceRegistryError):
    pass


class PreviewDisabledError(ServiceRegistryError):
    pass


class DashboardPreviewDisabledError(ServiceRegistryError):
    pass


class CampaignConflictError(ServiceRegistryError):
    pass


class CampaignNotFoundError(ServiceRegistryError):
    pass


class RegistryStateError(ServiceRegistryError):
    pass


def _require_non_empty_string(value: str | None, *, field_name: str) -> str:
    if value is None:
        raise InvalidCampaignRootError(f"{field_name} must be provided")
    normalized = value.strip()
    if not normalized:
        raise InvalidCampaignRootError(f"{field_name} must be non-empty")
    return normalized


def _normalize_campaign_id(value: str | None, *, root: Path) -> str:
    raw = value if value is not None else root.name
    normalized = _CAMPAIGN_ID_PATTERN.sub("-", raw.strip().lower()).strip("-_")
    if not normalized:
        raise InvalidCampaignRootError(
            "campaign_id must contain at least one alphanumeric character after normalization"
        )
    return normalized


def _optional_label(value: str | None, *, root: Path) -> str:
    if value is None:
        return root.name
    normalized = value.strip()
    if not normalized:
        raise InvalidCampaignRootError("label must be non-empty when provided")
    return normalized


def _load_json_object(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise InvalidCampaignRootError(f"missing required campaign file: {path.name}") from exc
    except json.JSONDecodeError as exc:
        raise InvalidCampaignRootError(f"{path.name} must contain valid JSON") from exc
    if not isinstance(payload, dict):
        raise InvalidCampaignRootError(f"{path.name} must contain a JSON object")
    return payload


def _atomic_write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_name(f".{path.name}.tmp-{time.time_ns()}")
    tmp_path.write_text(text, encoding="utf-8")
    tmp_path.replace(path)


def _validate_feature_flag(
    root: Path,
    *,
    flag_name: str,
    disabled_error: type[ServiceRegistryError],
    disabled_message: str,
) -> None:
    config_path = root / "bo_config.json"
    cfg = _load_json_object(config_path)
    raw_flags = cfg.get("feature_flags", {})
    if not isinstance(raw_flags, dict):
        raise InvalidCampaignRootError("bo_config.json feature_flags must be an object")
    enabled = raw_flags.get(flag_name, False)
    if not isinstance(enabled, bool):
        raise InvalidCampaignRootError(
            f"bo_config.json feature_flags.{flag_name} must be a boolean"
        )
    if not enabled:
        raise disabled_error(disabled_message)


def validate_campaign_root(path: str | Path) -> Path:
    root = Path(_require_non_empty_string(str(path), field_name="root_path")).expanduser().resolve()
    if not root.exists():
        raise InvalidCampaignRootError(f"campaign root does not exist: {root}")
    if not root.is_dir():
        raise InvalidCampaignRootError(f"campaign root must be a directory: {root}")

    missing = [name for name in _REQUIRED_CAMPAIGN_FILES if not (root / name).exists()]
    if missing:
        raise InvalidCampaignRootError(
            f"campaign root missing required files: {', '.join(sorted(missing))}"
        )

    _validate_feature_flag(
        root,
        flag_name="enable_service_api_preview",
        disabled_error=PreviewDisabledError,
        disabled_message=(
            "Campaign root is not service-enabled; set "
            "feature_flags.enable_service_api_preview=true before registration"
        ),
    )
    return root


def validate_dashboard_root(path: str | Path) -> Path:
    root = validate_campaign_root(path)
    _validate_feature_flag(
        root,
        flag_name="enable_dashboard_preview",
        disabled_error=DashboardPreviewDisabledError,
        disabled_message=(
            "Campaign root is not dashboard-enabled; set "
            "feature_flags.enable_dashboard_preview=true before using the preview dashboard"
        ),
    )
    return root


def load_registry_snapshot(path: Path) -> RegistrySnapshot:
    if not path.exists():
        return RegistrySnapshot()
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise RegistryStateError(f"registry file must contain valid JSON: {path}") from exc
    try:
        return RegistrySnapshot.model_validate(payload)
    except ValidationError as exc:
        raise RegistryStateError(f"registry file has invalid shape: {path}") from exc


def save_registry_snapshot(path: Path, snapshot: RegistrySnapshot) -> None:
    _atomic_write_text(path, json.dumps(snapshot.model_dump(mode="json"), indent=2))


class CampaignRegistry:
    def __init__(self, registry_file: Path) -> None:
        self.registry_file = registry_file
        self._write_lock = threading.Lock()

    def list_campaigns(self) -> list[CampaignRecord]:
        snapshot = load_registry_snapshot(self.registry_file)
        return sorted(snapshot.campaigns, key=lambda item: item.campaign_id)

    def get_campaign(self, campaign_id: str) -> CampaignRecord:
        target = _normalize_campaign_id(campaign_id, root=Path(campaign_id))
        for campaign in self.list_campaigns():
            if campaign.campaign_id == target:
                return campaign
        raise CampaignNotFoundError(f"campaign not found: {campaign_id}")

    def get_campaign_root(self, campaign_id: str) -> Path:
        return Path(self.get_campaign(campaign_id).root_path)

    def register_campaign(self, request: CampaignRegistrationRequest) -> CampaignRecord:
        root = validate_campaign_root(request.root_path)
        campaign_id = _normalize_campaign_id(request.campaign_id, root=root)
        label = _optional_label(request.label, root=root)

        with self._write_lock:
            snapshot = load_registry_snapshot(self.registry_file)
            existing_ids = {campaign.campaign_id for campaign in snapshot.campaigns}
            if campaign_id in existing_ids:
                raise CampaignConflictError(f"campaign_id already exists: {campaign_id}")

            root_text = str(root)
            existing_roots = {campaign.root_path for campaign in snapshot.campaigns}
            if root_text in existing_roots:
                raise CampaignConflictError(f"campaign root is already registered: {root_text}")

            record = CampaignRecord(
                campaign_id=campaign_id,
                root_path=root_text,
                label=label,
                created_at=time.time(),
            )
            snapshot.campaigns.append(record)
            snapshot.campaigns.sort(key=lambda item: item.campaign_id)
            save_registry_snapshot(self.registry_file, snapshot)
            return record
