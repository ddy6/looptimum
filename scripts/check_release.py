#!/usr/bin/env python3
"""Read-only release metadata, wheel and exact-tag checks. Never publishes."""

from __future__ import annotations

import argparse
import ast
import re
import subprocess
import tomllib
import zipfile
from email.parser import BytesParser
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
VERSION = re.compile(r"(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)")


def constant(path: Path, name: str) -> Any:
    for node in ast.parse(path.read_text()).body:
        if isinstance(node, ast.Assign) and any(
            isinstance(target, ast.Name) and target.id == name for target in node.targets
        ):
            return ast.literal_eval(node.value)
    raise ValueError(f"Missing constant {name} in {path}")


def source_errors(root: Path, expected: str | None = None) -> list[str]:
    project = tomllib.loads((root / "pyproject.toml").read_text())["project"]
    version = project["version"]
    errors = []
    if not VERSION.fullmatch(version):
        errors.append("Release version must be a final semantic version")
    if expected is not None and version != expected:
        errors.append(f"Package version {version} differs from expected {expected}")
    if project["dependencies"]:
        errors.append("Default package must remain free of runtime dependencies")
    requirements = {
        "README.md": f"Version in this checkout: `v{version}`.",
        "CHANGELOG.md": f"## [{version}] - ",
        "service/app.py": f'version="{version}-preview"',
        "docs/stability-guarantees.md": f"stable `v{version.split('.')[0]}.x`",
        "docs/quick-reference.md": f"## Public Command Surface (`v{version.split('.')[0]}.x`)",
        "docs/migration-v1.md": "## Rollback",
        "docs/release-guide.md": "## Publish the tag",
        f"docs/releases/v{version}.md": f"# Looptimum v{version}",
    }
    for relative, text in requirements.items():
        path = root / relative
        if not path.is_file() or text not in path.read_text():
            errors.append(f"Missing release metadata in {relative}: {text}")
    # A package bump must never relabel persisted state or evaluator payloads.
    for name, value in (("STATE_SCHEMA_VERSION", "0.3.0"), ("AX_STATE_SCHEMA_VERSION", "0.4.0")):
        if constant(root / "templates/_shared/runtime.py", name) != value:
            errors.append(f"State version boundary changed: {name}")
    backend = root / "templates/_shared/optimizer_backend.py"
    if constant(backend, "AX_FORMAT_VERSION") != 1:
        errors.append("Ax optimizer format boundary changed")
    pin = f"ax-platform=={constant(backend, 'AX_TESTED_VERSION')}"
    if project["optional-dependencies"]["ax"] != [pin]:
        errors.append("Ax extra differs from supported adapter version")
    if pin not in (root / "templates/_shared/ax-constraints.txt").read_text().splitlines():
        errors.append("Ax profile differs from package extra")
    return errors


def wheel_errors(root: Path, path: Path) -> list[str]:
    project = tomllib.loads((root / "pyproject.toml").read_text())["project"]
    errors = []
    with zipfile.ZipFile(path) as archive:
        metadata_files = [
            name
            for name in archive.namelist()
            if name.count("/") == 1 and name.endswith(".dist-info/METADATA")
        ]
        if len(metadata_files) != 1:
            return ["Wheel must contain one top-level metadata record"]
        metadata = BytesParser().parsebytes(archive.read(metadata_files[0]))
        if metadata["Name"] != project["name"] or metadata["Version"] != project["version"]:
            errors.append("Wheel package name/version differs from checkout")
        if metadata["Requires-Python"] != project["requires-python"]:
            errors.append("Wheel Python requirement differs from checkout")
        dependencies = metadata.get_all("Requires-Dist", [])
        if any("extra ==" not in entry for entry in dependencies):
            errors.append("Wheel introduces a default runtime dependency")
        ax_pin = project["optional-dependencies"]["ax"][0]
        if not any(
            entry.split(";")[0].strip() == ax_pin
            and re.search(r"extra == [\"\x27]ax[\"\x27]", entry)
            for entry in dependencies
        ):
            errors.append("Wheel omits the pinned optional Ax extra")
        for relative in (
            "service/app.py",
            "service/dashboard_assets/dashboard.css",
            "service/dashboard_assets/dashboard.js",
        ):
            if (
                relative not in archive.namelist()
                or archive.read(relative) != (root / relative).read_bytes()
            ):
                errors.append(f"Wheel omits or changes source asset: {relative}")
    return errors


def git_output(root: Path, *arguments: str) -> str:
    return subprocess.check_output(
        ["git", "-C", str(root), *arguments], text=True, stderr=subprocess.PIPE, timeout=30
    ).strip()


def installation_errors(root: Path, executable: str) -> list[str]:
    import json

    project = tomllib.loads((root / "pyproject.toml").read_text())["project"]
    installed = json.loads(
        subprocess.check_output(
            [
                executable,
                "-I",
                "-c",
                "import json,importlib.metadata as m,importlib.util as u; "
                "print(json.dumps(dict(version=m.version('looptimum'),optimizer_imports="
                "[n for n in ('ax','botorch','torch','gpytorch','numpy','scipy') if u.find_spec(n) is not None])))",
            ],
            text=True,
            timeout=30,
        )
    )
    errors = []
    if installed["version"] != project["version"]:
        errors.append("Installed wheel version differs from checkout")
    if installed["optimizer_imports"]:
        errors.append("Lean wheel environment exposes optional numerical packages")
    return errors


def git_errors(root: Path, *, version: str, tag: str | None, require_clean: bool) -> list[str]:
    errors = []
    if require_clean and git_output(root, "status", "--porcelain"):
        errors.append("Release worktree must be clean, including untracked files")
    if tag is not None:
        if tag != f"v{version}":
            errors.append(f"Tag {tag} differs from package v{version}")
        else:
            try:
                commit = git_output(root, "rev-parse", "--verify", f"refs/tags/{tag}^{{commit}}")
                if commit != git_output(root, "rev-parse", "HEAD"):
                    errors.append("Release tag does not point at the checked-out commit")
            except subprocess.CalledProcessError:
                errors.append(f"Release tag does not exist locally: {tag}")
    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--expected-version")
    parser.add_argument("--wheel", type=Path)
    parser.add_argument(
        "--installed-python", help="Check a lean environment installed from the wheel"
    )
    parser.add_argument("--tag")
    parser.add_argument("--require-clean", action="store_true")
    args = parser.parse_args()
    try:
        root = args.root.resolve()
        version = tomllib.loads((root / "pyproject.toml").read_text())["project"]["version"]
        errors = source_errors(root, args.expected_version)
        if args.wheel:
            errors.extend(wheel_errors(root, args.wheel))
        if args.installed_python:
            errors.extend(installation_errors(root, args.installed_python))
        if args.tag or args.require_clean:
            errors.extend(
                git_errors(root, version=version, tag=args.tag, require_clean=args.require_clean)
            )
        if errors:
            for error in errors:
                print(f"Release check failed: {error}")
            return 1
    except (OSError, ValueError, KeyError, subprocess.SubprocessError, zipfile.BadZipFile) as error:
        print(f"Release check failed: {error}")
        return 1
    print(f"Release metadata checks passed for v{version}; no publication performed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
