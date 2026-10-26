"""Release gates must reject metadata drift, unsafe artifacts and wrong commits."""

from __future__ import annotations

import importlib.util
import shutil
import subprocess
import tomllib
import zipfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location("release_checks", ROOT / "scripts/check_release.py")
assert SPEC and SPEC.loader
checks = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(checks)


def checkout(tmp_path):
    for relative in (
        "pyproject.toml",
        "README.md",
        "CHANGELOG.md",
        "service/app.py",
        "templates/_shared/runtime.py",
        "templates/_shared/optimizer_backend.py",
        "templates/_shared/ax-constraints.txt",
        "docs/stability-guarantees.md",
        "docs/quick-reference.md",
        "docs/migration-v1.md",
        "docs/release-guide.md",
        "docs/releases/v1.0.0.md",
    ):
        path = tmp_path / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / relative, path)
    return tmp_path


@pytest.mark.parametrize("damage", ["package", "state", "defaults", "preview"])
def test_release_gate_rejects_conflicting_version_boundaries(tmp_path, damage):
    root = checkout(tmp_path)
    assert checks.source_errors(root, "1.0.0") == []
    if damage == "state":
        path = root / "templates/_shared/runtime.py"
        path.write_text(
            path.read_text().replace(
                'STATE_SCHEMA_VERSION = "0.3.0"', 'STATE_SCHEMA_VERSION = "1.0.0"'
            )
        )
    elif damage == "preview":
        path = root / "service/app.py"
        path.write_text(path.read_text().replace('version="1.0.0-preview"', 'version="1.0.0"'))
    else:
        path = root / "pyproject.toml"
        path.write_text(
            path.read_text().replace('version = "1.0.0"', 'version = "0.4.0"')
            if damage == "package"
            else path.read_text().replace("dependencies = []", 'dependencies = ["torch"]')
        )
    assert checks.source_errors(root, "1.0.0")


def test_release_wheel_rejects_default_optimizer_dependency_and_missing_assets(tmp_path):
    project = tomllib.loads((ROOT / "pyproject.toml").read_text())["project"]
    path = tmp_path / "looptimum.whl"

    def write_wheel(extra_dependency="", include_assets=True):
        with zipfile.ZipFile(path, "w") as archive:
            archive.writestr(
                "looptimum-1.0.0.dist-info/METADATA",
                f'Name: looptimum\nVersion: {project["version"]}\nRequires-Python: {project["requires-python"]}\nRequires-Dist: ax-platform==1.3.1; extra == "ax"\n{extra_dependency}',
            )
            if include_assets:
                for relative in (
                    "service/app.py",
                    "service/dashboard_assets/dashboard.css",
                    "service/dashboard_assets/dashboard.js",
                ):
                    archive.writestr(relative, (ROOT / relative).read_bytes())

    write_wheel()
    assert checks.wheel_errors(ROOT, path) == []
    write_wheel("Requires-Dist: torch\n")
    assert "Wheel introduces a default runtime dependency" in checks.wheel_errors(ROOT, path)
    write_wheel(include_assets=False)
    assert any("source asset" in error for error in checks.wheel_errors(ROOT, path))


def test_tag_gate_requires_the_current_commit_and_a_clean_tree(tmp_path):
    def git(*args):
        return subprocess.run(
            [
                "git",
                "-C",
                str(tmp_path),
                "-c",
                "commit.gpgsign=false",
                "-c",
                "tag.gpgSign=false",
                "-c",
                "user.name=Release fixture",
                "-c",
                "user.email=fixture@example.invalid",
                *args,
            ],
            check=True,
            capture_output=True,
            text=True,
        )

    git("init", "-q")
    git("commit", "--allow-empty", "-qm", "fixture")
    git("tag", "v1.0.0")
    assert checks.git_errors(tmp_path, version="1.0.0", tag="v1.0.0", require_clean=True) == []
    assert checks.git_errors(tmp_path, version="1.0.0", tag="v0.4.0", require_clean=False)
    (tmp_path / "untracked.txt").write_text("unreviewed")
    assert checks.git_errors(tmp_path, version="1.0.0", tag=None, require_clean=True)
    git("commit", "--allow-empty", "-qm", "different commit")
    assert "Release tag does not point at the checked-out commit" in checks.git_errors(
        tmp_path, version="1.0.0", tag="v1.0.0", require_clean=False
    )
