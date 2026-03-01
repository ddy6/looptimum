from __future__ import annotations

from acquisition import acquisition_score


def _normalize(vec: dict, params: list[dict]) -> list[float]:
    out = []
    for p in params:
        lo, hi = map(float, p["bounds"])
        span = max(hi - lo, 1e-12)
        out.append((float(vec[p["name"]]) - lo) / span)
    return out


def _denormalize(vals: list[float], params: list[dict]) -> dict:
    out: dict = {}
    for i, p in enumerate(params):
        lo, hi = map(float, p["bounds"])
        v = lo + float(vals[i]) * (hi - lo)
        out[p["name"]] = int(round(v)) if p["type"] == "int" else float(v)
    return out


def propose_with_gp(
    candidates: list[dict],
    observations: list[dict],
    params: list[dict],
    objective: dict,
    acq_cfg: dict,
    best: float | None,
    seed: int,
) -> tuple[dict, dict]:
    try:
        import torch
        from botorch.fit import fit_gpytorch_mll
        from botorch.models import SingleTaskGP
        from gpytorch.kernels import MaternKernel, ScaleKernel
        from gpytorch.mlls import ExactMarginalLogLikelihood
    except Exception as exc:
        raise RuntimeError("GP backend requires botorch/gpytorch/torch to be installed") from exc

    torch.manual_seed(int(seed))
    obj_name = str(objective["name"])
    direction = str(objective["direction"])

    X = torch.tensor([_normalize(o["params"], params) for o in observations], dtype=torch.double)
    y_raw = [float(o["objectives"][obj_name]) for o in observations]
    # Fit in a minimization frame so acquisition handling is consistent.
    y_min_frame = [y if direction == "minimize" else -y for y in y_raw]
    Y = torch.tensor([[y] for y in y_min_frame], dtype=torch.double)

    covar_module = ScaleKernel(MaternKernel(nu=2.5, ard_num_dims=X.shape[-1]))
    model = SingleTaskGP(X, Y, covar_module=covar_module)
    mll = ExactMarginalLogLikelihood(model.likelihood, model)
    fit_gpytorch_mll(mll)

    scored = []
    for cand in candidates:
        x = torch.tensor([_normalize(cand, params)], dtype=torch.double)
        post = model.posterior(x)
        mean_min = post.mean.detach().cpu().view(-1)[0].item()
        std = post.variance.detach().cpu().clamp_min(1e-12).sqrt().view(-1)[0].item()

        mean = mean_min if direction == "minimize" else -mean_min
        score = acquisition_score(mean, std, best, direction, acq_cfg)
        scored.append((score, _denormalize(_normalize(cand, params), params), mean, std))

    scored.sort(key=lambda x: x[0], reverse=True)
    score, cand, mean, std = scored[0]
    return cand, {
        "strategy": "surrogate_acquisition",
        "surrogate_backend": "gp",
        "acquisition_type": acq_cfg.get("type", "ei"),
        "predicted_mean": mean,
        "predicted_std": std,
        "acquisition_score": score,
    }
