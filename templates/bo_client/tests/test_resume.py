from __future__ import annotations

import json

from conftest import parse_suggestion, run_cmd


def test_resume_restores_state_and_trial_ids(template_copy) -> None:
    first = parse_suggestion(run_cmd(template_copy, "suggest").stdout)
    payload = {
        "trial_id": first["trial_id"],
        "params": first["params"],
        "objectives": {"loss": 0.2},
        "status": "ok",
    }
    p = template_copy / "examples" / "_resume_ingest.json"
    p.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    run_cmd(template_copy, "ingest", "--results-file", str(p))

    status = json.loads(run_cmd(template_copy, "status").stdout)
    assert status["observations"] == 1
    assert status["next_trial_id"] == 2

    second = parse_suggestion(run_cmd(template_copy, "suggest").stdout)
    assert second["trial_id"] == 2
    status2 = json.loads(run_cmd(template_copy, "status").stdout)
    assert status2["pending"] == 1


def test_demo_stops_cleanly_when_budget_exhausted(template_copy) -> None:
    run_cmd(template_copy, "demo", "--steps", "45")
    status = json.loads(run_cmd(template_copy, "status").stdout)
    cfg = json.loads((template_copy / "bo_config.json").read_text(encoding="utf-8"))
    assert status["observations"] == cfg["max_trials"]
    assert status["pending"] == 0
