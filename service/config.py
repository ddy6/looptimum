from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

SERVICE_REGISTRY_FILE_ENV = "LOOPTIMUM_SERVICE_REGISTRY_FILE"
DEFAULT_SERVICE_REGISTRY_FILE = "service_state/campaign_registry.json"


@dataclass(frozen=True, slots=True)
class ServiceConfig:
    registry_file: Path


def resolve_registry_file(path: str | Path | None = None) -> Path:
    raw = str(path) if path is not None else os.environ.get(SERVICE_REGISTRY_FILE_ENV)
    selected = raw if raw and raw.strip() else DEFAULT_SERVICE_REGISTRY_FILE
    candidate = Path(selected).expanduser()
    if candidate.is_absolute():
        return candidate.resolve()
    return (Path.cwd() / candidate).resolve()


def build_service_config(path: str | Path | None = None) -> ServiceConfig:
    return ServiceConfig(registry_file=resolve_registry_file(path))
