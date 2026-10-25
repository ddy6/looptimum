"""Lean tests of comparison fairness, measurement, accounting, and restart behavior."""

from __future__ import annotations

import argparse
import copy
import subprocess
import sys

import pytest

from benchmarks.backend_comparison import run, workloads


def plan() -> dict:
    return run.protocol(
        argparse.Namespace(
            budget=3,
            initialization=1,
            seeds=[17],
            backends=["random", "proxy"],
            workloads=["smooth_quadratic"],
            workers=1,
            evaluator_seconds=3600,
        )
    )


def trial(ordinal, observed, latent, params):
    return {
        "trial_id": ordinal,
        "params": params,
        "observed": observed,
        "latent": latent,
        "status": "ok",
        "suggest": {"wall_seconds": 0.1 * ordinal, "cpu_seconds": 0.05, "peak_process_rss_mib": 50},
        "ingest": {"wall_seconds": 0.05, "cpu_seconds": 0.01, "peak_process_rss_mib": 20},
        "decision": {"strategy": "initial_random"},
    }


def test_workload_optima_mixed_types_and_fresh_repeat_noise():
    assert workloads.latent({"x1": 0.32, "x2": 0.74}, "smooth_quadratic") == 0
    assert workloads.latent({"x1": 0.5, "x2": 0.5}, "multimodal") == 0
    pipeline = {
        "batch_size": 64,
        "workers": 4,
        "cache": True,
        "compression": "lz4",
        "buffer_mb": 64.0,
    }
    assert workloads.latent(pipeline, "pipeline") == 10
    assert not workloads.valid({**pipeline, "cache": 1}, "pipeline")
    assert not workloads.valid({**pipeline, "workers": 4.0}, "pipeline")
    assert not workloads.valid({**pipeline, "buffer_mb": float("nan")}, "pipeline")
    params = {"x1": 0.32, "x2": 0.74}
    first = workloads.measure(params, "noisy_quadratic", 17, 1)
    assert first == workloads.measure(params, "noisy_quadratic", 17, 1)
    assert first["observed"] != workloads.measure(params, "noisy_quadratic", 17, 2)["observed"]
    assert first["noise_std"] > 0


def test_backend_configuration_and_phase_checks_prevent_silent_fallback():
    protocol = plan()
    for backend in ("random", "proxy", "gp"):
        config = run.configuration(backend, 17, protocol)
        assert config["optimizer"]["backend"] == "legacy"
        assert config["initial_random_trials"] == (3 if backend == "random" else 1)
    assert run.configuration("gp", 17, protocol)["surrogate"]["type"] == "gp"
    assert (
        run.configuration("ax_sobol", 17, protocol)["optimizer"]["ax"]["initialization_budget"] == 3
    )
    assert run.configuration("ax", 17, protocol)["optimizer"]["ax"]["initialization_budget"] == 1
    assert not run.decision_matches("gp", 2, {"surrogate_backend": "rbf_proxy"}, protocol)
    assert not run.decision_matches(
        "ax", 2, {"surrogate_backend": "ax", "generation_node": "Sobol"}, protocol
    )
    assert run.decision_matches(
        "ax", 2, {"surrogate_backend": "ax", "generation_node": "MBM"}, protocol
    )


def test_quality_uses_the_observed_incumbent_not_an_oracle_or_lucky_noisy_score():
    traces = [
        trial(1, -1, 0.3, {"x1": 0.1}),
        trial(2, 0.2, 0.1, {"x1": 0.2}),
        trial(3, 0.25, 0.1, {"x1": 0.2}),
    ]
    result = run.metrics(traces, "noisy_quadratic", plan())
    assert result["best_observed"] == -1
    assert result["selected_regret"] == 0.3 and result["best_latent_seen"] == 0.1
    assert result["repeat_rate"] == pytest.approx(1 / 3)
    assert result["evaluations"] == 3
    assert result["controller_wall_seconds"] == pytest.approx(0.75)
    assert result["modeled_campaign_seconds"] == pytest.approx(10800.75)
    assert result["p95_suggest_wall_seconds"] == pytest.approx(0.29)


