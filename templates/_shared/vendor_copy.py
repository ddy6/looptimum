#!/usr/bin/env python3
"""Copy shared contract helpers/schemas into a standalone template directory."""

from __future__ import annotations

import argparse
import shutil
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "template_dir",
        help="Template directory to vendor into (for example: templates/bo_client_demo)",
    )
    parser.add_argument(
        "--rewrite-config-paths",
        action="store_true",
        help="Rewrite bo_config.json schema paths to local schemas/*.json after vendoring",
    )
    args = parser.parse_args()

    shared_root = Path(__file__).resolve().parent
    template_dir = Path(args.template_dir).resolve()
    if not template_dir.exists():
        raise SystemExit(f"Template directory not found: {template_dir}")

    (template_dir / "schemas").mkdir(parents=True, exist_ok=True)
    shutil.copy2(shared_root / "contract.py", template_dir / "contract.py")
    for name in [
        "ingest_payload.schema.json",
        "search_space.schema.json",
        "suggestion_payload.schema.json",
    ]:
        shutil.copy2(shared_root / "schemas" / name, template_dir / "schemas" / name)

    if args.rewrite_config_paths:
        cfg_path = template_dir / "bo_config.json"
        if cfg_path.exists():
            import json

            cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
            paths = cfg.setdefault("paths", {})
            paths["ingest_schema_file"] = "schemas/ingest_payload.schema.json"
            paths["search_space_schema_file"] = "schemas/search_space.schema.json"
            paths["suggestion_schema_file"] = "schemas/suggestion_payload.schema.json"
            cfg_path.write_text(json.dumps(cfg, indent=2), encoding="utf-8")

    print(f"Vendored shared contract helpers into {template_dir}")


if __name__ == "__main__":
    main()
