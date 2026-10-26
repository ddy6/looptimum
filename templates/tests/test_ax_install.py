"""Offline provisioning boundaries; no downloads or numerical dependencies."""

from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location(
    "ax_install", ROOT / "templates/_shared/ax_install.py"
)
assert SPEC and SPEC.loader
tool = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(tool)


def bundle(tmp_path, monkeypatch):
    host = {"implementation": "cpython", "python": "3.11", "system": "Linux", "machine": "x86_64"}
    monkeypatch.setattr(tool, "target", lambda: host)
    destination = tmp_path / "bundle"
    wheels = destination / "wheels"
    wheels.mkdir(parents=True)
    profile = destination / "ax-constraints.txt"
    profile.write_text("ax-platform==1.3.1\nbotorch==0.18.1\ntorch==2.14.1\nsetuptools==80.9.0\n")
    pins = tool.read_profile(profile)
    records = []
    for name, version in (("ax-platform", "1.3.1"), ("torch", "2.14.1+cpu")):
        path = wheels / f"{name.replace('-', '_')}-{version}-py3-none-any.whl"
        with zipfile.ZipFile(path, "w") as archive:
            archive.writestr(
                f"{name.replace('-', '_')}-{version}.dist-info/METADATA",
                f"Metadata-Version: 2.1\nName: {name}\nVersion: {version}\n",
            )
        records.append(tool.wheel_record(path, pins, host))
    (destination / "requirements.lock").write_text(tool.lock_text(records))
    (destination / "manifest.json").write_text(
        json.dumps(
            {
                "format_version": 1,
                "target": host,
                "profile_sha256": tool.digest(profile),
                "wheels": records,
            }
        )
    )
    return destination


@pytest.mark.parametrize(
    "damage", ["wheel", "profile", "lock", "extra", "target", "path", "metadata", "duplicate"]
)
def test_wheelhouse_rejects_tampering_before_pip(tmp_path, monkeypatch, damage):
    destination = bundle(tmp_path, monkeypatch)
    manifest_path = destination / "manifest.json"
    manifest = json.loads(manifest_path.read_text())
    assert tool.check(destination)["format_version"] == 1
    if damage == "wheel":
        (destination / "wheels" / manifest["wheels"][0]["filename"]).write_bytes(b"corrupt")
    elif damage == "profile":
        (destination / "ax-constraints.txt").write_text("ax-platform==9\n")
    elif damage == "lock":
        (destination / "requirements.lock").write_text(
            "ax-platform @ https://example.com/evil.whl\n"
        )
    elif damage == "extra":
        (destination / "wheels/extra.whl").write_bytes(b"extra")
    else:
        if damage == "target":
            manifest["target"]["python"] = "3.12"
        elif damage == "path":
            manifest["wheels"][0]["filename"] = "../outside.whl"
        elif damage == "metadata":
            manifest["wheels"][0]["name"] = "different-package"
        elif damage == "duplicate":
            manifest["wheels"].append(manifest["wheels"][0])
        manifest_path.write_text(json.dumps(manifest))
    commands = []
    monkeypatch.setattr(tool, "run", commands.append)
    with pytest.raises(ValueError):
        tool.install(destination, sys.executable, tmp_path / "receipt.json")
    assert commands == [] and not (tmp_path / "receipt.json").exists()


def test_install_uses_only_local_hashed_requirements_and_records_verified_versions(
    tmp_path, monkeypatch
):
    destination = bundle(tmp_path, monkeypatch)
    manifest = tool.check(destination)
    replies = iter(
        [
            json.dumps({**manifest["target"], "venv": True}),
            json.dumps({"ax-platform": "1.3.1", "torch": "2.14.1+cpu", "pip": "26.0"}),
        ]
    )
    monkeypatch.setattr(tool.subprocess, "check_output", lambda *a, **kw: next(replies))
    commands = []
    monkeypatch.setattr(tool, "run", commands.append)
    receipt = tmp_path / "receipt.json"
    tool.install(destination, "/venv/bin/python", receipt)
    assert len(commands) == 2
    command = commands[0]
    assert command[:4] == ["/venv/bin/python", "-I", "-m", "pip"]
    assert {"--isolated", "--no-index", "--require-hashes", "--only-binary=:all:"} <= set(command)
    assert "--index-url" not in command and not any("https://" in arg for arg in command)
    assert commands[1][-1] == "check"
    result = json.loads(receipt.read_text())
    assert result["pip_check"] == "passed"
    assert result["installed_versions"]["torch"] == "2.14.1+cpu"
    assert result["manifest_sha256"] == tool.digest(destination / "manifest.json")


def test_failed_install_never_writes_success_receipt(tmp_path, monkeypatch):
    destination = bundle(tmp_path, monkeypatch)
    manifest = tool.check(destination)
    monkeypatch.setattr(
        tool.subprocess,
        "check_output",
        lambda *a, **kw: json.dumps({**manifest["target"], "venv": True}),
    )

    def failed(command):
        raise subprocess.CalledProcessError(1, command)

    monkeypatch.setattr(tool, "run", failed)
    with pytest.raises(subprocess.CalledProcessError):
        tool.install(destination, "/venv/bin/python", tmp_path / "receipt.json")
    assert not (tmp_path / "receipt.json").exists()


