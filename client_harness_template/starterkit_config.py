from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from starterkit_models import (
    StarterKitConfig,
    StarterTopic,
    StarterWebhookConfig,
    valid_starter_topics,
)

STARTERKIT_CONFIG_ENV = "LOOPTIMUM_STARTER_KIT_CONFIG"
DEFAULT_WEBHOOK_TIMEOUT_SECONDS = 10.0


def _require_object(value: Any, *, field_name: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError(f"{field_name} must be an object")
    return value


def _require_non_empty_string(value: Any, *, field_name: str) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{field_name} must be a string")
    normalized = value.strip()
    if not normalized:
        raise ValueError(f"{field_name} must be non-empty")
    return normalized


def _optional_string(value: Any, *, field_name: str) -> str | None:
    if value is None:
        return None
    return _require_non_empty_string(value, field_name=field_name)


def _positive_float(value: Any, *, field_name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{field_name} must be numeric")
    normalized = float(value)
    if normalized <= 0.0:
        raise ValueError(f"{field_name} must be > 0")
    return normalized


def _resolve_path(value: Any, *, field_name: str, base_dir: Path) -> Path:
    raw = Path(_require_non_empty_string(value, field_name=field_name))
    if not raw.is_absolute():
        raw = (base_dir / raw).resolve()
    else:
        raw = raw.resolve()
    return raw


def _normalize_webhook_topics(value: Any) -> tuple[StarterTopic, ...]:
    if value is None:
        return valid_starter_topics()
    if not isinstance(value, list) or not value:
        raise ValueError("webhook.topics must be a non-empty list or null")
    allowed = set(valid_starter_topics())
    topics: list[StarterTopic] = []
    seen: set[str] = set()
    for index, raw in enumerate(value):
        if not isinstance(raw, str):
            raise ValueError(f"webhook.topics[{index}] must be a string")
        normalized = raw.strip().lower()
        if normalized not in allowed:
            raise ValueError(f"webhook.topics must stay within {list(valid_starter_topics())}")
        if normalized in seen:
            raise ValueError("webhook.topics must not contain duplicates")
        seen.add(normalized)
        topics.append(normalized)  # type: ignore[arg-type]
    return tuple(topics)


def _normalize_webhook_headers(value: Any) -> dict[str, str]:
    if value is None:
        return {}
    headers = _require_object(value, field_name="webhook.headers")
    normalized: dict[str, str] = {}
    for key, raw_value in headers.items():
        header_name = _require_non_empty_string(key, field_name="webhook.headers key")
        header_value = _require_non_empty_string(
            raw_value, field_name=f"webhook.headers[{header_name!r}]"
        )
        normalized[header_name] = header_value
    return normalized


def resolve_starterkit_config_path(path: str | Path | None = None) -> Path:
    raw = str(path) if path is not None else os.environ.get(STARTERKIT_CONFIG_ENV)
    if raw is None or not raw.strip():
        raise ValueError(
            "Starter-kit integration requires a config path. "
            f"Provide an explicit path or set {STARTERKIT_CONFIG_ENV}."
        )
    resolved = Path(raw).expanduser().resolve()
    if not resolved.exists():
        raise ValueError(f"Starter-kit config file not found: {resolved}")
    return resolved


def load_starterkit_config(path: str | Path | None = None) -> StarterKitConfig:
    config_path = resolve_starterkit_config_path(path)
    payload = json.loads(config_path.read_text(encoding="utf-8"))
    data = _require_object(payload, field_name="starter-kit config")
    base_dir = config_path.parent

    extra_keys = sorted(set(data) - {"runtime", "webhook"})
    if extra_keys:
        raise ValueError(f"starter-kit config includes unsupported keys {extra_keys}")

    runtime = _require_object(data.get("runtime"), field_name="runtime")
    runtime_extra_keys = sorted(set(runtime) - {"event_log_file", "cursor_file"})
    if runtime_extra_keys:
        raise ValueError(f"runtime includes unsupported keys {runtime_extra_keys}")

    event_log_file = _resolve_path(
        runtime.get("event_log_file"),
        field_name="runtime.event_log_file",
        base_dir=base_dir,
    )
    cursor_raw = runtime.get("cursor_file")
    cursor_file = (
        _resolve_path(cursor_raw, field_name="runtime.cursor_file", base_dir=base_dir)
        if cursor_raw is not None
        else event_log_file.with_name("starterkit_cursor.json")
    )

    webhook_payload = data.get("webhook")
    webhook: StarterWebhookConfig | None = None
    if webhook_payload is not None:
        webhook_obj = _require_object(webhook_payload, field_name="webhook")
        webhook_extra_keys = sorted(
            set(webhook_obj)
            - {"enabled", "target_url", "timeout_seconds", "topics", "headers", "secret_env_var"}
        )
        if webhook_extra_keys:
            raise ValueError(f"webhook includes unsupported keys {webhook_extra_keys}")
        enabled = webhook_obj.get("enabled", True)
        if not isinstance(enabled, bool):
            raise ValueError("webhook.enabled must be a boolean")
        target_url = _optional_string(
            webhook_obj.get("target_url"), field_name="webhook.target_url"
        )
        if enabled and target_url is None:
            raise ValueError("webhook.target_url must be set when webhook.enabled is true")
        webhook = StarterWebhookConfig(
            enabled=enabled,
            target_url=target_url,
            timeout_seconds=_positive_float(
                webhook_obj.get("timeout_seconds", DEFAULT_WEBHOOK_TIMEOUT_SECONDS),
                field_name="webhook.timeout_seconds",
            ),
            topics=_normalize_webhook_topics(webhook_obj.get("topics")),
            headers=_normalize_webhook_headers(webhook_obj.get("headers")),
            secret_env_var=_optional_string(
                webhook_obj.get("secret_env_var"),
                field_name="webhook.secret_env_var",
            ),
        )

    return StarterKitConfig(
        event_log_file=event_log_file,
        cursor_file=cursor_file,
        webhook=webhook,
    )
