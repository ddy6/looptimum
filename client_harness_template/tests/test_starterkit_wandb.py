from __future__ import annotations

import importlib
import sys
from pathlib import Path

import pytest
from test_starterkit_tracking import _write_tracker_fixture

REPO_ROOT = Path(__file__).resolve().parents[2]
HARNESS_DIR = REPO_ROOT / "client_harness_template"
if str(HARNESS_DIR) not in sys.path:
    sys.path.insert(0, str(HARNESS_DIR))

starterkit_wandb = importlib.import_module("starterkit_wandb")


class _FakeWandbArtifact:
    def __init__(self, name: str, type: str) -> None:
        self.name = name
        self.type = type
        self.files: list[tuple[str, str | None]] = []

    def add_file(self, path: str, name: str | None = None) -> None:
        self.files.append((path, name))


class _FakeConfig:
    def __init__(self) -> None:
        self.payload: dict[str, object] = {}

    def update(self, value: dict[str, object]) -> None:
        self.payload.update(value)


class _FakeSummary:
    def __init__(self) -> None:
        self.payload: dict[str, object] = {}

    def update(self, value: dict[str, object]) -> None:
        self.payload.update(value)


class _FakeWandbRun:
    def __init__(self) -> None:
        self.id = "wandb-run-1"
        self.config = _FakeConfig()
        self.summary = _FakeSummary()
        self.logged_history: list[dict[str, float]] = []
        self.logged_artifacts: list[_FakeWandbArtifact] = []
        self.finished = False

    def log(self, payload: dict[str, float]) -> None:
        self.logged_history.append(dict(payload))

    def log_artifact(self, artifact: _FakeWandbArtifact) -> None:
        self.logged_artifacts.append(artifact)

    def finish(self) -> None:
        self.finished = True


class _FakeWandbModule:
    def __init__(self) -> None:
        self.init_kwargs: dict[str, object] | None = None
        self.run = _FakeWandbRun()

    def init(self, **kwargs: object) -> _FakeWandbRun:
        self.init_kwargs = dict(kwargs)
        return self.run

    def Artifact(self, name: str, type: str) -> _FakeWandbArtifact:  # noqa: N802
        return _FakeWandbArtifact(name=name, type=type)


def test_log_to_wandb_rejects_missing_dependency(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delitem(sys.modules, "wandb", raising=False)

    real_import = __import__

    def _raising_import(name: str, *args: object, **kwargs: object) -> object:
        if name == "wandb":
            raise ModuleNotFoundError("No module named 'wandb'")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr("builtins.__import__", _raising_import)

    with pytest.raises(RuntimeError, match="wandb is not installed"):
        starterkit_wandb.log_to_wandb("/tmp/does-not-matter", project="looptimum-tests")


def test_log_to_wandb_uses_snapshot_and_artifact_contract(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    project_root = tmp_path / "campaign"
    _write_tracker_fixture(project_root)
    fake_wandb = _FakeWandbModule()
    monkeypatch.setitem(sys.modules, "wandb", fake_wandb)

    result = starterkit_wandb.log_to_wandb(
        project_root,
        project="looptimum-tests",
        entity="client-team",
        run_name="tracker-sync",
        mode="offline",
    )

    assert result["backend"] == "wandb"
    assert result["run_id"] == "wandb-run-1"
    assert fake_wandb.init_kwargs is not None
    assert fake_wandb.init_kwargs["project"] == "looptimum-tests"
    assert fake_wandb.init_kwargs["entity"] == "client-team"
    assert fake_wandb.run.config.payload["objective_names"] == ["loss"]
    assert fake_wandb.run.summary.payload["looptimum/top_trial_count"] == 1
    assert fake_wandb.run.logged_history[0]["looptimum/observations"] == 1.0
    assert len(fake_wandb.run.logged_artifacts) == 1
    assert fake_wandb.run.logged_artifacts[0].files
    assert fake_wandb.run.finished is True
