"""Real GP regression coverage on the recorded numerical failure and portable controller."""

from __future__ import annotations

import importlib.util
import json
import math
import os
import random
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
FIXTURE = ROOT / "benchmarks/backend_comparison/gp_pipeline_seed97_failure.json"
AVAILABLE = importlib.util.find_spec("botorch") is not None
if os.environ.get("LOOPTIMUM_REQUIRE_AX_TESTS") == "1" and not AVAILABLE:
    raise RuntimeError("Required numerical integration lane must install BoTorch")
pytestmark = pytest.mark.skipif(not AVAILABLE, reason="optional GP stack is not installed")


def invoke(project, *args, success=True):
    result = subprocess.run(
        [sys.executable, "run_bo.py", *args],
        cwd=project,
        capture_output=True,
        text=True,
        timeout=120,
        env={**os.environ, "OMP_NUM_THREADS": "1", "MKL_NUM_THREADS": "1"},
    )
    if success:
        assert result.returncode == 0, result.stdout + result.stderr
    return result


def campaign(tmp_path):
    fixture = json.loads(FIXTURE.read_text())
    project = tmp_path / "controller"
    subprocess.run(
        [
            sys.executable,
            str(ROOT / "templates/_shared/vendor_copy.py"),
            str(ROOT / "templates/bo_client"),
            str(project),
        ],
        check=True,
        capture_output=True,
    )
    config = json.loads((project / "bo_config.json").read_text())
    config.update(fixture["settings"])
    config["max_pending_age_seconds"] = None
    (project / "bo_config.json").write_text(json.dumps(config))
    (project / "parameter_space.json").write_text(json.dumps(fixture["parameter_space"]))
    (project / "objective_schema.json").write_text(
        json.dumps({"primary_objective": {"name": "loss", "direction": "minimize"}})
    )
    (project / "seed.jsonl").write_text(
        "".join(json.dumps(row) + "\n" for row in fixture["observations"])
    )
    invoke(project, "import-observations", "--input-file", "seed.jsonl")
    return project, fixture


def test_portable_recorded_history_generates_a_finite_typed_gp_suggestion(tmp_path):
    from benchmarks.backend_comparison.workloads import valid

    project, fixture = campaign(tmp_path)
    before = json.loads((project / "state/bo_state.json").read_text())
    suggestion = json.loads(invoke(project, "suggest", "--json-only").stdout)
    assert suggestion["trial_id"] == 12 and valid(suggestion["params"], "pipeline")
    state = json.loads((project / "state/bo_state.json").read_text())
    assert state["observations"] == before["observations"] and state["best"] == before["best"]
    assert state["next_trial_id"] == 13 and len(state["pending"]) == 1
    decision = json.loads((project / "state/acquisition_log.jsonl").read_text().splitlines()[-1])[
        "decision"
    ]
    assert decision["surrogate_backend"] == "gp" and "fallback_reason" not in decision
    assert all(
        math.isfinite(decision[key])
        for key in ("predicted_mean", "predicted_std", "acquisition_score")
    )
    if "gp_fit_recovery" in decision:
        assert decision["gp_fit_recovery"]["status"] == "converged"
        assert decision["gp_fit_recovery"]["options"]["maxls"] == 50
    assert len(fixture["observations"]) == 11
    invoke(project, "validate")


def test_exhausted_fitting_never_allocates_or_switches_to_proxy(tmp_path):
    project, _ = campaign(tmp_path)
    before = (project / "state/bo_state.json").read_bytes()
    (project / "vendor/looptimum_shared/gp_fit.py").write_text(
        "def fit_with_recovery(mll):\n    raise RuntimeError('forced unrecoverable GP fit')\n"
    )
    failed = invoke(project, "suggest", "--json-only", success=False)
    assert failed.returncode != 0 and failed.stdout == ""
    assert "forced unrecoverable GP fit" in failed.stderr
    assert (project / "state/bo_state.json").read_bytes() == before
    assert not (project / "state/trials/trial_12").exists()


