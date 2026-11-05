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
        if request.get("protocol") == 2:
            return run_request_v2(request)
        raise ValueError("Unsupported Ax worker protocol")
    count = request.get("count")
    if (
        type(count) is not int
        or count < 0
        or (count == 0 and request.get("operation") != "rebuild")
    ):
        raise ValueError("Ax worker count must be positive except during an explicit rebuild")
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


def run_request_v2(request: JSONDict) -> JSONDict:
    """Project exact canonical data and stage one complete typed-feasible batch."""
    import ax_contract
    import ax_space
    import numpy as np
    import torch
    from ax.api.client import Client
    from ax.api.configs import ChoiceParameterConfig, RangeParameterConfig

    count = request.get("count")
    if (
        type(count) is not int
        or count < 0
        or (count == 0 and request.get("operation") != "rebuild")
    ):
        raise ValueError("Ax worker count must be positive except for rebuild")
    torch.set_num_threads(1)
    seed = (int(request["seed"]) + int(request["generation"])) % (2**32)
    random.seed(seed)
    np.random.seed(seed)
    torch.manual_seed(seed)
    options, codec, cfg = request["options"], request["codec"], request["objective_config"]
    aliases = ax_contract.metric_aliases(cfg)

    def raw_data(row: JSONDict) -> JSONDict:
        out: JSONDict = {}
        for name, metric in row["metrics"].items():
            mean = ax_contract.finite_number(metric["mean"], "metric.mean")
            sem = metric.get("sem")
            out[name] = (
                mean
                if sem is None
                else (mean, ax_contract.finite_number(sem, "metric.sem", nonnegative=True))
            )
        return out

    with tempfile.TemporaryDirectory(prefix="looptimum-ax2-") as directory:
        path = Path(directory) / "client.json"
        if request["snapshot"] is None:
            client = Client()
            parameters = []
            for param in codec["parameters"]:
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
                    parameters.append(
                        ChoiceParameterConfig(
                            name=param["name"],
                            parameter_type=param["parameter_type"],
                            values=param.get("values", param.get("bounds", [])[:1]),
                            is_ordered=False,
                            dependent_parameters={
                                entry["value"]: entry["children"]
                                for entry in param.get("dependents", [])
                            }
                            or None,
                        )
                    )
            client.configure_experiment(
                parameters=parameters, parameter_constraints=codec["parameter_constraints"]
            )
            outcome_constraints = [
                f"{aliases[item['metric']]} {item['op']} {item['bound']!r}"
                for item in cfg.get("outcome_constraints", [])
            ]
            if cfg["acquisition"] == "pareto":
                terms = []
                for objective in cfg["objectives"]:
                    name = objective["name"]
                    minimizing = objective["direction"] == "minimize"
                    terms.append(("-" if minimizing else "") + aliases[name])
                    outcome_constraints.append(
                        f"{aliases[name]} {'<=' if minimizing else '>='} {cfg['pareto_reference'][name]!r}"
                    )
                objective_expression = ", ".join(terms)
            else:
                objective_expression = "-score" if request["direction"] == "minimize" else "score"
            client.configure_optimization(
                objective=objective_expression, outcome_constraints=outcome_constraints
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
            path.write_text(json.dumps(request["snapshot"]))
            client = Client.load_from_json_file(filepath=str(path))
        mapping, signatures = dict(request["mapping"]), dict(request["signatures"])
        records = request["records"]
        if set(mapping) - {str(row["trial_id"]) for row in records}:
            raise ValueError("Canonical history lost a projected trial")
        for row in records:
            public_id = str(row["trial_id"])
            prior = signatures.get(public_id)
            if prior == row["signature"]:
                continue
            if public_id not in mapping:
                mapping[public_id] = client.attach_trial(parameters=row["params"])
            elif prior != canonical_digest(
                {"params": row["params"], "status": "pending", "objectives": None}
            ):
                raise ValueError(f"Previously projected terminal observation {public_id} changed")
            index = mapping[public_id]
            if row["status"] == "ok":
                client.complete_trial(trial_index=index, raw_data=raw_data(row))
            elif row["status"] in ("failed", "timeout"):
                client.mark_trial_failed(trial_index=index, failed_reason=row["status"])
            elif row["status"] == "killed":
                client.mark_trial_abandoned(trial_index=index)
            elif row["status"] != "pending":
                raise ValueError("Unsupported canonical trial status")
            signatures[public_id] = row["signature"]
        # Public JSON storage rounds means/SEMs. Restore the exact authoritative
        # canonical values before fitting, including unchanged completed rows.
        for row in records:
            if row["status"] == "ok":
                client.attach_data(
                    trial_index=mapping[str(row["trial_id"])], raw_data=raw_data(row)
                )
        blocked = {
            ax_space.key(ax_space.decode(codec, row["params"]))
            for row in records
            if row["status"] == "pending" or not options["allow_completed_repeats"]
        }
        candidates: list[JSONDict] = []
        attempts = 0
        reject_counts: dict[str, int] = {}
        maximum = options["max_generation_attempts"] * count
        while len(candidates) < count:
            remaining = maximum - attempts
            if remaining <= 0:
                raise ValueError(
                    f"Ax exhausted {maximum} attempts without a complete batch; rejects={reject_counts}"
                )
            proposals = client.get_next_trials(max_trials=min(count - len(candidates), remaining))
            if not proposals:
                raise ValueError("Ax needs more observations or a smaller complete batch")
            for index, encoded in proposals.items():
                attempts += 1
                raw = ax_space.decode(codec, encoded)
                identity = ax_space.key(raw)
                feasibility = ax_space.feasible(codec, raw)
                if identity in blocked or not feasibility["feasible"]:
                    reasons = [violation["rule_id"] for violation in feasibility["violations"]] or [
                        "duplicate"
                    ]
                    for reason in reasons:
                        reject_counts[reason] = reject_counts.get(reason, 0) + 1
                    client.mark_trial_abandoned(trial_index=index)
                    continue
                blocked.add(identity)
                public_id = str(int(request["next_trial_id"]) + len(candidates))
                mapping[public_id] = index
                signatures[public_id] = canonical_digest(
                    {"params": encoded, "status": "pending", "objectives": None}
                )
                candidates.append({"params": encoded, "ax_trial_index": index})
        phases = {
            int(row["trial_index"]): row.get("generation_node")
            for row in client.summarize().to_dict(orient="records")
        }
        for candidate in candidates:
            candidate["generation_node"] = phases.get(candidate["ax_trial_index"])
        client.save_to_json_file(filepath=str(path))
        return {
            "snapshot": json.loads(path.read_text()),
            "mapping": mapping,
            "signatures": signatures,
            "candidates": candidates,
            "versions": dependency_versions(),
            "attempts": attempts,
            "reject_counts": reject_counts,
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