def test_incomplete_failed_or_duplicate_seed_sets_never_pass_or_hide_survivor_bias():
    protocol = plan()
    metrics = run.metrics([trial(1, 0.1, 0.1, {"x1": 0.1})], "smooth_quadratic", protocol)
    complete = {
        "workload": "smooth_quadratic",
        "backend": "random",
        "seed": 17,
        "status": "complete",
        **metrics,
    }
    failed = {
        "workload": "smooth_quadratic",
        "backend": "proxy",
        "seed": 17,
        "status": "failed",
        "error": "fit failed",
    }
    summary = run.summarize(protocol, [complete, failed])
    assert summary["passed"] is False and "incomplete" in run.report(summary)
    assert "selected_regret" not in summary["groups"][1]
    assert not run.summarize(protocol, [complete, complete])["passed"]
    assert not run.summarize(protocol, [complete])["passed"]


def test_measurement_supervisor_captures_child_resources_and_kills_timed_out_group(tmp_path):
    for timeout, source in ((5, "print('measured')"), (0.05, "import time; time.sleep(60)")):
        request = tmp_path / "request.json"
        output = tmp_path / "measurement.json"
        run.write(
            request,
            {"command": [sys.executable, "-c", source], "cwd": str(tmp_path), "timeout": timeout},
        )
        subprocess.run(
            [
                sys.executable,
                "-m",
                "benchmarks.backend_comparison.measure_command",
                "--request",
                str(request),
                "--output",
                str(output),
            ],
            cwd=run.ROOT,
            check=True,
        )
        result = run.read(output)
        assert result["wall_seconds"] > 0 and result["peak_process_rss_mib"] > 0
        assert result["timed_out"] is (timeout < 1)
        if timeout > 1:
            assert result["returncode"] == 0 and result["stdout"].strip() == "measured"
        else:
            assert result["returncode"] != 0


def test_case_resumes_after_suggestion_without_replaying_an_evaluation(tmp_path, monkeypatch):
    protocol = plan()
    original = run.invoke

    def stop_before_ingest(directory, ordinal, command, extra, seed, plan):
        if command == "ingest":
            raise KeyboardInterrupt("simulate interrupted benchmark driver")
        return original(directory, ordinal, command, extra, seed, plan)

    monkeypatch.setattr(run, "invoke", stop_before_ingest)
    with pytest.raises(KeyboardInterrupt):
        run.run_case(tmp_path, "smooth_quadratic", "random", 17, protocol)
    directory = tmp_path / "runs/smooth_quadratic/random/17"
    first = run.read(directory / "trials/001.json")
    assert run.read(directory / "controller/state/bo_state.json")["pending"][0]["trial_id"] == 1
    monkeypatch.setattr(run, "invoke", original)
    completed = run.run_case(tmp_path, "smooth_quadratic", "random", 17, protocol)
    assert completed["status"] == "complete" and completed["evaluations"] == 3
    assert run.read(directory / "trials/001.json")["observed"] == first["observed"]
    assert run.run_case(tmp_path, "smooth_quadratic", "random", 17, protocol) == completed


def test_failed_case_is_retained_instead_of_retried_selectively(tmp_path, monkeypatch):
    def fail(*args, **kwargs):
        raise RuntimeError("backend unavailable")

    monkeypatch.setattr(run, "invoke", fail)
    first = run.run_case(tmp_path, "smooth_quadratic", "random", 17, plan())
    assert first["status"] == "failed"
    monkeypatch.setattr(run, "invoke", lambda *args: pytest.fail("failed case must not be rerun"))
    assert run.run_case(tmp_path, "smooth_quadratic", "random", 17, plan()) == first


