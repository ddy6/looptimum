"""Contract-2 imports validate before persistence and remain usable by generation."""

from __future__ import annotations

import csv
import json
from io import StringIO

import pytest
from test_ax_recovery import campaign, invoke, state


def write_history(project, values, format):
    records = [
        {
            "trial_id": index,
            "params": {"x": value},
            "objectives": {"loss": value},
            "status": "ok",
        }
        for index, value in enumerate(values, start=41)
    ]
    path = project / f"history.{format}"
    if format == "jsonl":
        path.write_text("".join(json.dumps(record) + "\n" for record in records))
    else:
        output = StringIO()
        writer = csv.DictWriter(
            output,
            fieldnames=["trial_id", "status", "ax_csv_version", "ax_params_json", "objective_loss"],
        )
        writer.writeheader()
        writer.writerows(
            {
                "trial_id": record["trial_id"],
                "status": record["status"],
                "ax_csv_version": 2,
                "ax_params_json": json.dumps(record["params"]),
                "objective_loss": record["objectives"]["loss"],
            }
            for record in records
        )
        path.write_text(output.getvalue())
    return path


def runtime_files(project):
    return {
        path.relative_to(project).as_posix(): path.read_bytes()
        for path in (project / "state").rglob("*")
        if path.is_file() and path.name != ".looptimum.lock"
    }


@pytest.mark.parametrize("variant", ["bo_client", "bo_client_full"])
@pytest.mark.parametrize("mode", ["strict", "permissive"])
def test_fresh_v2_import_seeds_fingerprint_before_first_generation(tmp_path, variant, mode):
    project = campaign(tmp_path, variant, contract_version=2)
    history = write_history(project, [0.2], "jsonl")
    invoke(project, "import-observations", "--input-file", str(history), "--import-mode", mode)
    imported = state(project)
    settings = json.loads((project / "bo_config.json").read_text())
    assert imported["meta"]["seed"] == settings["seed"]
    fingerprint = imported["optimizer"]["fingerprint"]
    invoke(project, "suggest", "--json-only")
    generated = state(project)
    assert generated["optimizer"]["fingerprint"] == fingerprint
    assert generated["observations"] == imported["observations"]
    assert generated["pending"][0]["trial_id"] == 2


@pytest.mark.parametrize("variant", ["bo_client", "bo_client_full"])
@pytest.mark.parametrize("format", ["jsonl", "csv"])
@pytest.mark.parametrize(
    "constraints",
    [
        {"forbidden_combinations": [{"when": {"x": 0.8}}]},
        {
            "linear_inequalities": [
                {"terms": [{"param": "x", "coefficient": 1}], "operator": "<=", "rhs": 0.6}
            ]
        },
        {"bound_tightening": [{"param": "x", "max": 0.6}]},
    ],
)
def test_strict_v2_import_rejects_infeasible_history_without_writes(
    tmp_path, variant, format, constraints
):
    project = campaign(tmp_path, variant, contract_version=2)
    (project / "constraints.json").write_text(json.dumps(constraints))
    history = write_history(project, [0.2, 0.8], format)
    before = runtime_files(project)
    result = invoke(project, "import-observations", "--input-file", str(history), success=False)
    assert result.returncode != 0
    assert "constraint" in result.stderr or "bounds" in result.stderr
    assert runtime_files(project) == before


@pytest.mark.parametrize("variant", ["bo_client", "bo_client_full"])
@pytest.mark.parametrize("format", ["jsonl", "csv"])
def test_permissive_v2_import_rejects_infeasible_rows_without_consuming_ids(
    tmp_path, variant, format
):
    project = campaign(tmp_path, variant, contract_version=2)
    (project / "constraints.json").write_text(
        json.dumps({"forbidden_combinations": [{"when": {"x": 0.8}}]})
    )
    history = write_history(project, [0.8, 0.2, 0.8, 0.3], format)
    invoke(
        project,
        "import-observations",
        "--input-file",
        str(history),
        "--import-mode",
        "permissive",
    )
    imported = state(project)
    assert [row["trial_id"] for row in imported["observations"]] == [1, 2]
    expected_sources = [42, 44] if format == "jsonl" else ["42", "44"]
    assert [row["source_trial_id"] for row in imported["observations"]] == expected_sources
    assert [row["params"] for row in imported["observations"]] == [{"x": 0.2}, {"x": 0.3}]
    assert imported["next_trial_id"] == 3
    (report_path,) = (project / "state/import_reports").glob("*.json")
    report = json.loads(report_path.read_text())
    assert report["accepted_trial_ids"] == [1, 2]
    assert [row["row_number"] for row in report["rejected_rows"]] == [1, 3]
    invoke(project, "suggest", "--json-only")
    assert state(project)["pending"][0]["trial_id"] == 3
