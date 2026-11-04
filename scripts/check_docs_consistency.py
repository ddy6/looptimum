#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
import tomllib
from pathlib import Path

from check_internal_links import (
    LINK_PATTERN,
    _is_external_target,
    _normalize_target,
    _resolve_target_path,
)

# Each topic has a canonical owner; a pointer page need not repeat its inventory.
REQUIRED_LINKS: dict[str, tuple[str, ...]] = {
    "README.md": (
        "quickstart/README.md",
        "docs/index.md",
        "docs/quick-reference.md",
        "templates/README.md",
        "benchmarks/README.md",
        "docs/stability-guarantees.md",
    ),
    "docs/README.md": ("docs/index.md",),
    "docs/index.md": (
        "quickstart/README.md",
        "docs/integration-guide.md",
        "docs/search-space.md",
        "docs/how-it-works.md",
        "docs/recovery-playbook.md",
        "docs/ax-installation.md",
        "docs/ax-support-matrix.md",
        "docs/type-safety.md",
        "docs/release-guide.md",
        "docs/examples/README.md",
        "reports/README.md",
    ),
    "quickstart/README.md": (
        "docs/packages.md",
        "docs/integration-guide.md",
        "docs/recovery-playbook.md",
        "docs/ax-installation.md",
        "quickstart/etl-pipeline-knob-tuning.md",
    ),
    "templates/README.md": (
        "quickstart/README.md",
        "docs/quick-reference.md",
        "docs/ax-support-matrix.md",
    ),
    "client_harness_template/README.md": (
        "docs/integration-guide.md",
        "client_harness_template/README_INTEGRATION.md",
    ),
    "docs/packages.md": (
        "quickstart/README.md",
        "docs/service-api-preview.md",
        "docs/ax-installation.md",
    ),
}
REQUIRED_FILES = tuple(
    sorted(
        {
            *REQUIRED_LINKS,
            *(target for targets in REQUIRED_LINKS.values() for target in targets),
            "CONTRIBUTING.md",
            "intake.md",
            "PILOT.md",
            "site/README.md",
            "docs/quick-reference.md",
            "docs/operational-semantics.md",
            "docs/migration-v1.md",
            "docs/dashboard-preview.md",
            "docs/auth-preview.md",
            "docs/coordination-preview.md",
            "docs/integration-starter-kit.md",
            "templates/bo_client/README.md",
            "templates/bo_client_demo/README.md",
            "templates/bo_client_full/README.md",
        }
    )
)
SUPPORT_FILES = (
    "pyproject.toml",
    "site/src/data/site.ts",
    "templates/_shared/schemas/search_space.schema.json",
)
TYPE_SUMMARIES = ("quickstart/README.md", "intake.md", "docs/search-space.md")
BACKENDS = {
    "bo_client_demo": set(),
    "bo_client": {"gp", "ax"},
    "bo_client_full": {"botorch_gp", "ax"},
}


def _linked_files(source: Path, text: str, root: Path) -> set[Path]:
    linked = set()
    for match in LINK_PATTERN.finditer(text):
        target = _normalize_target(match.group(1))
        if not target or target.startswith("#") or _is_external_target(target):
            continue
        linked.add(_resolve_target_path(source, target.partition("#")[0], root))
    return linked


def check(root: Path) -> list[str]:
    errors: list[str] = []
    texts = {}
    for name in (*REQUIRED_FILES, *SUPPORT_FILES):
        path = root / name
        if not path.is_file():
            errors.append(f"{name}: missing required documentation asset")
        else:
            texts[name] = path.read_text(encoding="utf-8")
    if errors:
        return errors

    for name, destinations in REQUIRED_LINKS.items():
        linked = _linked_files(root / name, texts[name], root)
        for destination in destinations:
            if (root / destination).resolve() not in linked:
                errors.append(f"{name}: missing canonical link to {destination}")

    schema = json.loads(texts[SUPPORT_FILES[2]])
    types = schema["properties"]["parameters"]["items"]["properties"]["type"]["enum"]
    for name in TYPE_SUMMARIES:
        text = texts[name]
        for kind in types:
            if f"`{kind}`" not in text:
                errors.append(f"{name}: missing supported parameter type {kind}")
        for paragraph in re.split(r"\n\s*\n", text):
            normalized = " ".join(paragraph.lower().split())
            if (
                "types" in normalized
                and "support" in normalized
                and "`float`" in normalized
                and "`int`" in normalized
                and ("`bool`" not in normalized or "`categorical`" not in normalized)
            ) or re.search(r"categorical.{0,100}requires? (?:a )?template extension", normalized):
                errors.append(f"{name}: stale parameter-support claim")

    rows = {}
    for line in texts["templates/README.md"].splitlines():
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        if len(cells) == 3 and cells[0].strip("`") in BACKENDS:
            rows[cells[0].strip("`")] = cells[1:]
    for variant, optional in BACKENDS.items():
        row = rows.get(variant)
        if (
            row is None
            or row[0] != "`rbf_proxy`"
            or set(re.findall(r"`([^`]+)`", row[1])) != optional
        ):
            errors.append(f"templates/README.md: incorrect backend capability row for {variant}")
        elif not optional and row[1].lower() != "none":
            errors.append(f"templates/README.md: {variant} must remain proxy-only")

    for name in (
        "templates/README.md",
        "docs/how-it-works.md",
        *(f"templates/{v}/README.md" for v in BACKENDS),
    ):
        for paragraph in re.split(r"\n\s*\n", texts[name]):
            lowered = " ".join(paragraph.lower().split())
            if ("enable_auth_preview" in lowered or "preview flags" in lowered) and any(
                term in lowered for term in ("reserved", "no-op", "globally inert")
            ):
                errors.append(f"{name}: preview flags are active service-registry gates")

    contact = re.search(r'contactEmail:\s*"([^\"]+)"', texts["site/src/data/site.ts"])
    if contact is None:
        errors.append("site/src/data/site.ts: missing contactEmail")
    else:
        for name in ("README.md", "PILOT.md", "docs/packages.md", "site/README.md"):
            addresses = set(re.findall(r"contact@looptimum\.[a-z]+", texts[name]))
            if addresses != {contact.group(1)}:
                errors.append(f"{name}: active contact email differs from siteConfig.contactEmail")

    config = tomllib.loads(texts["pyproject.toml"])
    for name in ("docs/type-safety.md", "CONTRIBUTING.md"):
        for pattern in config["tool"]["mypy"]["files"]:
            if f"`{pattern}`" not in texts[name]:
                errors.append(f"{name}: missing configured mypy scope {pattern}")

    # Version values are checked by check_release.py; links/anchors by check_internal_links.py.
    for badge in ("actions/workflows/ci.yml/badge.svg", "img.shields.io/github/v/release/"):
        if badge not in texts["README.md"]:
            errors.append(f"README.md: missing status badge {badge}")
    return errors


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Check canonical documentation links and capability facts."
    )
    parser.add_argument("--root", default=".", help="Repository root (default: current directory).")
    root = Path(parser.parse_args().root).resolve()
    errors = check(root)
    if errors:
        print("Public docs consistency check failed:")
        for error in errors:
            print(f"- {error}")
        return 1
    print("Public docs consistency check passed (canonical links and capability facts).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
