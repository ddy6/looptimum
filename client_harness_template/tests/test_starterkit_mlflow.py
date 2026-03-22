from __future__ import annotations

import importlib
import sys
import types
from pathlib import Path

import pytest
from test_starterkit_tracking import _write_tracker_fixture

REPO_ROOT = Path(__file__).resolve().parents[2]
HARNESS_DIR = REPO_ROOT / "client_harness_template"
if str(HARNESS_DIR) not in sys.path:
    sys.path.insert(0, str(HARNESS_DIR))

starterkit_mlflow = importlib.import_module("starterkit_mlflow")


class _FakeMLflowRun:
    def __init__(self) -> None:
        self.info = types.SimpleNamespace(run_id="mlflow-run-1")

    def __enter__(self) -> _FakeMLflowRun:
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        return None


class _FakeMLflowModule:
    def __init__(self) -> None:
        self.tracking_uri: str | None = None
        self.experiment_name: str | None = None
        self.run_name: str | None = None
        self.metrics: dict[str, float] | None = None
        self.params: dict[str, str] | None = None
        self.tags: dict[str, str] | None = None
        self.logged_dict_path: str | None = None
        self.logged_dict_payload: dict[str, object] | None = None
        self.logged_artifacts: list[tuple[str, str | None]] = []

    def set_tracking_uri(self, value: str) -> None:
        self.tracking_uri = value

    def set_experiment(self, value: str) -> None:
        self.experiment_name = value

    def start_run(self, *, run_name: str | None = None) -> _FakeMLflowRun:
        self.run_name = run_name
        return _FakeMLflowRun()

    def log_metrics(self, metrics: dict[str, float]) -> None:
        self.metrics = dict(metrics)

    def log_params(self, params: dict[str, str]) -> None:
        self.params = dict(params)

    def set_tags(self, tags: dict[str, str]) -> None:
        self.tags = dict(tags)

    def log_dict(self, payload: dict[str, object], artifact_file: str) -> None:
        self.logged_dict_payload = dict(payload)
        self.logged_dict_path = artifact_file

    def log_artifact(self, path: str, artifact_path: str | None = None) -> None:
        self.logged_artifacts.append((path, artifact_path))


def test_log_to_mlflow_rejects_missing_dependency(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delitem(sys.modules, "mlflow", raising=False)

    real_import = __import__

    def _raising_import(name: str, *args: object, **kwargs: object) -> object:
        if name == "mlflow":
            raise ModuleNotFoundError("No module named 'mlflow'")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr("builtins.__import__", _raising_import)

    with pytest.raises(RuntimeError, match="mlflow is not installed"):
        starterkit_mlflow.log_to_mlflow("/tmp/does-not-matter")


def test_log_to_mlflow_uses_canonical_snapshot_payload(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    project_root = tmp_path / "campaign"
    _write_tracker_fixture(project_root)
    fake_mlflow = _FakeMLflowModule()
    monkeypatch.setitem(sys.modules, "mlflow", fake_mlflow)

    result = starterkit_mlflow.log_to_mlflow(
        project_root,
        experiment_name="looptimum-tests",
        run_name="tracker-sync",
        tracking_uri="file:///tmp/mlruns",
    )

    assert result["backend"] == "mlflow"
    assert result["run_id"] == "mlflow-run-1"
    assert fake_mlflow.tracking_uri == "file:///tmp/mlruns"
    assert fake_mlflow.experiment_name == "looptimum-tests"
    assert fake_mlflow.run_name == "tracker-sync"
    assert fake_mlflow.metrics is not None
    assert fake_mlflow.metrics["looptimum.observations"] == 1.0
    assert fake_mlflow.tags is not None
    assert fake_mlflow.tags["looptimum.best_trial_id"] == "2"
    assert fake_mlflow.logged_dict_path == "looptimum_snapshot.json"
    assert fake_mlflow.logged_dict_payload is not None
    assert fake_mlflow.logged_dict_payload["best"]["trial_id"] == 2
    assert len(fake_mlflow.logged_artifacts) >= 3
