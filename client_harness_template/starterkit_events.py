from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any, Iterable

from starterkit_models import EventLogCursor, StarterLifecycleEvent, StarterTopic

_EVENT_TO_TOPIC = {
    "suggestion_created": "suggested",
    "campaign_reset": "reset",
    "campaign_restored": "restore",
    "campaign_restore_failed": "failed",
}


def _require_object(value: Any, *, field_name: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError(f"{field_name} must be an object")
    return value


def _require_finite_float(value: Any, *, field_name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{field_name} must be numeric")
    normalized = float(value)
    if not math.isfinite(normalized):
        raise ValueError(f"{field_name} must be finite")
    return normalized


def _optional_int(value: Any, *, field_name: str) -> int | None:
    if value is None:
        return None
    if not isinstance(value, int) or isinstance(value, bool):
        raise ValueError(f"{field_name} must be an integer when present")
    return int(value)


def _optional_string(value: Any, *, field_name: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError(f"{field_name} must be a string when present")
    normalized = value.strip()
    return normalized or None


def load_event_log_cursor(path: Path) -> EventLogCursor:
    if not path.exists():
        return EventLogCursor()
    payload = json.loads(path.read_text(encoding="utf-8"))
    return EventLogCursor.from_payload(_require_object(payload, field_name="cursor"))


def save_event_log_cursor(path: Path, cursor: EventLogCursor) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(cursor.to_payload(), indent=2) + "\n", encoding="utf-8")
    return path


def _event_topic(payload: dict[str, Any]) -> StarterTopic | None:
    raw_event = _optional_string(payload.get("event"), field_name="event")
    if raw_event is None:
        raise ValueError("event must be present")
    if raw_event == "ingest_applied":
        status = _optional_string(payload.get("status"), field_name="status")
        if status is None:
            raise ValueError("ingest_applied requires status")
        return "ingested" if status == "ok" else "failed"
    mapped = _EVENT_TO_TOPIC.get(raw_event)
    if mapped is None:
        return None
    return mapped  # type: ignore[return-value]


def normalize_starter_event(
    payload: dict[str, Any],
    *,
    line_number: int,
    byte_offset: int,
) -> StarterLifecycleEvent | None:
    normalized_payload = _require_object(payload, field_name="event payload")
    topic = _event_topic(normalized_payload)
    if topic is None:
        return None

    source_event = _optional_string(normalized_payload.get("event"), field_name="event")
    if source_event is None:
        raise ValueError("event must be present")
    occurred_at = _require_finite_float(normalized_payload.get("timestamp"), field_name="timestamp")
    command = _optional_string(normalized_payload.get("command"), field_name="command")
    status = _optional_string(normalized_payload.get("status"), field_name="status")
    trial_id = _optional_int(normalized_payload.get("trial_id"), field_name="trial_id")
    event_id = f"{line_number}:{source_event}:{int(occurred_at * 1_000_000)}"

    return StarterLifecycleEvent(
        topic=topic,
        source_event=source_event,
        event_id=event_id,
        occurred_at=occurred_at,
        line_number=int(line_number),
        byte_offset=int(byte_offset),
        command=command,
        trial_id=trial_id,
        status=status,
        payload=dict(normalized_payload),
    )


def build_webhook_payload(event: StarterLifecycleEvent) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "topic": event.topic,
        "event_id": event.event_id,
        "source_event": event.source_event,
        "occurred_at": event.occurred_at,
        "cursor": {
            "line_number": event.line_number,
            "byte_offset": event.byte_offset,
        },
        "payload": dict(event.payload),
    }
    if event.command is not None:
        payload["command"] = event.command
    if event.trial_id is not None:
        payload["trial_id"] = event.trial_id
    if event.status is not None:
        payload["status"] = event.status
    return payload


def consume_starter_events(
    event_log_path: Path,
    *,
    cursor: EventLogCursor | None = None,
    topics: Iterable[StarterTopic] | None = None,
) -> tuple[list[StarterLifecycleEvent], EventLogCursor]:
    current_cursor = cursor or EventLogCursor()
    if not event_log_path.exists():
        return [], current_cursor

    file_size = event_log_path.stat().st_size
    if current_cursor.byte_offset > file_size:
        raise ValueError(
            "event log appears truncated before cursor position "
            f"(cursor.byte_offset={current_cursor.byte_offset}, size={file_size})"
        )

    topic_filter = set(topics) if topics is not None else None
    events: list[StarterLifecycleEvent] = []
    line_number = current_cursor.line_number
    next_offset = current_cursor.byte_offset

    with event_log_path.open("rb") as handle:
        handle.seek(current_cursor.byte_offset)
        while True:
            raw_line = handle.readline()
            if raw_line == b"":
                break
            next_offset = handle.tell()
            line_number += 1
            line = raw_line.decode("utf-8").strip()
            if not line:
                continue
            try:
                payload = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(f"event_log line {line_number} invalid JSON: {exc}") from exc
            event = normalize_starter_event(
                _require_object(payload, field_name=f"event_log line {line_number}"),
                line_number=line_number,
                byte_offset=next_offset,
            )
            if event is None:
                continue
            if topic_filter is not None and event.topic not in topic_filter:
                continue
            events.append(event)

    return events, EventLogCursor(line_number=line_number, byte_offset=next_offset)
