"""Lazy optional GP fitting with one bounded numerical recovery after default failure."""

from __future__ import annotations

import copy
import math
from typing import Any

RECOVERY_OPTIONS = {"maxls": 50, "maxiter": 200, "maxfun": 2000}
RECOVERY_TIMEOUT_SECONDS = 30.0


def fit_with_recovery(mll: Any) -> dict[str, Any] | None:
    """Preserve default fits; retry failed fitting from the original state with longer line search."""
    import torch
    from botorch.exceptions.errors import ModelFittingError
    from botorch.fit import fit_gpytorch_mll

    original_state = copy.deepcopy(mll.state_dict())
    original_rng = torch.random.get_rng_state()
    try:
        fit_gpytorch_mll(mll)
        return None
    except ModelFittingError as original_error:
        mll.load_state_dict(original_state)
        mll.train()
        torch.random.set_rng_state(original_rng)
        try:
            from botorch.optim.core import OptimizationStatus
            from botorch.optim.fit import fit_gpytorch_mll_scipy

            result = fit_gpytorch_mll_scipy(
                mll, options=dict(RECOVERY_OPTIONS), timeout_sec=RECOVERY_TIMEOUT_SECONDS
            )
            # STOPPED includes iteration/function/time limits: require actual convergence.
            if result.status != OptimizationStatus.SUCCESS or not math.isfinite(float(result.fval)):
                raise ModelFittingError(
                    f"Bounded L-BFGS-B recovery did not converge: {result.status}: {result.message}"
                )
            if not all(bool(torch.isfinite(value).all()) for value in mll.parameters()):
                raise ModelFittingError("Bounded L-BFGS-B recovery produced non-finite parameters")
            mll.eval()
            return {
                "trigger": type(original_error).__name__,
                "initial_error": str(original_error),
                "optimizer": "scipy_lbfgsb",
                "attempts": 1,
                "options": dict(RECOVERY_OPTIONS),
                "timeout_seconds": RECOVERY_TIMEOUT_SECONDS,
                "status": "converged",
                "steps": int(result.step),
                "negative_mll": float(result.fval),
            }
        except Exception as recovery_error:
            mll.load_state_dict(original_state)
            mll.train()
            torch.random.set_rng_state(original_rng)
            raise ModelFittingError(
                "GP fitting failed after default fitting and one bounded L-BFGS-B recovery: "
                f"{recovery_error}"
            ) from recovery_error