def test_cli_checkpoint_resume_protocol_guard_and_golden_protection(tmp_path):
    command = [
        sys.executable,
        "-m",
        "benchmarks.backend_comparison.run",
        "--output-dir",
        str(tmp_path / "evidence"),
        "--budget",
        "3",
        "--initialization",
        "1",
        "--seeds",
        "17",
        "--backends",
        "random,proxy",
        "--workloads",
        "smooth_quadratic",
        "--workers",
        "1",
    ]
    first = subprocess.run(command, cwd=run.ROOT, capture_output=True, text=True)
    assert first.returncode == 0, first.stdout + first.stderr
    summary = run.read(tmp_path / "evidence/summary.json")
    assert summary["passed"] is True and summary["reference_protocol"] is False
    second = subprocess.run([*command, "--resume"], cwd=run.ROOT, capture_output=True, text=True)
    assert (
        second.returncode == 0
        and run.read(tmp_path / "evidence/summary.json")["results"] == summary["results"]
    )
    changed = subprocess.run(
        [*command, "--resume", "--budget", "4"], cwd=run.ROOT, capture_output=True, text=True
    )
    assert changed.returncode != 0 and "exact original protocol" in changed.stderr
    forbidden = subprocess.run(
        [*command, "--write-summary", str(run.ROOT / "benchmarks/summary.json")],
        cwd=run.ROOT,
        capture_output=True,
        text=True,
    )
    assert forbidden.returncode != 0 and "must not be overwritten" in forbidden.stderr


def test_resource_gate_rejects_excessive_overhead_without_a_quality_win_requirement():
    protocol = plan()
    record = {
        "workload": "smooth_quadratic",
        "seed": 17,
        "status": "complete",
        **run.metrics(
            [trial(index, 0.2, 0.2, {"x1": index / 10}) for index in (1, 2, 3)],
            "smooth_quadratic",
            protocol,
        ),
    }
    baseline = {**record, "backend": "random"}
    proxy = {**copy.deepcopy(record), "backend": "proxy", "selected_regret": 0.4}
    assert run.summarize(protocol, [baseline, proxy])["passed"] is True
    proxy["peak_process_rss_mib"] = 5000
    summary = run.summarize(protocol, [baseline, proxy])
    assert summary["gates"]["memory"] is False and summary["passed"] is False


def test_published_errors_exclude_local_prefixes_without_hiding_failure_or_changing_scores():
    original = [
        {
            "workload": "pipeline",
            "backend": "gp",
            "seed": 97,
            "status": "failed",
            "allocated_evaluations": 11,
            "error": f"{sys.prefix}/lib/site-packages/botorch/fit.py\nERROR: All attempts to fit the model have failed.",
        }
    ]
    published = run.publication_results(original)
    assert str(sys.prefix) not in published[0]["error"]
    assert "All attempts to fit the model have failed" in published[0]["error"]
    assert published[0]["status"] == "failed" and published[0]["allocated_evaluations"] == 11
    assert str(sys.prefix) in original[0]["error"]
    summary = run.summarize(plan(), published)
    text = run.report(summary)
    assert "acceptance gate remains unmet" in text and "not established" in text
    assert summary["passed"] is False


def test_reference_artifacts_retain_failed_cells_and_valid_diagnostic_inputs():
    summary_path = run.ROOT / "benchmarks/backend_comparison/summary.json"
    summary = run.read(summary_path)
    protocol = summary["protocol"]
    assert summary["reference_protocol"] is True
    assert len(summary["results"]) == len(protocol["workloads"]) * len(protocol["backends"]) * len(
        protocol["seeds"]
    )
    assert len(
        {(row["workload"], row["backend"], row["seed"]) for row in summary["results"]}
    ) == len(summary["results"])
    failed = [row for row in summary["results"] if row["status"] != "complete"]
    if failed:
        assert summary["passed"] is False
    for group in summary["groups"]:
        if group["completed_seeds"] < group["expected_seeds"]:
            assert "selected_regret" not in group
    assert "/Users/" not in summary_path.read_text()
    assert "/home/" not in summary_path.read_text()
    fixture = run.read(run.ROOT / "benchmarks/backend_comparison/gp_pipeline_seed97_failure.json")
    assert [row["trial_id"] for row in fixture["observations"]] == list(range(1, 12))
    assert fixture["fit_seed"] == fixture["seed"] + fixture["failed_public_trial_id"]
    for row in fixture["observations"]:
        assert workloads.valid(row["params"], "pipeline")
        assert row["objectives"]["loss"] == pytest.approx(
            workloads.latent(row["params"], "pipeline")
        )
