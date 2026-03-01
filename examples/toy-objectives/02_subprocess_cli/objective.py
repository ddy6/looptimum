#!/usr/bin/env python3
"""Toy example: subprocess/CLI integration with scalarization and failure mapping."""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any


WORKER = Path(__file__).resolve().with_name("worker_cli.py")
FAILED_SENTINEL = 1.0e9  # Directionally bad for minimize("loss")


def evaluate(params: dict[str, Any]) -> dict[str, Any]:
    """Run worker CLI, parse raw metrics, and return scalar objective + status."""
    with tempfile.TemporaryDirectory(prefix="toy_cli_eval_") as tmpdir:
        params_path = Path(tmpdir) / "params.json"
        params_path.write_text(json.dumps(params), encoding="utf-8")

        cmd = [sys.executable, str(WORKER), str(params_path)]
        proc = subprocess.run(cmd, capture_output=True, text=True)

        stdout = (proc.stdout or "").strip()
        stderr = (proc.stderr or "").strip()

        if proc.returncode == 2:
            # Synthetic invalid region. Return an explicit failed payload-friendly response.
            return {
                "objective": FAILED_SENTINEL,
                "status": "failed",
            }

        if proc.returncode != 0:
            raise RuntimeError(
                f"worker_cli failed rc={proc.returncode}; stdout={stdout!r}; stderr={stderr!r}"
            )

        metrics = json.loads(stdout)
        quality = float(metrics["quality"])
        runtime_s = float(metrics["runtime_s"])
        penalty = float(metrics["penalty"])

        # Lower is better: trade off quality and runtime with a penalty term.
        loss = (1.0 - quality) + 0.4 * runtime_s + penalty
        return {
            "objective": float(loss),
            "status": "ok",
        }

