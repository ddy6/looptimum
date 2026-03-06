from __future__ import annotations

import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
CI_KNOB_DOC = REPO_ROOT / "docs" / "ci-knob-tuning.md"
SYNC_SCRIPT = REPO_ROOT / "scripts" / "check_ci_playbook_sync.py"
CI_WORKFLOW = REPO_ROOT / ".github" / "workflows" / "ci.yml"


def test_phase7_core_assets_exist() -> None:
    assert CI_KNOB_DOC.exists(), f"missing CI knob tuning doc: {CI_KNOB_DOC}"
    assert SYNC_SCRIPT.exists(), f"missing CI playbook sync script: {SYNC_SCRIPT}"


def test_ci_knob_doc_contains_required_normative_policy() -> None:
    text = CI_KNOB_DOC.read_text(encoding="utf-8")
    assert "one controller/writer per `state/` path" in text
    assert "Default (recommended): CI artifacts." in text
    assert "Warm-cache mode:" in text
    assert "Default policy: top-k + median-of-repeats." in text
    assert "multiple controllers writing to the same `state/` path" in text


def test_ci_workflow_runs_ci_playbook_sync_check() -> None:
    assert CI_WORKFLOW.exists(), f"missing CI workflow: {CI_WORKFLOW}"
    text = CI_WORKFLOW.read_text(encoding="utf-8")
    assert "Validate CI playbook sync" in text
    assert "python scripts/check_ci_playbook_sync.py" in text


def test_sync_script_passes_on_current_doc() -> None:
    proc = subprocess.run(
        [sys.executable, str(SYNC_SCRIPT), "--root", str(REPO_ROOT)],
        cwd=str(REPO_ROOT),
        text=True,
        capture_output=True,
        check=False,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
