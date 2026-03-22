from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

StarterTopic = Literal["suggested", "ingested", "failed", "reset", "restore"]

_VALID_STARTER_TOPICS: tuple[StarterTopic, ...] = (
    "suggested",
    "ingested",
    "failed",
    "reset",
    "restore",
)


def valid_starter_topics() -> tuple[StarterTopic, ...]:
    return _VALID_STARTER_TOPICS


@dataclass(frozen=True)
class StarterWebhookConfig:
    enabled: bool
    target_url: str | None
    timeout_seconds: float
    topics: tuple[StarterTopic, ...]
    headers: dict[str, str]
    secret_env_var: str | None = None


@dataclass(frozen=True)
class StarterKitConfig:
    event_log_file: Path
    cursor_file: Path
    webhook: StarterWebhookConfig | None = None


@dataclass(frozen=True)
class EventLogCursor:
    line_number: int = 0
    byte_offset: int = 0

    def to_payload(self) -> dict[str, Any]:
        return {
            "line_number": int(self.line_number),
            "byte_offset": int(self.byte_offset),
        }

    @classmethod
    def from_payload(cls, payload: dict[str, Any]) -> EventLogCursor:
        line_number = payload.get("line_number", 0)
        byte_offset = payload.get("byte_offset", 0)
        if not isinstance(line_number, int) or isinstance(line_number, bool) or line_number < 0:
            raise ValueError("cursor.line_number must be an integer >= 0")
        if not isinstance(byte_offset, int) or isinstance(byte_offset, bool) or byte_offset < 0:
            raise ValueError("cursor.byte_offset must be an integer >= 0")
        return cls(line_number=int(line_number), byte_offset=int(byte_offset))


@dataclass(frozen=True)
class StarterLifecycleEvent:
    topic: StarterTopic
    source_event: str
    event_id: str
    occurred_at: float
    line_number: int
    byte_offset: int
    command: str | None
    trial_id: int | None
    status: str | None
    payload: dict[str, Any]
