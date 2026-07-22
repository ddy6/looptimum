#!/usr/bin/env python3
"""Create a self-contained portable copy of a Looptimum controller template."""

from __future__ import annotations

import argparse
import json
import shutil
from collections.abc import Callable
from pathlib import Path

RUNTIME_MODULES = (
    "contract.py",
    "constraints.py",
    "objectives.py",
    "archives.py",
    "governance.py",
    "runtime.py",
    "search_space.py",
    "observations_io.py",
)
VENDORED_SHARED_RELATIVE_DIR = Path("vendor") / "looptimum_shared"
VENDORED_SCHEMA_RELATIVE_DIR = VENDORED_SHARED_RELATIVE_DIR / "schemas"
RUNTIME_ARTIFACTS = frozenset(
    {
        "state/bo_state.json",
        "state/observations.csv",
        "state/acquisition_log.jsonl",
        "state/event_log.jsonl",
        "state/.looptimum.lock",
        "state/report.json",
        "state/report.md",
        "state/trials",
        "state/reset_archives",
        "state/import_reports",
        "examples/_demo_result.json",
    }
)
_CACHE_NAMES = frozenset({"__pycache__", ".pytest_cache", ".ruff_cache", ".mypy_cache"})


def _schema_filenames(shared_root: Path) -> tuple[str, ...]:
    schemas = tuple(sorted(path.name for path in (shared_root / "schemas").glob("*.schema.json")))
    if not schemas:
        raise SystemExit(f"No shared schema files found under {shared_root / 'schemas'}")
    return schemas


def _template_copy_ignore(template_dir: Path) -> Callable[[str, list[str]], set[str]]:
    def ignore(directory: str, names: list[str]) -> set[str]:
        ignored: set[str] = set()
        relative_dir = Path(directory).resolve().relative_to(template_dir)
        for name in names:
            relative_path = (relative_dir / name).as_posix()
            if name in _CACHE_NAMES or name.endswith((".pyc", ".pyo")):
                ignored.add(name)
            elif relative_path in RUNTIME_ARTIFACTS:
                ignored.add(name)
        return ignored

    return ignore


def _require_empty_destination(destination: Path) -> None:
    if destination.exists() and not destination.is_dir():
        raise SystemExit(f"Destination exists and is not a directory: {destination}")
    if destination.exists() and any(destination.iterdir()):
        raise SystemExit(f"Destination must be empty: {destination}")


def _vendor_runtime(
    shared_root: Path, destination: Path, schema_filenames: tuple[str, ...]
) -> None:
    vendor_root = destination / VENDORED_SHARED_RELATIVE_DIR
    vendor_schemas = destination / VENDORED_SCHEMA_RELATIVE_DIR
    vendor_schemas.mkdir(parents=True, exist_ok=True)

    for filename in RUNTIME_MODULES:
        source = shared_root / filename
        if not source.is_file():
            raise SystemExit(f"Required shared runtime module not found: {source}")
        shutil.copy2(source, vendor_root / filename)

    for filename in schema_filenames:
        shutil.copy2(shared_root / "schemas" / filename, vendor_schemas / filename)


def _rewrite_controller_paths(controller_path: Path) -> None:
    source = controller_path.read_text(encoding="utf-8")
    loader_path = 'module_path = _TEMPLATE_DIR.parent / "_shared" / filename'
    vendored_loader_path = 'module_path = _TEMPLATE_DIR / "vendor" / "looptimum_shared" / filename'
    if loader_path not in source:
        raise SystemExit(f"Controller loader path not found in {controller_path}")

    rewritten = source.replace(loader_path, vendored_loader_path)
    rewritten = rewritten.replace("../_shared/schemas/", "vendor/looptimum_shared/schemas/")
    controller_path.write_text(rewritten, encoding="utf-8")


def _rewrite_config_schema_paths(config_path: Path, schema_filenames: tuple[str, ...]) -> None:
    if not config_path.is_file():
        raise SystemExit(f"Controller config not found: {config_path}")

    cfg = json.loads(config_path.read_text(encoding="utf-8"))
    paths = cfg.get("paths")
    if not isinstance(paths, dict):
        raise SystemExit(f"Config paths must be an object: {config_path}")

    schema_keys = [key for key in paths if key.endswith("_schema_file")]
    if not schema_keys:
        raise SystemExit(f"No schema paths found in {config_path}")

    available_schemas = set(schema_filenames)
    for key in schema_keys:
        raw_path = paths[key]
        if not isinstance(raw_path, str) or not raw_path:
            raise SystemExit(f"Config schema path must be a non-empty string: paths.{key}")
        schema_filename = Path(raw_path).name
        if schema_filename not in available_schemas:
            raise SystemExit(
                f"Config schema path does not name a vendored shared schema: paths.{key}={raw_path!r}"
            )
        paths[key] = (VENDORED_SCHEMA_RELATIVE_DIR / schema_filename).as_posix()

    config_path.write_text(json.dumps(cfg, indent=2) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("template_dir", type=Path, help="Source controller template directory")
    parser.add_argument(
        "destination_dir", type=Path, help="Empty destination for the portable copy"
    )
    args = parser.parse_args()

    shared_root = Path(__file__).resolve().parent
    template_dir = args.template_dir.resolve()
    destination_dir = args.destination_dir.resolve()
    if not template_dir.is_dir():
        raise SystemExit(f"Template directory not found: {template_dir}")
    if not (template_dir / "run_bo.py").is_file():
        raise SystemExit(f"Template does not contain run_bo.py: {template_dir}")
    if destination_dir == template_dir or template_dir in destination_dir.parents:
        raise SystemExit("Destination must not be the template directory or one of its children")

    _require_empty_destination(destination_dir)
    schema_filenames = _schema_filenames(shared_root)
    destination_dir.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(
        template_dir,
        destination_dir,
        dirs_exist_ok=True,
        ignore=_template_copy_ignore(template_dir),
    )
    _vendor_runtime(shared_root, destination_dir, schema_filenames)
    _rewrite_controller_paths(destination_dir / "run_bo.py")
    _rewrite_config_schema_paths(destination_dir / "bo_config.json", schema_filenames)

    print(f"Created portable Looptimum controller at {destination_dir}")


if __name__ == "__main__":
    main()
