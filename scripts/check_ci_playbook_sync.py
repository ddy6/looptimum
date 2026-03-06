#!/usr/bin/env python3
from __future__ import annotations

import argparse
import re
import subprocess
from pathlib import Path

LINK_PATTERN = re.compile(r"!?\[[^\]]*\]\(([^)]+)\)")
INLINE_CODE_PATTERN = re.compile(r"`([^`\n]+)`")
FENCE_START_PATTERN = re.compile(r"^\s*```\s*([A-Za-z0-9_+-]*)\s*$")

REPO_PATH_PREFIXES = (
    "docs/",
    "templates/",
    "client_harness_template/",
    "scripts/",
    "quickstart/",
    "reports/",
)
REPO_FILE_NAMES = {"README.md", "CONTRIBUTING.md", "requirements-dev.txt", "pyproject.toml"}


def _iter_bash_blocks(markdown: str) -> list[str]:
    blocks: list[str] = []
    lines = markdown.splitlines()
    in_fence = False
    fence_lang = ""
    current: list[str] = []

    for line in lines:
        match = FENCE_START_PATTERN.match(line)
        if match:
            if not in_fence:
                in_fence = True
                fence_lang = match.group(1).strip().lower()
                current = []
                continue
            if fence_lang in {"bash", "sh"}:
                blocks.append("\n".join(current) + "\n")
            in_fence = False
            fence_lang = ""
            current = []
            continue

        if in_fence:
            current.append(line)

    return blocks


def _normalize_target(raw: str) -> str:
    target = raw.strip()
    if target.startswith("<") and target.endswith(">"):
        target = target[1:-1].strip()
    if not target:
        return ""
    return target.split(maxsplit=1)[0]


def _looks_like_repo_path(token: str) -> bool:
    if not token or "://" in token:
        return False
    if token.startswith(("/tmp/", "/path/", "./", "../")):
        return False
    if any(ch in token for ch in ("*", "{", "}", "<", ">")):
        return False
    if token in REPO_FILE_NAMES:
        return True
    return token.startswith(REPO_PATH_PREFIXES)


def _candidate_parts(raw: str) -> list[str]:
    parts: list[str] = []
    for token in re.split(r"[\s|;&]+", raw.strip()):
        cleaned = token.strip().strip("\"'`").strip(",.()[]{}")
        if cleaned:
            parts.append(cleaned)
    return parts


def _collect_doc_paths(text: str) -> set[str]:
    refs: set[str] = set()

    for match in LINK_PATTERN.finditer(text):
        raw = _normalize_target(match.group(1))
        if not raw or raw.startswith(("http://", "https://", "mailto:", "#")):
            continue
        path = raw.split("#", maxsplit=1)[0]
        if _looks_like_repo_path(path):
            refs.add(path)

    for match in INLINE_CODE_PATTERN.finditer(text):
        token = match.group(1).strip()
        for part in _candidate_parts(token):
            if _looks_like_repo_path(part):
                refs.add(part)

    return refs


def _validate_bash_blocks(blocks: list[str]) -> list[str]:
    errors: list[str] = []
    for idx, block in enumerate(blocks, start=1):
        proc = subprocess.run(
            ["bash", "-n"], input=block, text=True, capture_output=True, check=False
        )
        if proc.returncode != 0:
            stderr = (proc.stderr or "").strip()
            errors.append(f"bash block {idx} failed syntax check: {stderr}")
    return errors


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Validate docs/ci-knob-tuning.md references and bash block syntax."
    )
    parser.add_argument(
        "--root",
        default=".",
        help="Repository root (default: current directory).",
    )
    parser.add_argument(
        "--doc",
        default="docs/ci-knob-tuning.md",
        help="Path to CI playbook markdown file relative to root.",
    )
    args = parser.parse_args()

    repo_root = Path(args.root).resolve()
    doc_path = (repo_root / args.doc).resolve()
    if not doc_path.exists():
        print(f"CI playbook sync check failed: missing doc {doc_path.relative_to(repo_root)}")
        return 1

    text = doc_path.read_text(encoding="utf-8")
    errors: list[str] = []

    refs = _collect_doc_paths(text)
    for block in _iter_bash_blocks(text):
        for part in _candidate_parts(block):
            if _looks_like_repo_path(part):
                refs.add(part)
    for ref in sorted(refs):
        ref_path = (repo_root / ref).resolve()
        if not ref_path.exists():
            errors.append(f"missing referenced path: {ref}")

    bash_blocks = _iter_bash_blocks(text)
    errors.extend(_validate_bash_blocks(bash_blocks))

    if errors:
        print("CI playbook sync check failed:")
        for err in errors:
            print(f"- {err}")
        return 1

    print(
        "CI playbook sync check passed "
        f"({len(refs)} referenced paths, {len(bash_blocks)} bash blocks)."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
