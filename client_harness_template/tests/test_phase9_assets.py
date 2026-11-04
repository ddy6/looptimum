from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
DOCS_QUICK_REFERENCE = REPO_ROOT / "docs" / "quick-reference.md"
ETL_QUICKSTART = REPO_ROOT / "quickstart" / "etl-pipeline-knob-tuning.md"
DOCS_CONSISTENCY_SCRIPT = REPO_ROOT / "scripts" / "check_docs_consistency.py"
CI_WORKFLOW = REPO_ROOT / ".github" / "workflows" / "ci.yml"
TOP_LEVEL_README = REPO_ROOT / "README.md"


def test_phase9_core_assets_exist() -> None:
    assert DOCS_QUICK_REFERENCE.exists(), f"missing quick reference: {DOCS_QUICK_REFERENCE}"
    assert ETL_QUICKSTART.exists(), f"missing ETL quickstart: {ETL_QUICKSTART}"
    assert DOCS_CONSISTENCY_SCRIPT.exists(), (
        f"missing docs consistency script: {DOCS_CONSISTENCY_SCRIPT}"
    )


def test_readme_includes_primary_routes_and_badges() -> None:
    text = TOP_LEVEL_README.read_text(encoding="utf-8")
    assert "actions/workflows/ci.yml/badge.svg" in text
    assert "img.shields.io/github/v/release/ddy6/looptimum" in text
    assert "docs/quick-reference.md" in text
    assert "quickstart/README.md" in text
    assert "docs/index.md" in text


def test_ci_workflow_runs_public_docs_consistency_checks() -> None:
    text = CI_WORKFLOW.read_text(encoding="utf-8")
    assert "Validate internal markdown links" in text
    assert "python scripts/check_internal_links.py --paths README.md CONTRIBUTING.md" in text
    assert "reports site/README.md" in text
    assert "Validate public docs consistency" in text
    assert "python scripts/check_docs_consistency.py" in text


def test_docs_consistency_script_passes_on_current_docs() -> None:
    proc = subprocess.run(
        [sys.executable, str(DOCS_CONSISTENCY_SCRIPT), "--root", str(REPO_ROOT)],
        cwd=str(REPO_ROOT),
        text=True,
        capture_output=True,
        check=False,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr


@pytest.fixture
def docs_fixture(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.syspath_prepend(str(REPO_ROOT / "scripts"))
    import check_docs_consistency as checker

    for name in (*checker.REQUIRED_FILES, *checker.SUPPORT_FILES):
        destination = tmp_path / name
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(REPO_ROOT / name, destination)
    return tmp_path


@pytest.mark.parametrize(
    ("name", "old", "new", "diagnostic"),
    [
        ("README.md", "(quickstart/README.md)", "(quickstart/missing.md)", "canonical link"),
        (
            "quickstart/README.md",
            "Public parameter types are `float`, `int`, `bool` and `categorical`.",
            "Public parameter types supported: `float`, `int`.",
            "parameter",
        ),
        (
            "templates/README.md",
            "| `bo_client_demo` | `rbf_proxy` | none |",
            "| `bo_client_demo` | `rbf_proxy` | `ax` |",
            "backend capability",
        ),
        (
            "templates/README.md",
            "| `bo_client` | `rbf_proxy` | `gp`, `ax` |",
            "| `bo_client` | `rbf_proxy` | `gp` |",
            "backend capability",
        ),
        (
            "templates/README.md",
            "Auth-protected preview routes",
            "Reserved no-op preview flag",
            "active service-registry",
        ),
        (
            "docs/how-it-works.md",
            "Active preview-service registry gates",
            "Reserved no-op preview flags",
            "active service-registry",
        ),
        ("PILOT.md", "contact@looptimum.io", "contact@looptimum.com", "contact email"),
        ("docs/type-safety.md", "- `scripts/check_release.py`", "", "mypy scope"),
    ],
)
def test_docs_guard_rejects_capability_drift(
    docs_fixture: Path,
    name: str,
    old: str,
    new: str,
    diagnostic: str,
) -> None:
    target = docs_fixture / name
    text = target.read_text(encoding="utf-8")
    assert old in text
    target.write_text(text.replace(old, new), encoding="utf-8")
    proc = subprocess.run(
        [sys.executable, str(DOCS_CONSISTENCY_SCRIPT), "--root", str(docs_fixture)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 1, proc.stdout + proc.stderr
    assert name in proc.stdout
    assert diagnostic in proc.stdout


def test_docs_guard_accepts_pointer_index_and_descriptive_headings(docs_fixture: Path) -> None:
    (docs_fixture / "docs" / "README.md").write_text("[Task map](./index.md)\n", encoding="utf-8")
    root = docs_fixture / "README.md"
    root.write_text(root.read_text().replace("## Inspect the evidence", "## Research results"))
    proc = subprocess.run(
        [sys.executable, str(DOCS_CONSISTENCY_SCRIPT), "--root", str(docs_fixture)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