@pytest.mark.parametrize("force_numerical_failure", [False, True])
def test_recorded_recovery_converges_or_restores_state(monkeypatch, force_numerical_failure):
    import torch
    from botorch import fit as fitting
    from botorch.exceptions.errors import ModelFittingError
    from botorch.models import SingleTaskGP
    from gpytorch.kernels import MaternKernel, ScaleKernel
    from gpytorch.mlls import ExactMarginalLogLikelihood
    from linear_operator.utils.errors import NotPSDError

    sys.path.insert(0, str(ROOT / "templates/bo_client"))
    try:
        spec = importlib.util.spec_from_file_location(
            "gp_regression_surrogate", ROOT / "templates/bo_client/surrogate_gp.py"
        )
        surrogate_gp = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(surrogate_gp)
    finally:
        sys.path.remove(str(ROOT / "templates/bo_client"))
    fixture = json.loads(FIXTURE.read_text())
    params = surrogate_gp._SEARCH_SPACE.normalize_search_space(fixture["parameter_space"])
    x = torch.tensor(
        [surrogate_gp._normalize(row["params"], params) for row in fixture["observations"]],
        dtype=torch.double,
    )
    y = torch.tensor(
        [[row["objectives"]["loss"]] for row in fixture["observations"]], dtype=torch.double
    )
    torch.set_num_threads(1)
    torch.manual_seed(fixture["fit_seed"])
    model = SingleTaskGP(
        x, y, covar_module=ScaleKernel(MaternKernel(nu=2.5, ard_num_dims=x.shape[-1]))
    )
    mll = ExactMarginalLogLikelihood(model.likelihood, model)
    original_state = {name: value.clone() for name, value in mll.state_dict().items()}
    original_rng = torch.random.get_rng_state().clone()

    def failed_default(mll):
        raise ModelFittingError("forced default failure to exercise recovery across platforms")

    monkeypatch.setattr(fitting, "fit_gpytorch_mll", failed_default)

    if force_numerical_failure:
        from botorch.optim import fit as scipy_fitting

        def failed_recovery(mll, **kwargs):
            with torch.no_grad():
                next(mll.parameters()).add_(1.0)
            torch.rand(3)
            raise NotPSDError("injected non-positive-definite covariance")

        monkeypatch.setattr(scipy_fitting, "fit_gpytorch_mll_scipy", failed_recovery)

    try:
        recovery = surrogate_gp._GP_FIT.fit_with_recovery(mll)
    except ModelFittingError as error:
        # The retained history is a numerical regression case, not a promise
        # that one bounded optimization will converge on every BLAS/platform.
        assert "one bounded L-BFGS-B recovery" in str(error)
        assert isinstance(error.__cause__, (ModelFittingError, NotPSDError))
        if force_numerical_failure:
            assert "injected non-positive-definite covariance" in str(error)
        assert mll.training and model.training and model.likelihood.training
        assert mll.state_dict().keys() == original_state.keys()
        for name, value in mll.state_dict().items():
            assert torch.equal(value, original_state[name]), name
        assert torch.equal(torch.random.get_rng_state(), original_rng)
    else:
        assert not force_numerical_failure
        assert recovery["status"] == "converged" and recovery["attempts"] == 1
        assert recovery["steps"] <= 200 and math.isfinite(recovery["negative_mll"])
        assert not mll.training
        posterior = model.posterior(x)
        assert torch.isfinite(posterior.mean).all() and torch.isfinite(posterior.variance).all()


def test_real_bounded_recovery_converges_on_well_conditioned_data(monkeypatch):
    import torch
    from botorch import fit as fitting
    from botorch.exceptions.errors import ModelFittingError
    from botorch.models import SingleTaskGP
    from gpytorch.kernels import MaternKernel, ScaleKernel
    from gpytorch.mlls import ExactMarginalLogLikelihood

    spec = importlib.util.spec_from_file_location(
        "gp_convergence_fit", ROOT / "templates/_shared/gp_fit.py"
    )
    gp_fit = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(gp_fit)
    x = torch.linspace(0.0, 1.0, 9, dtype=torch.double).unsqueeze(-1)
    y = (x - 0.35).square()
    model = SingleTaskGP(x, y, covar_module=ScaleKernel(MaternKernel(nu=2.5, ard_num_dims=1)))
    mll = ExactMarginalLogLikelihood(model.likelihood, model)

    def failed_default(mll):
        raise ModelFittingError("forced default failure on well-conditioned data")

    monkeypatch.setattr(fitting, "fit_gpytorch_mll", failed_default)
    recovery = gp_fit.fit_with_recovery(mll)
    assert recovery["status"] == "converged" and recovery["attempts"] == 1
    assert recovery["steps"] <= 200 and math.isfinite(recovery["negative_mll"])
    assert not mll.training
    posterior = model.posterior(x)
    assert torch.isfinite(posterior.mean).all() and torch.isfinite(posterior.variance).all()


def test_full_direct_gp_routes_through_bounded_recovery(tmp_path, monkeypatch):
    import torch
    from botorch import fit as fitting
    from botorch.exceptions.errors import ModelFittingError

    spec = importlib.util.spec_from_file_location(
        "full_gp_regression", ROOT / "templates/bo_client_full/run_bo.py"
    )
    controller = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(controller)
    fixture = json.loads(FIXTURE.read_text())
    params = controller.normalize_search_space(fixture["parameter_space"])
    objective = controller.normalize_objective_schema(
        {"primary_objective": {"name": "loss", "direction": "minimize"}}
    )
    config = fixture["settings"]
    config["candidate_pool_size"] = 8
    config["acquisition"] = json.loads(
        (ROOT / "templates/bo_client_full/bo_config.json").read_text()
    )["acquisition"]
    state = {
        "best": {
            "objective_value": min(row["objectives"]["loss"] for row in fixture["observations"])
        }
    }
    torch.set_num_threads(1)
    torch.manual_seed(109)

    def failed_default(mll):
        raise ModelFittingError("forced default failure")

    monkeypatch.setattr(fitting, "fit_gpytorch_mll", failed_default)
    candidate, decision = controller.propose_with_botorch(
        random.Random(109), fixture["observations"], state, config, params, objective
    )
    assert decision["surrogate_backend"] == "botorch_gp"
    assert decision["gp_fit_recovery"]["status"] == "converged"
    assert set(candidate) == {param["name"] for param in params}
