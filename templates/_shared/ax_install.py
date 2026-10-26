#!/usr/bin/env python3
"""Build and validate a host-specific CPU Ax wheelhouse; install it without an index.

Uses only the standard library and pip. No optimizer imports occur here.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import re
import shutil
import subprocess
import sys
import tempfile
import zipfile
from email.parser import BytesParser
from pathlib import Path
from typing import Any

PROFILE = Path(__file__).with_name("ax-constraints.txt")
PYPI = "https://pypi.org/simple"
CPU_INDEX = "https://download.pytorch.org/whl/cpu"


def canonical(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def digest(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def target() -> dict[str, str]:
    value = {
        "implementation": sys.implementation.name,
        "python": f"{sys.version_info.major}.{sys.version_info.minor}",
        "system": platform.system(),
        "machine": platform.machine().lower(),
    }
    if (
        value["implementation"] != "cpython"
        or value["python"] not in {"3.11", "3.12"}
        or (value["system"], value["machine"]) not in {("Linux", "x86_64"), ("Darwin", "arm64")}
    ):
        raise ValueError(f"No tested CPU installation profile for {value}")
    return value


def read_profile(path: Path) -> dict[str, str]:
    pins: dict[str, str] = {}
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        match = re.fullmatch(r"([A-Za-z0-9][A-Za-z0-9_.-]*)==([A-Za-z0-9.+]+)", line)
        if not match or canonical(match[1]) in pins:
            raise ValueError(f"Profile requires unique exact pins, found {line!r}")
        pins[canonical(match[1])] = match[2]
    if not {"ax-platform", "botorch", "torch", "setuptools"} <= pins.keys():
        raise ValueError("Incomplete Ax dependency profile")
    return pins


def wheel_record(path: Path, pins: dict[str, str], host: dict[str, str]) -> dict[str, str]:
    with zipfile.ZipFile(path) as archive:
        # Vendored dependencies (for example inside setuptools) may carry their
        # own nested dist-info. Only the wheel's top-level metadata identifies it.
        metadata = [
            name
            for name in archive.namelist()
            if name.count("/") == 1 and name.endswith(".dist-info/METADATA")
        ]
        if len(metadata) != 1:
            raise ValueError(f"Expected one wheel metadata record: {path.name}")
        parsed = BytesParser().parsebytes(archive.read(metadata[0]))
    name, version = canonical(str(parsed["Name"])), str(parsed["Version"])
    if name not in pins or version.split("+")[0] != pins[name]:
        raise ValueError(f"Wheel is outside the pinned profile: {name}=={version}")
    if name == "torch" and (
        (host["system"] == "Linux" and not version.endswith("+cpu"))
        or (host["system"] == "Darwin" and "+" in version)
    ):
        raise ValueError("Expected the CPU Torch wheel for this platform")
    return {"filename": path.name, "name": name, "version": version, "sha256": digest(path)}


def lock_text(wheels: list[dict[str, str]]) -> str:
    return "".join(
        f"{wheel['name']}=={wheel['version']} --hash=sha256:{wheel['sha256']}\n" for wheel in wheels
    )


def pip_command(executable: str, *arguments: str) -> list[str]:
    # Python -I also ignores PYTHONPATH/PYTHONHOME and the user site. Pip's
    # --isolated alone cannot stop inherited Python paths exposing another env.
    return [executable, "-I", "-m", "pip", "--isolated", "--disable-pip-version-check", *arguments]


def run(command: list[str]) -> None:
    subprocess.run(
        command,
        check=True,
        timeout=900,
        env={**os.environ, "PIP_CONFIG_FILE": os.devnull},
    )


def build(destination: Path, profile: Path) -> None:
    host, pins = target(), read_profile(profile)
    destination = destination.resolve()
    if destination.exists():
        raise ValueError("Wheelhouse destination must not exist; existing bundles are preserved")
    destination.parent.mkdir(parents=True, exist_ok=True)
    # Stage alongside the destination. Failed resolution never publishes a bundle.
    with tempfile.TemporaryDirectory(prefix=".ax-wheelhouse-", dir=destination.parent) as temporary:
        stage = Path(temporary)
        wheels = stage / "wheels"
        wheels.mkdir()
        shutil.copyfile(profile, stage / PROFILE.name)
        torch_stage = stage / "torch"
        torch_stage.mkdir()
        run(
            pip_command(
                sys.executable,
                "download",
                "--only-binary=:all:",
                "--no-deps",
                "--index-url",
                CPU_INDEX if host["system"] == "Linux" else PYPI,
                "--dest",
                str(torch_stage),
                f"torch=={pins['torch']}",
            )
        )
        torch_wheels = list(torch_stage.glob("*.whl"))
        if len(torch_wheels) != 1:
            raise ValueError("Expected exactly one downloaded Torch wheel")
        wheel_record(torch_wheels[0], pins, host)
        run(
            pip_command(
                sys.executable,
                "download",
                "--only-binary=:all:",
                "--index-url",
                PYPI,
                "--dest",
                str(wheels),
                "--constraint",
                str(stage / PROFILE.name),
                f"ax-platform=={pins['ax-platform']}",
                str(torch_wheels[0]),
            )
        )
        records = sorted(
            (wheel_record(path, pins, host) for path in wheels.iterdir()),
            key=lambda row: row["name"],
        )
        names = [row["name"] for row in records]
        if len(names) != len(set(names)) or "ax-platform" not in names or "torch" not in names:
            raise ValueError("Duplicate or missing wheel packages")
        (stage / "requirements.lock").write_text(lock_text(records))
        manifest = {
            "format_version": 1,
            "target": host,
            "profile_sha256": digest(stage / PROFILE.name),
            "wheels": records,
        }
        (stage / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
        shutil.rmtree(torch_stage)
        stage.rename(destination)
    print(f"Built {len(records)} pinned wheels for {host}: {destination}")


def check(bundle: Path) -> dict[str, Any]:
    host = target()
    manifest = json.loads((bundle / "manifest.json").read_text())
    if manifest.get("format_version") != 1 or manifest.get("target") != host:
        raise ValueError("Wheelhouse target does not match this OS/architecture/Python minor")
    profile = bundle / PROFILE.name
    if digest(profile) != manifest.get("profile_sha256"):
        raise ValueError("Wheelhouse profile digest mismatch")
    pins = read_profile(profile)
    records = manifest.get("wheels")
    if not isinstance(records, list) or not records:
        raise ValueError("Wheelhouse has no wheel inventory")
    filenames: set[str] = set()
    names: set[str] = set()
    for record in records:
        filename = record["filename"]
        if Path(filename).name != filename or not filename.endswith(".whl"):
            raise ValueError("Invalid wheel filename")
        path = bundle / "wheels" / filename
        if path.is_symlink() or not path.is_file() or digest(path) != record["sha256"]:
            raise ValueError(f"Wheel missing or digest mismatch: {filename}")
        if wheel_record(path, pins, host) != record:
            raise ValueError(f"Wheel metadata mismatch: {filename}")
        if filename in filenames or record["name"] in names:
            raise ValueError("Duplicate wheel inventory")
        filenames.add(filename)
        names.add(record["name"])
    if not {"ax-platform", "torch"} <= names:
        raise ValueError("Wheelhouse is missing Ax or Torch")
    if {path.name for path in (bundle / "wheels").iterdir()} != filenames:
        raise ValueError("Wheelhouse has unlisted files")
    # Never pass a user-edited requirement/direct URL to pip, even if it has a hash.
    if (bundle / "requirements.lock").read_text() != lock_text(records):
        raise ValueError("Wheelhouse requirements lock differs from inventory")
    return dict(manifest)


def install(bundle: Path, executable: str, receipt: Path) -> None:
    bundle = bundle.resolve()
    if receipt.exists():
        raise ValueError("Receipt path already exists; preserve previous installation evidence")
    manifest = check(bundle)
    inspection = subprocess.check_output(
        [
            executable,
            "-I",
            "-c",
            "import json,sys,platform; print(json.dumps("
            "dict(implementation=sys.implementation.name,python=f'{sys.version_info.major}.{sys.version_info.minor}',"
            "system=platform.system(),machine=platform.machine().lower(),"
            "venv=sys.prefix!=sys.base_prefix)))",
        ],
        text=True,
        timeout=30,
    )
    environment = json.loads(inspection)
    if not environment.pop("venv") or environment != manifest["target"]:
        raise ValueError("Install requires a matching virtual environment")
    run(
        pip_command(
            executable,
            "install",
            "--no-index",
            "--find-links",
            str(bundle / "wheels"),
            "--only-binary=:all:",
            "--require-hashes",
            "--requirement",
            str(bundle / "requirements.lock"),
        )
    )
    run(pip_command(executable, "check"))
    installed = json.loads(
        subprocess.check_output(
            [
                executable,
                "-I",
                "-c",
                "import json,importlib.metadata as m; "
                "print(json.dumps({d.metadata['Name']:d.version for d in m.distributions()}))",
            ],
            text=True,
            timeout=30,
        )
    )
    normalized = {canonical(name): value for name, value in installed.items()}
    if any(normalized.get(row["name"]) != row["version"] for row in manifest["wheels"]):
        raise ValueError("Installed versions differ from wheelhouse")
    receipt.parent.mkdir(parents=True, exist_ok=True)
    receipt.write_text(
        json.dumps(
            {
                "format_version": 1,
                "target": manifest["target"],
                "profile_sha256": manifest["profile_sha256"],
                "manifest_sha256": digest(bundle / "manifest.json"),
                "installed_versions": dict(sorted(installed.items())),
                "pip_check": "passed",
                "installation_source": "local hashed wheels; no package index",
            },
            indent=2,
        )
        + "\n"
    )
    print(f"Installed pinned Ax environment; receipt: {receipt}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    builder = commands.add_parser("build", help="Download CPU wheels on a matching connected host")
    builder.add_argument("wheelhouse", type=Path)
    builder.add_argument("--profile", type=Path, default=PROFILE)
    validator = commands.add_parser("check", help="Validate target, inventory, metadata and hashes")
    validator.add_argument("wheelhouse", type=Path)
    installer = commands.add_parser("install", help="Install local wheels in a matching venv")
    installer.add_argument("wheelhouse", type=Path)
    installer.add_argument("--python", default=sys.executable)
    installer.add_argument("--receipt", required=True, type=Path)
    args = parser.parse_args()
    try:
        if args.command == "build":
            build(args.wheelhouse, args.profile)
        elif args.command == "check":
            checked = check(args.wheelhouse)
            print(f"Verified {len(checked['wheels'])} wheel hashes for {checked['target']}")
        else:
            install(args.wheelhouse, args.python, args.receipt)
    except (ValueError, OSError, KeyError, zipfile.BadZipFile, subprocess.SubprocessError) as error:
        parser.exit(1, f"Ax installation failed: {error}\n")


if __name__ == "__main__":
    main()
