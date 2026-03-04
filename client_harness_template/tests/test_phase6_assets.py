from __future__ import annotations

import json
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
GOLDEN_LOG = REPO_ROOT / "docs" / "examples" / "decision_trace" / "golden_acquisition_log.jsonl"
REGEN_SCRIPT = REPO_ROOT / "docs" / "examples" / "decision_trace" / "regenerate_golden_log.sh"


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
