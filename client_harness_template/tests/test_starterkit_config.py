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

starterkit_config = importlib.import_module("starterkit_config")


def _write_config(
    path: Path,
    *,
    include_webhook: bool = True,
    enabled: bool = True,
) -> None:
    payload: dict[str, object] = {
        "runtime": {
            "event_log_file": "campaign_state/event_log.jsonl",
        }
    }
    if include_webhook:
        payload["webhook"] = {
            "enabled": enabled,
            "target_url": "https://hooks.example.test/looptimum" if enabled else None,
            "timeout_seconds": 15,
            "topics": ["suggested", "failed", "restore"],
            "headers": {"X-Client": "starter"},
            "secret_env_var": "LOOPTIMUM_WEBHOOK_SECRET",
        }
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def test_load_starterkit_config_from_explicit_path(tmp_path: Path) -> None:
    config_path = tmp_path / "starterkit_config.json"
    _write_config(config_path)

    config = starterkit_config.load_starterkit_config(config_path)

    assert config.event_log_file == (tmp_path / "campaign_state" / "event_log.jsonl").resolve()
    assert config.cursor_file == (tmp_path / "campaign_state" / "starterkit_cursor.json").resolve()
    assert config.webhook is not None
    assert config.webhook.enabled is True
    assert config.webhook.target_url == "https://hooks.example.test/looptimum"
    assert config.webhook.timeout_seconds == 15.0
    assert config.webhook.topics == ("suggested", "failed", "restore")
    assert config.webhook.headers == {"X-Client": "starter"}
    assert config.webhook.secret_env_var == "LOOPTIMUM_WEBHOOK_SECRET"


def test_load_starterkit_config_uses_env_path_when_arg_is_omitted(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config_path = tmp_path / "starterkit_config_env.json"
    _write_config(config_path, include_webhook=False)
    monkeypatch.setenv(starterkit_config.STARTERKIT_CONFIG_ENV, str(config_path))

    resolved = starterkit_config.resolve_starterkit_config_path()
    config = starterkit_config.load_starterkit_config()

    assert resolved == config_path.resolve()
    assert config.webhook is None


def test_load_starterkit_config_allows_disabled_webhook_without_target(tmp_path: Path) -> None:
    config_path = tmp_path / "starterkit_config_disabled.json"
    _write_config(config_path, include_webhook=True, enabled=False)

    config = starterkit_config.load_starterkit_config(config_path)

    assert config.webhook is not None
    assert config.webhook.enabled is False
    assert config.webhook.target_url is None


def test_load_starterkit_config_rejects_invalid_topic(tmp_path: Path) -> None:
    config_path = tmp_path / "starterkit_config_invalid_topic.json"
    _write_config(config_path)
    payload = json.loads(config_path.read_text(encoding="utf-8"))
    payload["webhook"]["topics"] = ["suggested", "paused"]
    config_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    with pytest.raises(ValueError, match="webhook.topics must stay within"):
        starterkit_config.load_starterkit_config(config_path)


def test_resolve_starterkit_config_requires_explicit_path_or_env(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv(starterkit_config.STARTERKIT_CONFIG_ENV, raising=False)

    with pytest.raises(ValueError, match="Starter-kit integration requires a config path"):
        starterkit_config.resolve_starterkit_config_path()
