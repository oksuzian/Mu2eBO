#!/usr/bin/env python3
"""BoTorch qNEHVI re-derivation for any pure-numeric BOMode.

Standalone CLI; not wired into graph/closed_loop.py. Companion to the
skopt-EI shims at
`/exp/mu2e/data/users/oksuzian/autoresearch_grid/mmackenz_table_plots/gp_predict_{foils,helical}.py`
— same `compute_explore_picks(q, ...)` return contract (list of native-
int/float n-tuples), so a future closed_loop swap-in is straightforward.

Why this exists: the original `botorch_predict_helical.py` was deleted
before the 2026-05-18 .snap/ window opened (see wiki/projects/bo-helical
.md note); the qNEHVI recipe survived in the wiki and is reapplied here.

Modes supported: `foils` (5D), `helical` (4D). `michael` is NOT supported
— its space mixes Real + Categorical, which needs a separate model (mixed
single-task GP w/ one-hot or qParEGO over Tchebycheff scalarization);
out of scope for this shim.

Recipe (wiki/projects/bo-helical.md:837-851):
  - acquisition: qNoisyExpectedHypervolumeImprovement
  - objectives: maximize (sob, -log10(calo))
  - ref point: per-round nadir(feasible front) - 0.1*span (NOT hardcoded)
  - MC sampler seed: 42 ^ round_idx (NOT fixed 42 — fixed seed reuses the
    same Sobol draw every round -> subtle diversity bias)
  - num_restarts: 16
  - sample_shape: 128
  - prune_baseline: True

CLI:
  .venv-botorch/bin/python botorch_predict.py \\
      --mode foils --q 5 --round-idx 0 --emit-picks-json picks.json
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path

import torch

AUTORESEARCH = Path("/exp/mu2e/app/users/oksuzian/autoresearch")
sys.path.insert(0, str(AUTORESEARCH))
import autoresearch_bo_michael as bo  # noqa: E402


# torch defaults: float64 + CPU. The history matrix is tiny (<200 pts), so
# CPU is faster than GPU once you account for transfer; float64 matches
# botorch's recommended SingleTaskGP precision.
torch.set_default_dtype(torch.float64)
DEVICE = torch.device("cpu")


# Per-mode bounds + integer-dim mask, inlined here so .venv-botorch (no
# skopt) doesn't have to import BOMode.build_space(). Order MUST match the
# Point.x layout (= build_space order) in autoresearch_bo_michael.py:
#   foils   (v2 6D): [rOut_up, rOut_dn, hT_up, hT_dn, rIn_up, rIn_dn]
#                    -> FoilsMode.build_space
#   helical (4D):    [tsda_helical_dx, dy, halflength, angle]
#                    -> HelicalMode.build_space
MODE_SPECS = {
    "foils": {
        # v2 6D: (rOut_up, rOut_dn, hT_up, hT_dn, rIn_up, rIn_dn). All Real.
        "lo":       [ 50.0,  50.0, 0.05, 0.05,  0.0,  0.0],
        "hi":       [250.0, 250.0, 1.00, 1.00, 50.0, 50.0],
        "int_dims": [],
    },
    "helical": {
        "lo":       [0.01,  40.0,  25.0,  60.0],
        "hi":       [5.00, 400.0, 500.0, 720.0],
        "int_dims": [],
    },
}


def _load_history_tensor(mode: str):
    """Return (X, Y, bounds, int_dims) tensors over the mode's search space.

    X shape (n, d): per-mode x vector as floats (Integer dims coerced).
    Y shape (n, 2): [sob, -log10(calo)] — botorch maximizes both.
    bounds shape (2, d): from MODE_SPECS.
    int_dims: list of column indices to round on emit.
    """
    if mode not in MODE_SPECS:
        raise SystemExit(f"[botorch_predict] mode={mode!r} not supported; "
                         f"choose from {sorted(MODE_SPECS)}. "
                         "michael's Real+Categorical space needs a mixed model.")
    spec = MODE_SPECS[mode]
    bo_mode = bo.MODES[mode]
    # Match the skopt shims (gp_predict_*.py): seeds = priors + history.
    # For foils v2, priors are the projected v1 n=6/6 subset (~51 rows);
    # without them an early v2 run with zero leaderboard rows has nothing
    # to fit on.
    priors = bo_mode.load_priors() if hasattr(bo_mode, "load_priors") else []
    history = bo_mode.load_history()
    seeds = priors + history
    if not seeds:
        raise SystemExit(f"[botorch_predict] empty history for mode={mode}; "
                         f"need at least one row in "
                         f"{bo_mode.leaderboard}. Seed with "
                         "autoresearch_bo_michael.py cmd_propose or the "
                         "skopt shim first.")

    X_rows = []
    Y_rows = []
    for p in seeds:
        if p.calo <= 0:
            continue  # log10 undefined; rare but possible on broken harvest
        X_rows.append([float(v) for v in p.x])
        Y_rows.append([p.sob, -math.log10(p.calo)])
    X = torch.tensor(X_rows, device=DEVICE)
    Y = torch.tensor(Y_rows, device=DEVICE)

    if X.shape[1] != len(spec["lo"]):
        raise SystemExit(f"[botorch_predict] mode={mode} dim mismatch: "
                         f"history has {X.shape[1]}D points but MODE_SPECS "
                         f"declares {len(spec['lo'])}D bounds. Check "
                         "leaderboard schema vs MODE_SPECS in this file.")

    lo = torch.tensor(spec["lo"], device=DEVICE)
    hi = torch.tensor(spec["hi"], device=DEVICE)
    bounds = torch.stack([lo, hi], dim=0)
    return X, Y, bounds, spec["int_dims"]


def _fit_gp(X, Y, bounds):
    """Fit a 2-output SingleTaskGP with input normalization + output stdize."""
    from botorch.fit import fit_gpytorch_mll
    from botorch.models import SingleTaskGP
    from botorch.models.transforms.input import Normalize
    from botorch.models.transforms.outcome import Standardize
    from gpytorch.mlls import ExactMarginalLogLikelihood

    model = SingleTaskGP(
        train_X=X,
        train_Y=Y,
        input_transform=Normalize(d=X.shape[-1], bounds=bounds),
        outcome_transform=Standardize(m=Y.shape[-1]),
    )
    mll = ExactMarginalLogLikelihood(model.likelihood, model)
    fit_gpytorch_mll(mll)
    return model


def _qnehvi_picks(model, X, Y, bounds, q: int, round_idx: int):
    """Optimize qNEHVI for q candidates; return shape (q, d) tensor."""
    from botorch.acquisition.multi_objective.monte_carlo import (
        qNoisyExpectedHypervolumeImprovement,
    )
    from botorch.optim import optimize_acqf
    from botorch.sampling.normal import SobolQMCNormalSampler

    # Per-round ref-point: nadir of the observed front, pushed out 10% of
    # the span. For maximization, "dominated" = smaller — so subtract the
    # offset (sign-robust; "× 1.1" only works when nadir is negative).
    nadir = Y.min(dim=0).values
    span = (Y.max(dim=0).values - nadir).abs().clamp(min=1e-9)
    ref_point = (nadir - 0.1 * span).tolist()

    seed = 42 ^ int(round_idx)
    sampler = SobolQMCNormalSampler(sample_shape=torch.Size([128]), seed=seed)

    acq = qNoisyExpectedHypervolumeImprovement(
        model=model,
        ref_point=ref_point,
        X_baseline=X,
        sampler=sampler,
        prune_baseline=True,
    )

    candidates, _ = optimize_acqf(
        acq_function=acq,
        bounds=bounds,
        q=q,
        num_restarts=16,
        raw_samples=512,
        options={"batch_limit": 5, "maxiter": 200},
        sequential=False,
    )
    return candidates.detach()


def _emit_picks(cands, int_dims):
    """Cast (q, d) tensor -> list of native-typed tuples.

    int_dims get round() + int(); other dims get float(). Native types only
    (msgpack-safe — see gp_predict_foils.py:62-67 for the LangGraph
    constraint that motivates this).
    """
    int_set = set(int_dims)
    out = []
    for row in cands.cpu().numpy().tolist():
        tup = tuple(int(round(v)) if i in int_set else float(v)
                    for i, v in enumerate(row))
        out.append(tup)
    return out


def compute_explore_picks(q: int = 5,
                          mode: str = "foils",
                          round_idx: int = 0,
                          nsteps_budget=None,
                          min_spacing=None,
                          pessimistic_calo: bool = False,
                          alpha: float = bo.DEFAULT_ALPHA,
                          ) -> list[tuple]:
    """qNEHVI replacement matching gp_predict_{foils,helical}.compute_explore_picks.

    The trailing kwargs (nsteps_budget, min_spacing, pessimistic_calo) are
    accepted for shim-compatibility and ignored: qNEHVI handles its own
    geometry-feasibility via the GP posterior on calo, and there is no
    helical-style N_crit gate baked into this picker.
    """
    X, Y, bounds, int_dims = _load_history_tensor(mode)
    model = _fit_gp(X, Y, bounds)
    cands = _qnehvi_picks(model, X, Y, bounds, q=q, round_idx=round_idx)
    return _emit_picks(cands, int_dims)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--mode", choices=sorted(MODE_SPECS), default="foils",
                    help="BO mode to refit (default foils)")
    ap.add_argument("--q", type=int, default=5,
                    help="Batch size (default 5)")
    ap.add_argument("--round-idx", type=int, default=0,
                    help="Round index; seeds MC sampler (default 0)")
    ap.add_argument("--alpha", type=float, default=bo.DEFAULT_ALPHA,
                    help=f"Scalarization weight passed through for shim "
                         f"compatibility (default {bo.DEFAULT_ALPHA})")
    ap.add_argument("--emit-picks-json", type=str, default=None,
                    help="If set, write picks as JSON to this path")
    ns = ap.parse_args(argv)

    picks = compute_explore_picks(q=ns.q, mode=ns.mode,
                                  round_idx=ns.round_idx, alpha=ns.alpha)

    if ns.emit_picks_json:
        Path(ns.emit_picks_json).write_text(json.dumps(picks, indent=2))
        print(f"[botorch_predict] mode={ns.mode} wrote {len(picks)} picks "
              f"-> {ns.emit_picks_json}")
    else:
        for i, p in enumerate(picks):
            print(f"pick {i} ({ns.mode}): {p}")


if __name__ == "__main__":
    main()
