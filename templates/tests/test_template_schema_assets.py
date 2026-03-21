from __future__ import annotations

import json
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SHARED_SCHEMAS = REPO_ROOT / "templates" / "_shared" / "schemas"
TEMPLATES = ("bo_client", "bo_client_demo", "bo_client_full")
CANONICAL_FILES = (
    "constraints.schema.json",
    "ingest_payload.schema.json",
    "search_space.schema.json",
    "suggestion_payload.schema.json",
)
FEATURE_FLAG_KEYS = (
    "enable_botorch_gp",
    "fallback_to_proxy_if_unavailable",
    "enable_service_api_preview",
    "enable_dashboard_preview",
    "enable_auth_preview",
)


def _load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def test_template_schema_dirs_include_canonical_files_only() -> None:
    for template in TEMPLATES:
        schema_dir = REPO_ROOT / "templates" / template / "schemas"
        for name in CANONICAL_FILES:
            assert (schema_dir / name).exists(), f"missing {schema_dir / name}"


def test_template_canonical_schema_files_match_shared_content() -> None:
    shared = {name: _load_json(SHARED_SCHEMAS / name) for name in CANONICAL_FILES}

    for template in TEMPLATES:
        schema_dir = REPO_ROOT / "templates" / template / "schemas"
        for name in CANONICAL_FILES:
            assert _load_json(schema_dir / name) == shared[name]


def test_template_bo_configs_share_feature_flag_shape() -> None:
    for template in TEMPLATES:
        cfg_path = REPO_ROOT / "templates" / template / "bo_config.json"
        cfg = _load_json(cfg_path)
        flags = cfg.get("feature_flags")
        assert isinstance(flags, dict), f"missing feature_flags in {cfg_path}"
        assert tuple(flags.keys()) == FEATURE_FLAG_KEYS
        assert flags["enable_service_api_preview"] is False
        assert flags["enable_dashboard_preview"] is False
        assert flags["enable_auth_preview"] is False


def test_template_bo_configs_include_constraints_schema_path() -> None:
    for template in TEMPLATES:
        cfg_path = REPO_ROOT / "templates" / template / "bo_config.json"
        cfg = _load_json(cfg_path)
        paths = cfg.get("paths")
        assert isinstance(paths, dict), f"missing paths in {cfg_path}"
        assert paths.get("constraints_schema_file") == "../_shared/schemas/constraints.schema.json"


def test_search_space_schema_exposes_workstream1_parameter_fields() -> None:
    schema = _load_json(SHARED_SCHEMAS / "search_space.schema.json")
    item_properties = schema["properties"]["parameters"]["items"]["properties"]
    assert item_properties["type"]["enum"] == ["float", "int", "bool", "categorical"]
    assert "choices" in item_properties
    assert "scale" in item_properties
    assert "when" in item_properties


def test_constraints_schema_exposes_workstream3_rule_collections() -> None:
    schema = _load_json(SHARED_SCHEMAS / "constraints.schema.json")
    properties = schema["properties"]
    assert set(properties) == {
        "bound_tightening",
        "linear_inequalities",
        "forbidden_combinations",
    }
    assert properties["linear_inequalities"]["items"]["properties"]["operator"]["enum"] == [
        "<=",
        ">=",
    ]