def test_pip_ignores_inherited_python_paths_and_home(tmp_path):
    environment = tmp_path / "environment"
    subprocess.run(
        [sys.executable, "-I", "-m", "venv", str(environment)], check=True, capture_output=True
    )
    shadow = tmp_path / "shadow"
    shadow.mkdir()
    (shadow / "pip.py").write_text("raise RuntimeError('inherited pip shadow was imported')\n")
    executable = environment / "bin/python"
    result = subprocess.run(
        tool.pip_command(str(executable), "--version"),
        env={**os.environ, "PYTHONPATH": str(shadow), "PYTHONHOME": str(shadow)},
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert str(environment) in result.stdout
    assert "inherited pip shadow" not in result.stderr


def test_failed_download_does_not_publish_or_overwrite_a_bundle(tmp_path, monkeypatch):
    destination = bundle(tmp_path, monkeypatch)
    profile = destination / "ax-constraints.txt"
    commands = []
    monkeypatch.setattr(tool, "run", commands.append)
    with pytest.raises(ValueError, match="must not exist"):
        tool.build(destination, profile)
    assert not commands

    def failed(command):
        raise subprocess.CalledProcessError(1, command)

    monkeypatch.setattr(tool, "run", failed)
    with pytest.raises(subprocess.CalledProcessError):
        tool.build(tmp_path / "new", profile)
    assert not (tmp_path / "new").exists()
    assert not list(tmp_path.glob(".ax-wheelhouse-*"))


def test_cpu_wheel_requirement_and_exact_profile_are_enforced(tmp_path, monkeypatch):
    destination = bundle(tmp_path, monkeypatch)
    profile = destination / "ax-constraints.txt"
    pins = tool.read_profile(profile)
    path = destination / "torch-2.14.1-py3-none-any.whl"
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("torch-2.14.1.dist-info/METADATA", "Name: torch\nVersion: 2.14.1\n")
    with pytest.raises(ValueError, match="CPU Torch"):
        tool.wheel_record(path, pins, tool.target())
    profile.write_text(profile.read_text() + "ax_platform==1.3.1\n")
    with pytest.raises(ValueError, match="unique exact pins"):
        tool.read_profile(profile)


def test_wheel_identity_uses_top_level_metadata_and_ignores_vendored_packages(
    tmp_path, monkeypatch
):
    destination = bundle(tmp_path, monkeypatch)
    path = destination / "setuptools-80.9.0-py3-none-any.whl"
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr(
            "setuptools-80.9.0.dist-info/METADATA", "Name: setuptools\nVersion: 80.9.0\n"
        )
        archive.writestr(
            "setuptools/_vendor/packaging-24.2.dist-info/METADATA",
            "Name: packaging\nVersion: 24.2\n",
        )
    record = tool.wheel_record(
        path, tool.read_profile(destination / "ax-constraints.txt"), tool.target()
    )
    assert record["name"] == "setuptools" and record["version"] == "80.9.0"
    with zipfile.ZipFile(path, "a") as archive:
        archive.writestr("other-1.0.dist-info/METADATA", "Name: other\nVersion: 1.0\n")
    with pytest.raises(ValueError, match="one wheel metadata"):
        tool.wheel_record(
            path, tool.read_profile(destination / "ax-constraints.txt"), tool.target()
        )


def test_install_rejects_a_foreign_interpreter_before_mutating_it(tmp_path, monkeypatch):
    destination = bundle(tmp_path, monkeypatch)
    host = tool.check(destination)["target"]
    monkeypatch.setattr(
        tool.subprocess,
        "check_output",
        lambda *a, **kw: json.dumps({**host, "python": "3.12", "venv": True}),
    )
    commands = []
    monkeypatch.setattr(tool, "run", commands.append)
    with pytest.raises(ValueError, match="matching virtual environment"):
        tool.install(destination, "/foreign/python", tmp_path / "receipt.json")
    assert commands == []


def test_profile_matches_root_extra_and_portable_tools_are_self_contained(tmp_path):
    import tomllib

    profile = ROOT / "templates/_shared/ax-constraints.txt"
    pins = tool.read_profile(profile)
    project = tomllib.loads((ROOT / "pyproject.toml").read_text())
    assert project["project"]["optional-dependencies"]["ax"] == [
        f"ax-platform=={pins['ax-platform']}"
    ]
    for variant in ("bo_client", "bo_client_full"):
        destination = tmp_path / variant
        subprocess.run(
            [
                sys.executable,
                str(ROOT / "templates/_shared/vendor_copy.py"),
                str(ROOT / "templates" / variant),
                str(destination),
            ],
            check=True,
            capture_output=True,
        )
        assert (destination / "ax-constraints.txt").read_bytes() == profile.read_bytes()
        assert (destination / "ax_install.py").read_bytes() == (
            ROOT / "templates/_shared/ax_install.py"
        ).read_bytes()
        assert "../_shared" not in (destination / "requirements-ax.txt").read_text()
        subprocess.run(
            [sys.executable, "-S", "ax_install.py", "--help"],
            cwd=destination,
            check=True,
            capture_output=True,
        )
