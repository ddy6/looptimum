from __future__ import annotations

import json
from pathlib import Path

import pytest

from service.models import CampaignRegistrationRequest
from service.registry import (
    CampaignConflictError,
    CampaignNotFoundError,
    CampaignRegistry,
    PreviewDisabledError,
)


def _write_campaign_root(root: Path, *, service_enabled: bool = True) -> None:
    root.mkdir(parents=True, exist_ok=True)
    (root / "run_bo.py").write_text("# preview runtime entrypoint\n", encoding="utf-8")
    (root / "parameter_space.json").write_text(
        json.dumps(
            {"params": [{"name": "x", "type": "float", "bounds": [0.0, 1.0]}], "version": 2}
        ),
        encoding="utf-8",
    )
    (root / "objective_schema.json").write_text(
        json.dumps(
            {
                "primary_objective": {"name": "loss", "goal": "minimize"},
            }
        ),
        encoding="utf-8",
    )
    (root / "bo_config.json").write_text(
        json.dumps(
            {
                "feature_flags": {
                    "enable_service_api_preview": service_enabled,
                }
            },
            indent=2,
        ),
        encoding="utf-8",
    )


def test_register_campaign_derives_id_and_persists_minimal_registry_record(tmp_path: Path) -> None:
    registry_file = tmp_path / "service_state" / "campaign_registry.json"
    campaign_root = tmp_path / "campaigns" / "Alpha Campaign"
    _write_campaign_root(campaign_root)
    registry = CampaignRegistry(registry_file)

    record = registry.register_campaign(
        CampaignRegistrationRequest(root_path=str(campaign_root), label="Alpha")
    )

    assert record.campaign_id == "alpha-campaign"
    assert record.label == "Alpha"
    assert record.root_path == str(campaign_root.resolve())

    stored = json.loads(registry_file.read_text(encoding="utf-8"))
    assert stored["schema_version"] == "0.1.0-preview"
    assert stored["campaigns"] == [
        {
            "campaign_id": "alpha-campaign",
            "root_path": str(campaign_root.resolve()),
            "label": "Alpha",
            "created_at": record.created_at,
        }
    ]


def test_register_campaign_rejects_preview_disabled_root(tmp_path: Path) -> None:
    registry = CampaignRegistry(tmp_path / "service_state" / "campaign_registry.json")
    campaign_root = tmp_path / "campaigns" / "disabled"
    _write_campaign_root(campaign_root, service_enabled=False)

    with pytest.raises(PreviewDisabledError, match="feature_flags.enable_service_api_preview=true"):
        registry.register_campaign(CampaignRegistrationRequest(root_path=str(campaign_root)))


def test_register_campaign_rejects_duplicate_campaign_id_and_root(tmp_path: Path) -> None:
    registry = CampaignRegistry(tmp_path / "service_state" / "campaign_registry.json")
    first_root = tmp_path / "campaigns" / "first"
    second_root = tmp_path / "campaigns" / "second"
    _write_campaign_root(first_root)
    _write_campaign_root(second_root)

    registry.register_campaign(
        CampaignRegistrationRequest(root_path=str(first_root), campaign_id="shared-id")
    )

    with pytest.raises(CampaignConflictError, match="campaign_id already exists"):
        registry.register_campaign(
            CampaignRegistrationRequest(root_path=str(second_root), campaign_id="shared-id")
        )

    with pytest.raises(CampaignConflictError, match="campaign root is already registered"):
        registry.register_campaign(CampaignRegistrationRequest(root_path=str(first_root)))


def test_get_campaign_raises_for_missing_campaign_id(tmp_path: Path) -> None:
    registry = CampaignRegistry(tmp_path / "service_state" / "campaign_registry.json")

    with pytest.raises(CampaignNotFoundError, match="campaign not found"):
        registry.get_campaign("missing")
