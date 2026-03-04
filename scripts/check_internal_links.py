#!/usr/bin/env python3
from __future__ import annotations

import argparse
import re
from pathlib import Path
from typing import Iterable
from urllib.parse import unquote, urlparse

LINK_PATTERN = re.compile(r"!?\[[^\]]*]\(([^)]+)\)")
HEADING_PATTERN = re.compile(r"^\s{0,3}#{1,6}\s+(.+?)\s*$")
FENCE_PATTERN = re.compile(r"^\s*```")
EXTERNAL_SCHEMES = {"http", "https", "mailto", "tel"}
SKIP_TARGET_PREFIXES = ("javascript:", "data:")


def _github_anchor_slug(heading: str) -> str:
    slug = heading.strip().lower()
    slug = re.sub(r"[^\w\- ]", "", slug)
    slug = slug.replace(" ", "-")
    slug = re.sub(r"-{2,}", "-", slug).strip("-")
    return slug


def _extract_anchors(md_path: Path) -> set[str]:
    anchors: set[str] = set()
    duplicates: dict[str, int] = {}
    in_fence = False
    for line in md_path.read_text(encoding="utf-8").splitlines():
        if FENCE_PATTERN.match(line):
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        match = HEADING_PATTERN.match(line)
        if not match:
            continue
        base = _github_anchor_slug(match.group(1))
        if not base:
            continue
        count = duplicates.get(base, 0)
        duplicates[base] = count + 1
        anchors.add(base if count == 0 else f"{base}-{count}")
    return anchors


def _normalize_target(raw_target: str) -> str:
    target = raw_target.strip()
    if target.startswith("<") and target.endswith(">"):
        target = target[1:-1].strip()
    if not target:
        return target
    # Drop optional markdown title: ./file.md "Title"
    return target.split(maxsplit=1)[0]


def _iter_markdown_files(repo_root: Path, roots: Iterable[Path]) -> list[Path]:
    md_paths: list[Path] = []
    for root in roots:
        if root.is_file() and root.suffix.lower() == ".md":
            md_paths.append(root)
            continue
        if root.is_dir():
            md_paths.extend(sorted(root.rglob("*.md")))
    # Keep deterministic order and deduplicate.
    return sorted(set(path.resolve() for path in md_paths if path.exists()))


def _is_external_target(target: str) -> bool:
    parsed = urlparse(target)
    if parsed.scheme.lower() in EXTERNAL_SCHEMES:
        return True
    lowered = target.lower()
    return any(lowered.startswith(prefix) for prefix in SKIP_TARGET_PREFIXES)


def _resolve_target_path(source_file: Path, target_path: str, repo_root: Path) -> Path:
    if target_path.startswith("/"):
        return (repo_root / target_path.lstrip("/")).resolve()
    return (source_file.parent / unquote(target_path)).resolve()


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate internal markdown links and anchors.")
    parser.add_argument(
        "--root",
        default=".",
        help="Repository root containing markdown docs (default: current directory).",
    )
    parser.add_argument(
        "--paths",
        nargs="*",
        default=[
            "README.md",
            "CONTRIBUTING.md",
            "intake.md",
            "docs",
            "quickstart",
            "templates",
            "reports",
        ],
        help="Markdown roots/files to scan.",
    )
    args = parser.parse_args()

    repo_root = Path(args.root).resolve()
    scan_roots = [(repo_root / rel).resolve() for rel in args.paths]
    markdown_files = _iter_markdown_files(repo_root, scan_roots)

    anchors_cache: dict[Path, set[str]] = {}
    errors: list[str] = []

    for md_file in markdown_files:
        lines = md_file.read_text(encoding="utf-8").splitlines()
        in_fence = False
        for line_no, line in enumerate(lines, start=1):
            if FENCE_PATTERN.match(line):
                in_fence = not in_fence
                continue
            if in_fence:
                continue
            for match in LINK_PATTERN.finditer(line):
                raw_target = match.group(1)
                target = _normalize_target(raw_target)
                if not target or _is_external_target(target):
                    continue

                if target.startswith("#"):
                    target_path = md_file
                    anchor = target[1:]
                else:
                    rel_path, sep, anchor = target.partition("#")
                    target_path = _resolve_target_path(md_file, rel_path, repo_root)
                    if not target_path.exists():
                        errors.append(
                            f"{md_file.relative_to(repo_root)}:{line_no}: missing target '{target}'"
                        )
                        continue

                if not anchor:
                    continue
                if target_path.suffix.lower() != ".md":
                    errors.append(
                        f"{md_file.relative_to(repo_root)}:{line_no}: anchor used for non-md target '{target}'"
                    )
                    continue

                anchors = anchors_cache.get(target_path)
                if anchors is None:
                    anchors = _extract_anchors(target_path)
                    anchors_cache[target_path] = anchors
                if anchor not in anchors:
                    errors.append(
                        f"{md_file.relative_to(repo_root)}:{line_no}: missing anchor '{anchor}' in "
                        f"'{target_path.relative_to(repo_root)}'"
                    )

    if errors:
        print("Internal link check failed:")
        for err in errors:
            print(f"- {err}")
        return 1

    print(f"Internal link check passed ({len(markdown_files)} markdown files scanned).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
