from __future__ import annotations

import sqlite3
import time
import uuid
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator, Protocol

from service.config import ServiceCoordinationConfig
from service.models import ServiceCoordinationMode
from service.registry import ServiceRegistryError


class CoordinationUnavailableError(ServiceRegistryError):
    pass


class CoordinationStateError(ServiceRegistryError):
    pass


class CoordinationBackend(Protocol):
    mode: ServiceCoordinationMode
    requires_campaign_opt_in: bool

    @contextmanager
    def acquire_campaign_lease(
        self,
        campaign_id: str,
        *,
        timeout_seconds: float | None,
        fail_fast: bool,
    ) -> Iterator[None]:
        yield


@dataclass(frozen=True, slots=True)
class FileLockCoordinationBackend:
    mode: ServiceCoordinationMode = "file_lock"
    requires_campaign_opt_in: bool = False

    @contextmanager
    def acquire_campaign_lease(
        self,
        campaign_id: str,
        *,
        timeout_seconds: float | None,
        fail_fast: bool,
    ) -> Iterator[None]:
        del campaign_id, timeout_seconds, fail_fast
        yield


@dataclass(frozen=True, slots=True)
class SQLiteLeaseCoordinationBackend:
    sqlite_file: Path
    lease_ttl_seconds: float
    mode: ServiceCoordinationMode = "sqlite_lease"
    requires_campaign_opt_in: bool = True

    def _connect(self) -> sqlite3.Connection:
        self.sqlite_file.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(
            self.sqlite_file,
            timeout=1.0,
            isolation_level=None,
            check_same_thread=False,
        )
        connection.execute("PRAGMA busy_timeout = 1000")
        return connection

    def _ensure_schema(self, connection: sqlite3.Connection) -> None:
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS campaign_leases (
                campaign_id TEXT PRIMARY KEY,
                owner_token TEXT NOT NULL,
                acquired_at REAL NOT NULL,
                expires_at REAL NOT NULL
            )
            """
        )

    def _try_acquire(self, campaign_id: str, owner_token: str, *, now: float) -> bool:
        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            self._ensure_schema(connection)
            row = connection.execute(
                "SELECT owner_token, expires_at FROM campaign_leases WHERE campaign_id = ?",
                (campaign_id,),
            ).fetchone()
            expires_at = now + self.lease_ttl_seconds
            if row is None:
                connection.execute(
                    """
                    INSERT INTO campaign_leases (campaign_id, owner_token, acquired_at, expires_at)
                    VALUES (?, ?, ?, ?)
                    """,
                    (campaign_id, owner_token, now, expires_at),
                )
                connection.commit()
                return True
            current_expires_at = float(row[1])
            if current_expires_at <= now:
                connection.execute(
                    """
                    UPDATE campaign_leases
                    SET owner_token = ?, acquired_at = ?, expires_at = ?
                    WHERE campaign_id = ?
                    """,
                    (owner_token, now, expires_at, campaign_id),
                )
                connection.commit()
                return True
            connection.rollback()
            return False
        except sqlite3.Error as exc:
            connection.rollback()
            raise CoordinationStateError(
                f"service coordination backend error for campaign {campaign_id!r}"
            ) from exc
        finally:
            connection.close()

    def _release(self, campaign_id: str, owner_token: str) -> None:
        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            self._ensure_schema(connection)
            connection.execute(
                "DELETE FROM campaign_leases WHERE campaign_id = ? AND owner_token = ?",
                (campaign_id, owner_token),
            )
            connection.commit()
        except sqlite3.Error as exc:
            connection.rollback()
            raise CoordinationStateError(
                f"service coordination backend error while releasing campaign {campaign_id!r}"
            ) from exc
        finally:
            connection.close()

    @contextmanager
    def acquire_campaign_lease(
        self,
        campaign_id: str,
        *,
        timeout_seconds: float | None,
        fail_fast: bool,
    ) -> Iterator[None]:
        owner_token = uuid.uuid4().hex
        effective_timeout = (
            0.0
            if fail_fast
            else (self.lease_ttl_seconds if timeout_seconds is None else timeout_seconds)
        )
        deadline = time.monotonic() + effective_timeout
        while True:
            now = time.time()
            if self._try_acquire(campaign_id, owner_token, now=now):
                break
            if time.monotonic() >= deadline:
                raise CoordinationUnavailableError(
                    f"service coordination lease unavailable for campaign {campaign_id!r}"
                )
            time.sleep(min(0.05, max(0.0, deadline - time.monotonic())))
        try:
            yield
        finally:
            self._release(campaign_id, owner_token)


def build_coordination_backend(
    config: ServiceCoordinationConfig,
) -> FileLockCoordinationBackend | SQLiteLeaseCoordinationBackend:
    if config.mode == "file_lock":
        return FileLockCoordinationBackend()
    return SQLiteLeaseCoordinationBackend(
        sqlite_file=config.sqlite_file,
        lease_ttl_seconds=config.lease_ttl_seconds,
    )
