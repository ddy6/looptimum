from __future__ import annotations

import hashlib
import json
import math
import os
import re
import shlex
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
QUICKSTART = REPO_ROOT / "quickstart" / "README.md"
START = "<!-- portable-quickstart:start -->"
END = "<!-- portable-quickstart:end -->"


def _command_block(markdown: str) -> str:
    if markdown.count(START) != 1 or markdown.count(END) != 1:
        raise ValueError("quickstart must have exactly one marked command block")
    selected = markdown.split(START, 1)[1].split(END, 1)[0].strip()
    match = re.fullmatch(r"```bash\n(.*?)\n```", selected, re.DOTALL)
    if match is None:
        raise ValueError("marked quickstart must contain one Bash fence")
    return match.group(1) + "\n"


def _inventory(root: Path) -> dict[str, str]:
    return {
        str(path.relative_to(root)): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in root.rglob("*")
        if path.is_file()
    }


@pytest.fixture
def walkthrough(tmp_path: Path) -> tuple[Path, Path, dict[str, str]]:
    source = tmp_path / "source"
    for name in ("_shared", "bo_client"):
        shutil.copytree(
            REPO_ROOT / "templates" / name,
            source / "templates" / name,
            ignore=shutil.ignore_patterns("__pycache__", "*.pyc", ".pytest_cache"),
        )
    shutil.copy2(REPO_ROOT / "LICENSE", source / "LICENSE")
    # Ignored history must stay in the fixture, never leak into the campaign.
    template = source / "templates" / "bo_client"
    for relative in ("state/bo_state.json", "state/trials/old/manifest.json"):
        path = template / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text('{"old_campaign_marker": true}\n', encoding="utf-8")
    tools = tmp_path / "bin"
    tools.mkdir()
    python = tools / "python3"
    python.write_text(
        f'#!/bin/sh\nexec {shlex.quote(sys.executable)} -B -E -s -S "$@"\n',
        encoding="utf-8",
    )
    python.chmod(0o755)
    campaigns = tmp_path / "campaigns"
    campaigns.mkdir()
    env = dict(os.environ, PATH=f"{tools}{os.pathsep}{os.environ['PATH']}", TMPDIR=str(campaigns))
    probe = subprocess.run(
        [
            str(python),
            "-c",
            "import importlib.util; "
            "assert all(importlib.util.find_spec(m) is None "
            "for m in ('torch', 'botorch', 'gpytorch', 'ax', 'numpy', 'scipy'))",
        ],
        cwd=source,
        env=env,
        capture_output=True,
        text=True,
        timeout=15,
    )
    assert probe.returncode == 0, probe.stderr
    return source, campaigns, env


def _run_block(
    markdown: str, source: Path, env: dict[str, str]
) -> subprocess.CompletedProcess[str]:
    before = _inventory(source)
    result = subprocess.run(
        ["bash", "-c", _command_block(markdown)],
        cwd=source,
        env=env,
        capture_output=True,
        text=True,
        timeout=45,
    )
    assert _inventory(source) == before, "documented commands mutated their source template"
    return result


def _status_objects(stdout: str) -> list[dict]:
    decoder = json.JSONDecoder()
    objects = []
    for match in re.finditer(r"(?m)^\{", stdout):
        value, _ = decoder.raw_decode(stdout[match.start() :])
        if "observations" in value and "pending" in value:
            objects.append(value)
    return objects


def test_documented_portable_quickstart(walkthrough: tuple[Path, Path, dict[str, str]]) -> None:
    source, campaigns, env = walkthrough
    proc = _run_block(QUICKSTART.read_text(encoding="utf-8"), source, env)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    initial, final = _status_objects(proc.stdout)
    assert (initial["observations"], initial["pending"]) == (0, 0)
    assert (final["observations"], final["pending"]) == (1, 0)
    (campaign,) = campaigns.iterdir()
    suggestion = json.loads((campaign / "suggestion.json").read_text())
    result = json.loads((campaign / "result.json").read_text())
    assert (result["trial_id"], result["params"]) == (suggestion["trial_id"], suggestion["params"])
    assert result["status"] == "ok"
    assert math.isfinite(result["objectives"]["loss"])
    state_path = campaign / "state" / "bo_state.json"
    state = json.loads(state_path.read_text())
    assert len(state["observations"]) == 1
    assert state["pending"] == []
    assert state["next_trial_id"] == suggestion["trial_id"] + 1
    assert state["best"]["trial_id"] == suggestion["trial_id"]
    assert not (campaign / "state" / "trials" / "old").exists()
    assert (campaign / "LICENSE").read_bytes() == (REPO_ROOT / "LICENSE").read_bytes()
    config = json.loads((campaign / "bo_config.json").read_text())
    assert (campaign / "vendor" / "looptimum_shared" / "contract.py").is_file()
    for key, relative in config["paths"].items():
        if key.endswith("_schema_file"):
            assert (campaign / relative).is_file()

    replay = subprocess.run(
        [
            "python3",
            str(campaign / "run_bo.py"),
            "ingest",
            "--project-root",
            str(campaign),
            "--results-file",
            str(campaign / "result.json"),
        ],
        cwd=campaigns,
        env=env,
        capture_output=True,
        text=True,
        timeout=15,
    )
    assert replay.returncode == 0, replay.stdout + replay.stderr
    assert json.loads(state_path.read_text()) == state


def test_documented_quickstart_detects_broken_command(
    walkthrough: tuple[Path, Path, dict[str, str]],
) -> None:
    source, _, env = walkthrough
    markdown = QUICKSTART.read_text(encoding="utf-8").replace(
        "scripts/synthetic_experiment.py", "scripts/missing_evaluator.py"
    )
    proc = _run_block(markdown, source, env)
    assert proc.returncode != 0
    assert "missing_evaluator.py" in proc.stderr


@pytest.mark.parametrize("markdown", ["no markers", f"{START}\n{START}\n{END}"])
def test_documented_quickstart_requires_one_marked_block(markdown: str) -> None:
    with pytest.raises(ValueError, match="exactly one"):
        _command_block(markdown)
