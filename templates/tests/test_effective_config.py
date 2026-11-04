"""Current examples and legacy ignored-field diagnostics remain compatible."""

from __future__ import annotations

import copy
import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location(
    "effective_backend", ROOT / "templates/_shared/optimizer_backend.py"
)
BACKEND = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(BACKEND)
LEGACY = json.loads((Path(__file__).parent / "fixtures/legacy_ignored_config.json").read_text())
SAMPLES = (
    "templates/bo_client/bo_config.json",
    "templates/bo_client_demo/bo_config.json",
    "templates/bo_client_full/bo_config.json",
    "docs/examples/warm_start/bo_config.json",
    "docs/examples/batch_async/bo_config.json",
    "docs/examples/multi_objective/bo_config.json",
    "examples/snappyhexmesh_campaign/project/bo_config.json",
)
STOPPING = ["stopping.min_improvement", "stopping.patience_trials"]


@pytest.mark.parametrize("name", SAMPLES)
def test_current_examples_do_not_advertise_inert_controls(name):
    cfg = json.loads((ROOT / name).read_text())
    assert not {"min_improvement", "patience_trials"}.intersection(cfg.get("stopping", {}))
    if name in (SAMPLES[0], SAMPLES[-1]):
        assert "gp_model" not in cfg["surrogate"]


@pytest.mark.parametrize("template", ["bo_client", "bo_client_demo", "bo_client_full"])
def test_legacy_diagnostics_report_only_supplied_inactive_settings(template):
    cfg = copy.deepcopy(LEGACY)
    before = copy.deepcopy(cfg)
    info = BACKEND.optimizer_diagnostics(cfg, template=template)
    expected = STOPPING + (["surrogate.gp_model"] if template == "bo_client" else [])
    assert info["inactive_legacy_settings"] == expected
    assert BACKEND.optimizer_diagnostics(cfg, template=template) == info
    assert cfg == before
    cfg.pop("stopping")
    cfg["surrogate"].pop("gp_model")
    assert "inactive_legacy_settings" not in BACKEND.optimizer_diagnostics(cfg, template=template)


@pytest.mark.parametrize("template", ["bo_client", "bo_client_full"])
def test_ax_retains_legacy_diagnostics_and_does_not_duplicate_surrogate(template, monkeypatch):
    monkeypatch.setattr(BACKEND, "dependency_versions", lambda: {"ax-platform": None})
    cfg = {**copy.deepcopy(LEGACY), "optimizer": {"backend": "ax"}}
    info = BACKEND.optimizer_diagnostics(cfg, template=template)
    assert not info["available"]
    assert info["inactive_legacy_settings"] == [
        "surrogate",
        "acquisition",
        "initial_random_trials",
        "candidate_pool_size",
        *STOPPING,
    ]
    assert (
        BACKEND.optimizer_diagnostics({"optimizer": {"backend": "ax"}}, template=template)[
            "inactive_legacy_settings"
        ]
        == []
    )


@pytest.mark.parametrize(
    "cfg,expected",
    [
        ({"stopping": None, "surrogate": []}, None),
        ({"stopping": "old", "surrogate": None}, None),
        ({"stopping": {"min_improvement": "unused"}}, ["stopping.min_improvement"]),
        ({"surrogate": {"gp_model": False}}, ["surrogate.gp_model"]),
        ({"stopping": {"unknown": 1}}, None),
    ],
)
def test_diagnostics_do_not_validate_or_crash_on_ignored_legacy_extras(cfg, expected):
    info = BACKEND.optimizer_diagnostics(cfg, template="bo_client")
    assert info.get("inactive_legacy_settings") == expected


@pytest.mark.parametrize("template", ["bo_client", "bo_client_demo", "bo_client_full"])
def test_portable_legacy_sample_and_clean_config_generate_identical_params(tmp_path, template):
    suggestions = []
    for legacy in (False, True):
        project = tmp_path / str(legacy)
        subprocess.run(
            [
                sys.executable,
                str(ROOT / "templates/_shared/vendor_copy.py"),
                str(ROOT / "templates" / template),
                str(project),
            ],
            check=True,
            capture_output=True,
            timeout=15,
        )
        cfg_path = project / "bo_config.json"
        cfg = json.loads(cfg_path.read_text())
        if legacy:
            cfg["stopping"] = copy.deepcopy(LEGACY["stopping"])
            if template == "bo_client":
                cfg["surrogate"]["gp_model"] = copy.deepcopy(LEGACY["surrogate"]["gp_model"])
        cfg_path.write_text(json.dumps(cfg))

        def run(*args):
            return subprocess.run(
                [
                    sys.executable,
                    "-B",
                    str(project / "run_bo.py"),
                    *args,
                    "--project-root",
                    str(project),
                ],
                cwd=tmp_path,
                capture_output=True,
                text=True,
                timeout=15,
                check=True,
            )

        run("validate")
        info = json.loads(run("doctor", "--json").stdout)["optimizer"]
        if legacy:
            expected = STOPPING + (["surrogate.gp_model"] if template == "bo_client" else [])
            assert info["inactive_legacy_settings"] == expected
        else:
            assert "inactive_legacy_settings" not in info
        suggestions.append(json.loads(run("suggest", "--json-only").stdout)["params"])
    assert suggestions[0] == suggestions[1]
