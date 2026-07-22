from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
FULL_TEMPLATE = REPO_ROOT / "templates" / "bo_client_full"
PORTABLE_COPY_TOOL = REPO_ROOT / "templates" / "_shared" / "vendor_copy.py"
RUNTIME_MODULES = {
    "contract.py",
    "constraints.py",
    "objectives.py",
    "archives.py",
    "governance.py",
    "runtime.py",
    "search_space.py",
    "observations_io.py",
}
SCHEMAS = {
    "constraints.schema.json",
    "ingest_payload.schema.json",
    "objective_schema.schema.json",
    "search_space.schema.json",
    "suggestion_payload.schema.json",
}


def _run(command: list[str], *, cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(command, cwd=cwd, capture_output=True, text=True)


def test_portable_copy_is_self_contained_and_validates_from_an_empty_destination(
    tmp_path: Path,
) -> None:
    destination = tmp_path / "controller"
    copied = _run(
        [sys.executable, str(PORTABLE_COPY_TOOL), str(FULL_TEMPLATE), str(destination)],
        cwd=REPO_ROOT,
    )
    assert copied.returncode == 0, copied.stderr
    assert "Created portable Looptimum controller" in copied.stdout

    vendor_root = destination / "vendor" / "looptimum_shared"
    assert {path.name for path in vendor_root.glob("*.py")} == RUNTIME_MODULES
    assert {path.name for path in (vendor_root / "schemas").glob("*.json")} == SCHEMAS

    controller_source = (destination / "run_bo.py").read_text(encoding="utf-8")
    assert '_TEMPLATE_DIR / "vendor" / "looptimum_shared" / filename' in controller_source
    assert "../_shared" not in controller_source

    config = json.loads((destination / "bo_config.json").read_text(encoding="utf-8"))
    schema_paths = {value for key, value in config["paths"].items() if key.endswith("_schema_file")}
    assert schema_paths == {f"vendor/looptimum_shared/schemas/{schema}" for schema in SCHEMAS}

    validated = _run(
        [
            sys.executable,
            "run_bo.py",
            "validate",
            "--project-root",
            str(destination),
        ],
        cwd=destination,
    )
    assert validated.returncode == 0, validated.stderr
    assert "Validation passed." in validated.stdout
