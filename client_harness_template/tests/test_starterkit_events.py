from __future__ import annotations

import importlib
import json
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
HARNESS_DIR = REPO_ROOT / "client_harness_template"
if str(HARNESS_DIR) not in sys.path:
    sys.path.insert(0, str(HARNESS_DIR))

starterkit_events = importlib.import_module("starterkit_events")
starterkit_models = importlib.import_module("starterkit_models")
EventLogCursor = starterkit_models.EventLogCursor


def _write_event_log(path: Path, rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "".join(json.dumps(row, sort_keys=True) + "\n" for row in rows),
        encoding="utf-8",
    )


def test_consume_starter_events_maps_runtime_events_to_topics(tmp_path: Path) -> None:
    event_log = tmp_path / "state" / "event_log.jsonl"
    _write_event_log(
        event_log,
        [
            {"event": "lock_acquired", "timestamp": 10.0, "command": "suggest"},
            {"event": "suggestion_created", "timestamp": 11.0, "trial_id": 1},
            {
                "event": "ingest_applied",
                "timestamp": 12.0,
                "trial_id": 1,
                "status": "ok",
                "command": "ingest",
            },
            {
                "event": "ingest_applied",
                "timestamp": 13.0,
                "trial_id": 2,
                "status": "timeout",
                "command": "ingest",
            },
            {"event": "campaign_reset", "timestamp": 14.0, "archive_enabled": True},
            {"event": "campaign_restored", "timestamp": 15.0, "archive_id": "reset-123"},
            {"event": "campaign_restore_failed", "timestamp": 16.0, "error": "bad archive"},
        ],
    )

    events, cursor = starterkit_events.consume_starter_events(event_log)

    assert [event.topic for event in events] == [
        "suggested",
        "ingested",
        "failed",
        "reset",
        "restore",
        "failed",
    ]
    assert [event.source_event for event in events] == [
        "suggestion_created",
        "ingest_applied",
        "ingest_applied",
        "campaign_reset",
        "campaign_restored",
        "campaign_restore_failed",
    ]
    assert events[0].trial_id == 1
    assert events[1].status == "ok"
    assert events[2].status == "timeout"
    assert events[-1].trial_id is None
    assert cursor.line_number == 7
    assert cursor.byte_offset == event_log.stat().st_size


def test_consume_starter_events_supports_cursor_replay(tmp_path: Path) -> None:
    event_log = tmp_path / "state" / "event_log.jsonl"
    _write_event_log(
        event_log,
        [
            {"event": "suggestion_created", "timestamp": 20.0, "trial_id": 1},
            {
                "event": "ingest_applied",
                "timestamp": 21.0,
                "trial_id": 1,
                "status": "ok",
                "command": "ingest",
            },
        ],
    )

    first_events, first_cursor = starterkit_events.consume_starter_events(event_log)
    assert [event.topic for event in first_events] == ["suggested", "ingested"]

    with event_log.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps({"event": "campaign_reset", "timestamp": 22.0}) + "\n")

    second_events, second_cursor = starterkit_events.consume_starter_events(
        event_log,
        cursor=first_cursor,
    )
    assert [event.topic for event in second_events] == ["reset"]
    assert second_cursor.line_number == 3
    assert second_cursor.byte_offset == event_log.stat().st_size


def test_consume_starter_events_rejects_truncated_log_before_cursor(tmp_path: Path) -> None:
    event_log = tmp_path / "state" / "event_log.jsonl"
    _write_event_log(
        event_log,
        [{"event": "suggestion_created", "timestamp": 30.0, "trial_id": 1}],
    )

    cursor = EventLogCursor(line_number=5, byte_offset=event_log.stat().st_size + 10)
    with pytest.raises(ValueError, match="event log appears truncated before cursor position"):
        starterkit_events.consume_starter_events(event_log, cursor=cursor)


def test_cursor_round_trip_and_webhook_payload_shape(tmp_path: Path) -> None:
    cursor_path = tmp_path / "starterkit_cursor.json"
    cursor = EventLogCursor(line_number=4, byte_offset=128)

    starterkit_events.save_event_log_cursor(cursor_path, cursor)
    loaded = starterkit_events.load_event_log_cursor(cursor_path)

    assert loaded == cursor

    event = starterkit_events.normalize_starter_event(
        {
            "event": "ingest_applied",
            "timestamp": 42.0,
            "trial_id": 7,
            "status": "failed",
            "command": "ingest",
            "terminal_reason": "solver diverged",
        },
        line_number=4,
        byte_offset=128,
    )
    assert event is not None
    payload = starterkit_events.build_webhook_payload(event)

    assert payload["topic"] == "failed"
    assert payload["event_id"] == event.event_id
    assert payload["trial_id"] == 7
    assert payload["status"] == "failed"
    assert payload["command"] == "ingest"
    assert payload["cursor"] == {"line_number": 4, "byte_offset": 128}
    assert payload["payload"]["terminal_reason"] == "solver diverged"


def test_consume_starter_events_supports_topic_filter(tmp_path: Path) -> None:
    event_log = tmp_path / "state" / "event_log.jsonl"
    _write_event_log(
        event_log,
        [
            {"event": "suggestion_created", "timestamp": 50.0, "trial_id": 1},
            {
                "event": "ingest_applied",
                "timestamp": 51.0,
                "trial_id": 1,
                "status": "ok",
                "command": "ingest",
            },
            {"event": "campaign_reset", "timestamp": 52.0},
        ],
    )

    events, _ = starterkit_events.consume_starter_events(
        event_log,
        topics=["suggested", "restore"],
    )
    assert [event.topic for event in events] == ["suggested"]
