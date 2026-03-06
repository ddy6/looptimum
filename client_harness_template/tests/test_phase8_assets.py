from __future__ import annotations

import json
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
BENCHMARK_README = REPO_ROOT / "benchmarks" / "README.md"
BENCHMARK_RUNNER = REPO_ROOT / "benchmarks" / "run_trial_efficiency_benchmark.py"
BENCHMARK_SUMMARY = REPO_ROOT / "benchmarks" / "summary.json"
BENCHMARK_CASE_STUDY = REPO_ROOT / "benchmarks" / "case_study.md"
BENCHMARK_SANITY = REPO_ROOT / "scripts" / "check_benchmark_sanity.py"
CI_WORKFLOW = REPO_ROOT / ".github" / "workflows" / "ci.yml"
TOP_LEVEL_README = REPO_ROOT / "README.md"


def test_phase8_benchmark_assets_exist() -> None:
    assert BENCHMARK_README.exists(), f"missing benchmarks README: {BENCHMARK_README}"
    assert BENCHMARK_RUNNER.exists(), f"missing benchmark runner: {BENCHMARK_RUNNER}"
    assert BENCHMARK_SUMMARY.exists(), f"missing benchmark summary: {BENCHMARK_SUMMARY}"
    assert BENCHMARK_CASE_STUDY.exists(), f"missing benchmark case study: {BENCHMARK_CASE_STUDY}"
    assert BENCHMARK_SANITY.exists(), f"missing benchmark sanity script: {BENCHMARK_SANITY}"


def test_benchmark_summary_shape_and_protocol_fields() -> None:
    payload = json.loads(BENCHMARK_SUMMARY.read_text(encoding="utf-8"))
    assert payload["schema_version"] == "0.1.0"
    assert payload["objective"]["id"] == "tiny_quadratic"
    metric = payload["metric"]
    assert metric["name"] == "best_objective_at_fixed_budget"
    assert int(metric["seed_count"]) == 10
    assert int(metric["required_seed_count"]) == 10

    results = payload["results"]
    assert "looptimum" in results
    assert "random_search" in results
    assert "comparison" in results

    per_seed = payload["per_seed"]
    assert isinstance(per_seed, list)
    assert len(per_seed) == 10
    sample = per_seed[0]
    assert "seed" in sample
    assert "looptimum_best_objective" in sample
    assert "random_best_objective" in sample


def test_case_study_references_summary_artifact() -> None:
    text = BENCHMARK_CASE_STUDY.read_text(encoding="utf-8")
    assert "generated directly from benchmark summary artifacts" in text
    assert "`benchmarks/summary.json`" in text


def test_ci_workflow_runs_benchmark_sanity_check() -> None:
    text = CI_WORKFLOW.read_text(encoding="utf-8")
    assert "Validate benchmark sanity" in text
    assert "python scripts/check_benchmark_sanity.py" in text


def test_readme_includes_evidence_links() -> None:
    text = TOP_LEVEL_README.read_text(encoding="utf-8")
    assert "## Evidence" in text
    assert "benchmarks/run_trial_efficiency_benchmark.py" in text
    assert "benchmarks/summary.json" in text
    assert "benchmarks/case_study.md" in text
