from __future__ import annotations

import json
import tomllib
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
GOLDEN_LOG = REPO_ROOT / "docs" / "examples" / "decision_trace" / "golden_acquisition_log.jsonl"
REGEN_SCRIPT = REPO_ROOT / "docs" / "examples" / "decision_trace" / "regenerate_golden_log.sh"
CI_WORKFLOW = REPO_ROOT / ".github" / "workflows" / "ci.yml"
PYPROJECT = REPO_ROOT / "pyproject.toml"
TYPE_SAFETY_DOC = REPO_ROOT / "docs" / "type-safety.md"


def test_golden_acquisition_log_has_expected_shape_and_timestamps() -> None:
    assert GOLDEN_LOG.exists(), f"missing golden log: {GOLDEN_LOG}"
    lines = [
        json.loads(line)
        for line in GOLDEN_LOG.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    assert len(lines) == 8

    strategies: list[str] = []
    for idx, row in enumerate(lines, start=1):
        assert row["trial_id"] == idx
        assert row["timestamp"] == 1_700_000_000.0 + float(idx)
        decision = row["decision"]
        assert isinstance(decision, dict)
        strategies.append(str(decision["strategy"]))

    assert strategies[:6] == ["initial_random"] * 6
    assert all(strategy == "surrogate_acquisition" for strategy in strategies[6:])


def test_regeneration_script_enforces_normalized_timestamp_export() -> None:
    assert REGEN_SCRIPT.exists(), f"missing regeneration script: {REGEN_SCRIPT}"
    script_text = REGEN_SCRIPT.read_text(encoding="utf-8")
    assert "--normalize-acquisition-timestamps" in script_text
    assert "--steps 8" in script_text


def test_ci_workflow_contains_blocking_mypy_job() -> None:
    assert CI_WORKFLOW.exists(), f"missing CI workflow: {CI_WORKFLOW}"
    text = CI_WORKFLOW.read_text(encoding="utf-8")
    assert "typecheck:" in text
    assert "Type Check (mypy, py3.12)" in text
    assert "python -m mypy" in text


def test_mypy_scope_and_type_safety_doc_are_present() -> None:
    assert PYPROJECT.exists(), f"missing pyproject: {PYPROJECT}"
    payload = tomllib.loads(PYPROJECT.read_text(encoding="utf-8"))
    tool_cfg = payload.get("tool", {})
    mypy_cfg = tool_cfg.get("mypy", {})
    files = mypy_cfg.get("files")
    assert isinstance(files, list)
    assert "templates/_shared/*.py" in files
    assert "templates/bo_client/run_bo.py" in files
    assert "client_harness_template/run_one_eval.py" in files
    assert mypy_cfg.get("disallow_untyped_defs") is True
    assert mypy_cfg.get("disallow_any_generics") is True

    assert TYPE_SAFETY_DOC.exists(), f"missing type-safety doc: {TYPE_SAFETY_DOC}"
    doc_text = TYPE_SAFETY_DOC.read_text(encoding="utf-8")
    assert "Type-checking tool: `mypy`." in doc_text
    assert "Initial blocking CI gate scope" in doc_text
