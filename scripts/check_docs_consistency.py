#!/usr/bin/env python3
from __future__ import annotations

import argparse
from pathlib import Path

PUBLIC_DOC_ROOTS = ("README.md", "docs", "quickstart")

REQUIRED_FILES = (
    "README.md",
    "docs/index.md",
    "docs/README.md",
    "docs/quick-reference.md",
    "quickstart/README.md",
    "quickstart/etl-pipeline-knob-tuning.md",
)

REQUIRED_SNIPPETS: dict[str, tuple[str, ...]] = {
    "README.md": (
        "actions/workflows/ci.yml/badge.svg",
        "img.shields.io/github/v/release/",
        "## Trust Anchors",
        "(docs/quick-reference.md)",
        "(quickstart/etl-pipeline-knob-tuning.md)",
    ),
    "docs/index.md": (
        "(./quick-reference.md)",
        "(../quickstart/etl-pipeline-knob-tuning.md)",
    ),
    "docs/README.md": (
        "`quick-reference.md`",
        "`../quickstart/etl-pipeline-knob-tuning.md`",
    ),
    "docs/quick-reference.md": (
        "## Public Command Surface (`v0.3.x`)",
        "## State and Artifact Definitions",
        "## Compatibility",
    ),
    "quickstart/README.md": ("(./etl-pipeline-knob-tuning.md)",),
    "quickstart/etl-pipeline-knob-tuning.md": (
        "# ETL Pipeline Knob-Tuning Quickstart",
        "## Run Sequence (Canonical)",
        "## Evidence and Audit Trail",
    ),
}


def _load_text(repo_root: Path, rel_path: str) -> str:
    path = (repo_root / rel_path).resolve()
    return path.read_text(encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Validate lightweight public docs consistency checks for README/docs/quickstart."
        )
    )
    parser.add_argument(
        "--root",
        default=".",
        help="Repository root containing docs (default: current directory).",
    )
    args = parser.parse_args()

    repo_root = Path(args.root).resolve()
    errors: list[str] = []

    for rel_path in REQUIRED_FILES:
        path = (repo_root / rel_path).resolve()
        if not path.exists():
            errors.append(f"missing required public doc asset: {rel_path}")

    for rel_path, snippets in REQUIRED_SNIPPETS.items():
        path = (repo_root / rel_path).resolve()
        if not path.exists():
            continue
        text = _load_text(repo_root, rel_path)
        for snippet in snippets:
            if snippet not in text:
                errors.append(f"missing required snippet in {rel_path}: {snippet}")

    if errors:
        print("Public docs consistency check failed:")
        for err in errors:
            print(f"- {err}")
        return 1

    roots = ", ".join(PUBLIC_DOC_ROOTS)
    print(f"Public docs consistency check passed (scope: {roots}).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
