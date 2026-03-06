from __future__ import annotations

import subprocess
import sys
from pathlib import Path

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


def test_readme_includes_phase9_trust_anchors_and_badges() -> None:
    text = TOP_LEVEL_README.read_text(encoding="utf-8")
    assert "## Trust Anchors" in text
    assert "actions/workflows/ci.yml/badge.svg" in text
    assert "img.shields.io/github/v/release/ddy6/looptimum" in text
    assert "docs/quick-reference.md" in text
    assert "quickstart/etl-pipeline-knob-tuning.md" in text


def test_ci_workflow_runs_public_docs_consistency_checks() -> None:
    text = CI_WORKFLOW.read_text(encoding="utf-8")
    assert "Validate internal markdown links" in text
    assert "python scripts/check_internal_links.py --paths README.md docs quickstart" in text
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
