"""Dependency-free fault injection around the optional GP fitting boundary."""

from __future__ import annotations

import importlib.util
import math
import subprocess
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location(
    "test_gp_fit_shared", ROOT / "templates/_shared/gp_fit.py"
)
FIT = importlib.util.module_from_spec(spec)
spec.loader.exec_module(FIT)


class Model:
    def __init__(self):
        self.values = {"weight": [1.0]}
        self.training = True

    def state_dict(self):
        return self.values

    def load_state_dict(self, state):
        import copy

        self.values = copy.deepcopy(state)

    def train(self):
        self.training = True

    def eval(self):
        self.training = False

    def parameters(self):
        return iter(self.values["weight"])


@pytest.fixture
def stack(monkeypatch):
    class ModelFittingError(RuntimeError):
        pass

    rng = {"value": 17}
    modules = {
        name: ModuleType(name)
        for name in (
            "torch",
            "botorch",
            "botorch.fit",
            "botorch.exceptions",
            "botorch.exceptions.errors",
            "botorch.optim",
            "botorch.optim.core",
            "botorch.optim.fit",
        )
    }
    torch = modules["torch"]
    torch.random = SimpleNamespace(
        get_rng_state=lambda: rng["value"], set_rng_state=lambda value: rng.update(value=value)
    )
    torch.isfinite = lambda value: SimpleNamespace(all=lambda: math.isfinite(value))
    modules["botorch.exceptions.errors"].ModelFittingError = ModelFittingError
    modules["botorch.optim.core"].OptimizationStatus = SimpleNamespace(
        SUCCESS="success", STOPPED="stopped", FAILURE="failure"
    )
    for name, module in modules.items():
        monkeypatch.setitem(sys.modules, name, module)
    return SimpleNamespace(
        primary=modules["botorch.fit"],
        recovery=modules["botorch.optim.fit"],
        error=ModelFittingError,
        rng=rng,
    )


def test_healthy_fit_has_no_retry_or_rng_rewind(stack):
    def healthy(model):
        model.values["weight"][0] = 2.0
        stack.rng["value"] = 29
        model.eval()

    stack.primary.fit_gpytorch_mll = healthy
    stack.recovery.fit_gpytorch_mll_scipy = lambda *args, **kwargs: pytest.fail("unexpected retry")
    model = Model()
    assert FIT.fit_with_recovery(model) is None
    assert model.values["weight"] == [2.0] and model.training is False
    assert stack.rng["value"] == 29


def test_retry_restores_initial_parameters_and_rng_and_records_bounded_convergence(stack):
    def primary(model):
        model.values["weight"][0] = 99.0
        stack.rng["value"] = 99
        raise stack.error("default failed")

    calls = []

    def recovery(model, **kwargs):
        assert model.values["weight"] == [1.0] and model.training is True
        assert stack.rng["value"] == 17
        calls.append(kwargs)
        model.values["weight"][0] = 3.0
        return SimpleNamespace(status="success", fval=0.329, step=75, message="converged")

    stack.primary.fit_gpytorch_mll = primary
    stack.recovery.fit_gpytorch_mll_scipy = recovery
    model = Model()
    diagnostic = FIT.fit_with_recovery(model)
    assert model.values["weight"] == [3.0] and model.training is False
    assert calls == [
        {"options": {"maxls": 50, "maxiter": 200, "maxfun": 2000}, "timeout_sec": 30.0}
    ]
    assert diagnostic["attempts"] == 1 and diagnostic["status"] == "converged"
    assert diagnostic["initial_error"] == "default failed"


@pytest.mark.parametrize(
    "status,loss,weight",
    [
        ("failure", 0.3, 2.0),
        ("stopped", 0.3, 2.0),
        ("success", float("nan"), 2.0),
        ("success", float("inf"), 2.0),
        ("success", 0.3, float("nan")),
    ],
)
def test_nonconvergence_and_nonfinite_fits_fail_closed_and_restore_state(
    stack, status, loss, weight
):
    def primary(model):
        raise stack.error("default failed")

    def recovery(model, **kwargs):
        model.values["weight"][0] = weight
        stack.rng["value"] = 99
        return SimpleNamespace(status=status, fval=loss, step=200, message="limit or invalid fit")

    stack.primary.fit_gpytorch_mll = primary
    stack.recovery.fit_gpytorch_mll_scipy = recovery
    model = Model()
    with pytest.raises(stack.error, match="one bounded L-BFGS-B recovery"):
        FIT.fit_with_recovery(model)
    assert model.values["weight"] == [1.0] and model.training is True
    assert stack.rng["value"] == 17


def test_unrelated_errors_are_not_retried(stack):
    def primary(model):
        raise ValueError("invalid training data")

    stack.primary.fit_gpytorch_mll = primary
    stack.recovery.fit_gpytorch_mll_scipy = lambda *args, **kwargs: pytest.fail("unexpected retry")
    with pytest.raises(ValueError, match="invalid training data"):
        FIT.fit_with_recovery(Model())


def test_fitting_helper_import_is_lean():
    source = f"import sys; sys.path.insert(0, {str(ROOT / 'templates/_shared')!r}); import gp_fit; assert not any(name in sys.modules for name in ('torch','botorch','gpytorch','numpy'))"
    subprocess.run([sys.executable, "-S", "-c", source], check=True)
