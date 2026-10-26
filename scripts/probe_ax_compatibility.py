#!/usr/bin/env python3
"""Exercise the optional Ax stack using public APIs; write a portable JSON receipt."""

from __future__ import annotations

import argparse
import json
import math
import platform
import tempfile
import time
from importlib.metadata import version
from pathlib import Path
from typing import Any


def run_probe() -> dict[str, Any]:
    import numpy as np
    import torch
    from ax.api.client import Client
    from ax.api.configs import RangeParameterConfig

    started = time.perf_counter()
    torch.set_num_threads(1)
    if torch.version.cuda is not None:
        raise AssertionError("CPU installation probe found a CUDA Torch build")
    client = Client()
    client.configure_experiment(
        name="looptimum_compatibility_probe",
        parameters=[
            RangeParameterConfig(name="x", parameter_type="float", bounds=(0.0, 1.0)),
            RangeParameterConfig(name="y", parameter_type="float", bounds=(0.0, 1.0)),
        ],
    )
    client.configure_optimization(objective="-loss")
    client.configure_generation_strategy(
        method="fast",
        initialization_budget=3,
        min_observed_initialization_trials=3,
        initialization_random_seed=17,
        initialize_with_center=False,
        allow_exceeding_initialization_budget=False,
        torch_device="cpu",
    )
    initial = client.get_next_trials(max_trials=3)
    if len(initial) != 3:
        raise AssertionError(f"Expected three initialization trials, received {len(initial)}")
    for index, params in initial.items():
        x, y = float(params["x"]), float(params["y"])
        client.complete_trial(trial_index=index, raw_data={"loss": (x - 0.3) ** 2 + (y - 0.7) ** 2})

    # Save before a real model-guided step, then compare a separately restored client.
    with tempfile.TemporaryDirectory(prefix="looptimum-ax-probe-") as directory:
        snapshot = Path(directory) / "client.json"
        client.save_to_json_file(filepath=str(snapshot))
        restored = Client.load_from_json_file(filepath=str(snapshot))
        np.random.seed(101)
        torch.manual_seed(101)
        before = time.perf_counter()
        uninterrupted = client.get_next_trials(max_trials=1)
        model_step_seconds = time.perf_counter() - before
        np.random.seed(101)
        torch.manual_seed(101)
        resumed = restored.get_next_trials(max_trials=1)
        if set(uninterrupted) != set(resumed):
            raise AssertionError("Restart changed the Ax trial index")
        for index, params in uninterrupted.items():
            for name, value in params.items():
                if not math.isclose(float(value), float(resumed[index][name]), abs_tol=1e-7):
                    raise AssertionError("Restart changed the seeded model-guided proposal")
        client.save_to_json_file(filepath=str(snapshot))
        saved = json.loads(snapshot.read_text())
        if "BoTorch" not in json.dumps(saved):
            raise AssertionError("Probe did not reach a serialized BoTorch generation strategy")

        running_index = next(iter(uninterrupted))
        client.mark_trial_failed(trial_index=running_index, failed_reason="probe_failure")
        abandoned = client.attach_trial(parameters={"x": 0.2, "y": 0.4})
        client.mark_trial_abandoned(trial_index=abandoned)
        imported = client.attach_trial(parameters={"x": 0.6, "y": 0.8})
        client.complete_trial(trial_index=imported, raw_data={"loss": 0.1})
        client.save_to_json_file(filepath=str(snapshot))
        final = Client.load_from_json_file(filepath=str(snapshot))
        summary = json.loads(final.summarize().to_json(orient="records"))

    return {
        "probe_version": 1,
        "platform": {
            "system": platform.system(),
            "machine": platform.machine(),
            "python": platform.python_version(),
        },
        "torch_device": "cpu",
        "torch_cuda_build": torch.version.cuda,
        "versions": {
            name: version(name)
            for name in ("ax-platform", "botorch", "torch", "gpytorch", "numpy", "scipy")
        },
        "initialization_trials": len(initial),
        "model_guided_proposal": uninterrupted,
        "seeded_restart_matches": True,
        "model_step_seconds": model_step_seconds,
        "elapsed_seconds": time.perf_counter() - started,
        "summary": summary,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    receipt = run_probe()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(receipt, indent=2, allow_nan=False) + "\n")
    print(f"Ax compatibility probe passed; receipt: {args.output}")


if __name__ == "__main__":
    main()
