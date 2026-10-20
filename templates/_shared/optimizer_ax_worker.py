"""Internal isolated Ax worker. Canonical campaign files are owned by the controller."""

from __future__ import annotations

import json
import random
import sys
import tempfile
from contextlib import redirect_stdout
from pathlib import Path
from typing import Any

from optimizer_backend import AX_TESTED_VERSION, canonical_digest, dependency_versions

JSONDict = dict[str, Any]


def run_request(request: JSONDict) -> JSONDict:
    versions = dependency_versions()
    if versions["ax-platform"] != AX_TESTED_VERSION:
        raise ValueError(
            f"Ax backend requires ax-platform=={AX_TESTED_VERSION}; install the ax extra"
        )
    if request.get("protocol") != 1:
        raise ValueError("Unsupported Ax worker protocol")
    import numpy as np
    import torch
    from ax.api.client import Client
    from ax.api.configs import ChoiceParameterConfig, RangeParameterConfig

    torch.set_num_threads(1)
    seed = (int(request["seed"]) + int(request["generation"])) % (2**32)
    random.seed(seed)
    np.random.seed(seed)
    torch.manual_seed(seed)
    options = request["options"]
    with tempfile.TemporaryDirectory(prefix="looptimum-ax-") as directory:
        snapshot_path = Path(directory) / "client.json"
        if request["snapshot"] is None:
            client = Client()
            parameters = []
            for param in request["parameters"]:
                if "bounds" in param and param["bounds"][0] != param["bounds"][1]:
                    parameters.append(
                        RangeParameterConfig(
                            name=param["name"],
                            parameter_type=param["parameter_type"],
                            bounds=tuple(param["bounds"]),
                            scaling=param.get("scaling"),
                        )
                    )
                else:
                    values = param.get("values", param.get("bounds", [])[:1])
                    parameters.append(
                        ChoiceParameterConfig(
                            name=param["name"],
                            parameter_type=param["parameter_type"],
                            values=values,
                            is_ordered=False,
                        )
                    )
            client.configure_experiment(parameters=parameters)
            client.configure_optimization(
                objective="-score" if request["direction"] == "minimize" else "score"
            )
            client.configure_generation_strategy(
                method=options["method"],
                initialization_budget=options["initialization_budget"],
                min_observed_initialization_trials=options["min_observed_initialization_trials"],
                initialization_random_seed=int(request["seed"]) % (2**32),
                initialize_with_center=options["initialize_with_center"],
                use_existing_trials_for_initialization=True,
                allow_exceeding_initialization_budget=False,
                torch_device="cpu",
            )
        else:
            snapshot_path.write_text(json.dumps(request["snapshot"]))
            client = Client.load_from_json_file(filepath=str(snapshot_path))

        mapping = dict(request["mapping"])
        signatures = dict(request["signatures"])
        rows = request["records"]
        if set(mapping) - {str(row["trial_id"]) for row in rows}:
            raise ValueError("Canonical history lost a previously projected Ax trial")
        for row in rows:
            public_id = str(row["trial_id"])
            prior_signature = signatures.get(public_id)
            if prior_signature == row["signature"]:
                continue
            if public_id not in mapping:
                mapping[public_id] = client.attach_trial(parameters=row["params"])
            elif signatures.get(public_id) != canonical_digest(
                {"params": row["params"], "status": "pending", "objectives": None}
            ):
                raise ValueError(f"Previously projected terminal observation {public_id} changed")
            index = mapping[public_id]
            if row["status"] == "ok":
                client.complete_trial(trial_index=index, raw_data={"score": row["value"]})
            elif row["status"] in ("failed", "timeout"):
                client.mark_trial_failed(trial_index=index, failed_reason=row["status"])
            elif row["status"] == "killed":
                client.mark_trial_abandoned(trial_index=index)
            elif row["status"] != "pending":
                raise ValueError(f"Unsupported canonical trial status: {row['status']}")
            signatures[public_id] = row["signature"]

        blocked = {
            canonical_digest(row["params"])
            for row in rows
            if row["status"] == "pending" or not options["allow_completed_repeats"]
        }
        candidates: list[JSONDict] = []
        attempts = 0
        while len(candidates) < request["count"]:
            if attempts >= options["max_generation_attempts"] * request["count"]:
                raise ValueError("Ax exhausted generation attempts without a complete unique batch")
            attempts += 1
            proposed = client.get_next_trials(max_trials=request["count"] - len(candidates))
            if not proposed:
                raise ValueError(
                    "Ax needs more completed observations or a smaller requested batch"
                )
            for index, params in proposed.items():
                key = canonical_digest(params)
                if key in blocked:
                    client.mark_trial_abandoned(trial_index=index)
                    continue
                blocked.add(key)
                public_id = str(int(request["next_trial_id"]) + len(candidates))
                mapping[public_id] = index
                signatures[public_id] = canonical_digest(
                    {"params": params, "status": "pending", "objectives": None}
                )
                candidates.append({"params": params, "ax_trial_index": index})

        summary = client.summarize()
        phases = {
            int(row["trial_index"]): row.get("generation_node")
            for row in summary.to_dict(orient="records")
        }
        for candidate in candidates:
            candidate["generation_node"] = phases.get(candidate["ax_trial_index"])
        client.save_to_json_file(filepath=str(snapshot_path))
        return {
            "snapshot": json.loads(snapshot_path.read_text()),
            "mapping": mapping,
            "signatures": signatures,
            "candidates": candidates,
            "versions": versions,
            "attempts": attempts,
        }


def main() -> None:
    try:
        request = json.load(sys.stdin)
        with redirect_stdout(sys.stderr):
            result = run_request(request)
        response = {"ok": True, "result": result}
    except Exception as exc:
        response = {"ok": False, "error": str(exc), "error_type": type(exc).__name__}
    print(json.dumps(response, allow_nan=False))


if __name__ == "__main__":
    main()
