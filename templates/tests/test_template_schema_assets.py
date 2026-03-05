from __future__ import annotations

import json
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SHARED_SCHEMAS = REPO_ROOT / "templates" / "_shared" / "schemas"
TEMPLATES = ("bo_client", "bo_client_demo", "bo_client_full")
CANONICAL_FILES = (
    "ingest_payload.schema.json",
    "search_space.schema.json",
    "suggestion_payload.schema.json",
)


def _load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def test_template_schema_dirs_include_canonical_and_alias_files() -> None:
    for template in TEMPLATES:
        schema_dir = REPO_ROOT / "templates" / template / "schemas"
        for name in (*CANONICAL_FILES, "result_payload.schema.json"):
            assert (schema_dir / name).exists(), f"missing {schema_dir / name}"


def test_template_canonical_schema_files_match_shared_content() -> None:
    shared = {name: _load_json(SHARED_SCHEMAS / name) for name in CANONICAL_FILES}

    for template in TEMPLATES:
        schema_dir = REPO_ROOT / "templates" / template / "schemas"
        for name in CANONICAL_FILES:
            assert _load_json(schema_dir / name) == shared[name]


def test_result_payload_alias_schema_matches_ingest_shape_with_deprecation_note() -> None:
    for template in TEMPLATES:
        schema_dir = REPO_ROOT / "templates" / template / "schemas"
        alias = _load_json(schema_dir / "result_payload.schema.json")
        ingest = _load_json(schema_dir / "ingest_payload.schema.json")

        assert alias["required"] == ingest["required"]
        assert alias["properties"] == ingest["properties"]
        assert alias.get("x-deprecated-alias-for") == "ingest_payload.schema.json"

        description = alias.get("description")
        assert isinstance(description, str)
        assert "Scheduled for removal in v0.4.0" in description
