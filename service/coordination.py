from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from service.config import ServiceCoordinationConfig
from service.models import ServiceCoordinationMode


class CoordinationBackend(Protocol):
    mode: ServiceCoordinationMode
    requires_campaign_opt_in: bool


@dataclass(frozen=True, slots=True)
class FileLockCoordinationBackend:
    mode: ServiceCoordinationMode = "file_lock"
    requires_campaign_opt_in: bool = False


@dataclass(frozen=True, slots=True)
class SQLiteLeaseCoordinationBackend:
    sqlite_file: Path
    lease_ttl_seconds: float
    mode: ServiceCoordinationMode = "sqlite_lease"
    requires_campaign_opt_in: bool = True


def build_coordination_backend(
    config: ServiceCoordinationConfig,
) -> FileLockCoordinationBackend | SQLiteLeaseCoordinationBackend:
    if config.mode == "file_lock":
        return FileLockCoordinationBackend()
    return SQLiteLeaseCoordinationBackend(
        sqlite_file=config.sqlite_file,
        lease_ttl_seconds=config.lease_ttl_seconds,
    )
