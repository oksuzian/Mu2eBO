# Batch / Asynchronous Bayesian Optimization

**Type:** concept
**Status:** active
**Updated:** 2026-05-16

## Summary
How to propose **q > 1 in-flight BO points** at once instead of one-at-a-time, so
grid wall-clock parallelism amplifies into BO iteration throughput. The decision
that matters here: which batch-acquisition method, at which `q`, given our
setup (sklearn-GP + EI in `skopt.Optimizer`, ~96 michael priors, 10 helical
priors, 4–5D continuous + 1 categorical, ~1–2 h grid wall per point, async
returns are the norm because mustops_ce wall-time spans wider than mubeam).

The short answer: **CL-mean at q=3, ceiling q=5, for michael mode. CL-min at
q=2 for helical until history grows.** scikit-optimize ships this natively as
`Optimizer.ask(n_points=q, strategy=...)` — the retrofit is ~10–30 LOC inside
`autoresearch_bo_michael.py:cmd_propose` plus a small pending-state file.
Long answer below.

## Key facts — method landscape

| Method | What | Cost | Practical q | Notes for us |
|---|---|---|---|---|
| **Constant Liar (CL-mean/min/max)** | greedy; pretend picked points returned a fake `y`, refit, repeat | `O(q)` GP updates | up to ~50 | Native in skopt. Default starting point. CL-min more exploratory, CL-max more exploitative, CL-mean neutral. |
| **Kriging Believer (KB)** | greedy; fake value = posterior mean → collapses variance at pick | `O(q)` GP updates | up to ~50 | Better diversity than CL-mean; not in skopt. Equivalent to BoTorch `qNEI` fantasy mode. |
| **q-EI / q-NEI** | jointly optimize multipoint EI over all q points | `O(N_mc · q · n²)` per eval | ~10 closed-form, ~50 MC | Theoretically Bayes-optimal one-step lookahead. Requires BoTorch rewrite. |
| **qKG / fantasy KG** | one-step lookahead in posterior-mean improvement | `N_fantasies` GP refits per eval | ~8 | Most expensive; overkill for n≈100. |
| **Thompson Sampling (TS)** | draw q posterior samples, each worker maxes its own | `O(n³)` Cholesky, then independent | hundreds discrete / ~20 continuous | **Collapses** with strong priors — all samples concentrate near the incumbent. Bad fit for us once history grows. |
| **Local Penalization (LP)** | maximize `α(x)·Π_j φ(x;x_j)` with exclusion ball at each pick | `O(q)` acq maximizations, no GP refit | ~20–50 | Lipschitz-estimate based; fragile in high-D or non-stationary surfaces. GPyOpt has it; archived. Trieste also. |
| **Async TS / PLAyBOOK** | improved LP for asynchronous workers | per-pending-point | worker-limited | PLAyBOOK (Alvi 2019) beats async-TS / async-KB on most benchmarks; not in skopt. |

**Empirical pecking order (general):** qEI/qKG > KB ≈ CL-mix > CL-mean > CL-min/max > random. LP and TS swap places depending on whether the surface is rugged (LP wins) or the prior is informative (TS collapses).

**Sync vs async:** async dominates wall-clock when worker runtimes are heterogeneous (mustops_ce stage has 5–10× more variance than mubeam due to OOM tails and FCL init time). Sync only wins if all evaluations finish in lockstep — they don't.

## Key facts — fit to our setup

- **`skopt.Optimizer` already supports CL natively** via `ask(n_points=q, strategy="cl_min"|"cl_mean"|"cl_max")` — the `Optimizer` built at `autoresearch_bo_michael.py:152-161` is CL-capable out of the box. No new dependency.
- **Prior leverage:** 96 michael priors → CL fakes are ~5% perturbation of the conditioned set, safe up to q=5. 10 helical priors → q=5 means 50% extra "fake data" per round; CL aggressively flattens EI near picks → cap helical at **q=2 with `cl_min`** until history reaches ~30 real points.
- **The seam is q=1 today.** `cmd_propose` (`autoresearch_bo_michael.py:423-458`) calls `opt.ask()` once, renders one geom, prints one shell instruction.
- **Pending state must persist across `propose` invocations.** `Optimizer` is rebuilt from scratch every call (`autoresearch_bo_michael.py:429`) with `random_state=42` (`:160`) — without a pending-points file, two back-to-back `propose` calls return the *same* `x`.
- **Grid layer is q-ready.** `pipeline.py` is fully parametric per `--config` (`pipeline.py:36-67`); `poll_cluster` is cluster-scoped (`pipeline.py:323-356`); q parallel pipelines do not interfere. Per-user FIFE quota easily absorbs q=5 × ~300 jobs ≈ 1500 jobs.
- **Library alternatives that preserve the 96-point warm start:** BoTorch (`SingleTaskGP(X, y)` + `qLogNoisyExpectedImprovement` with `X_pending=`), Trieste (`AsynchronousGreedy`), HEBO (`observe(X, y)`). Ax wraps BoTorch but needs `Experiment` ceremony. Dragonfly has unique async-TS but stagnant since 2022.
- **One pitfall the libraries don't fix:** the categorical `col5` dimension in michael mode (`autoresearch_bo_michael.py:204`) is awkward for libraries that assume pure-continuous spaces. Stay on skopt unless we're already paying the rewrite cost for q-EI semantics.

## Key facts — retrofit shape (no code yet)

Three surgical patches land the batch retrofit; a fourth would automate the grid handoff.

1. **`cmd_propose` (`autoresearch_bo_michael.py:423`):**
   - `nargs="+"` on the config-name argument or add `--q N`.
   - Replace `opt.ask()` with `opt.ask(n_points=q, strategy="cl_mean")`.
   - Loop the render/stage block over the q `xs`.
   - Write each as a pending row.
2. **`BOMode.load_history` (`autoresearch_bo_michael.py:132`):** union the pending file so the next `propose` knows what's in flight — **do not `tell` pending points to the optimizer** (CL injects them internally during `ask`). Pending suppression only prevents re-proposal on rerun.
3. **Pending persistence:** new sibling file `pending_bo_<mode>.tsv` with `config, knobs…, alpha, submitted_at`. `cmd_evaluate` atomically moves pending → leaderboard. `flock` around `cmd_propose` body to prevent concurrent-propose races (no locking exists today).
4. **(Optional) Orchestrator:** thin driver that takes the q proposal names and fans out the per-config `pipeline.py … submit/poll/harvest/evaluate` chains. `autoresearch_loop.py` is the natural home.

**Recommended starting strategy by mode:**
- `michael`: `strategy="cl_mean"`, q=3 → bump to q=5 if batches stay diverse.
- `helical`: `strategy="cl_min"`, q=2 only — until history ≥ ~30 real points.

**Diagnostic for q creep:** if `propose` starts returning near-duplicate geometries within a batch, CL is leaking; drop q or switch `strategy` to a more pessimistic variant.

## Cross-links
- Driver: [[autoresearch-bo-michael]]
- Driver: [[pipeline]]
- Concept: [[bo-modes]]
- Project: [[bo-michael]], [[bo-helical]]
- Source files: `autoresearch_bo_michael.py:152-161` (Optimizer factory), `:423-458` (cmd_propose, batch retrofit lands here), `:132-150` (history I/O, pending-union point), `pipeline.py:36-67` (per-config paths, q-safe today)

## Sources
- Ginsbourger, Le Riche, Carraro 2010 — *Kriging is well-suited to parallelize optimization* (CL + KB) — [PDF](https://www.cs.ubc.ca/labs/algorithms/EARG/stack/2010_CI_Ginsbourger-ParallelKriging.pdf)
- Chevalier & Ginsbourger 2013 — *Fast computation of multi-points EI* — [HAL](https://hal.science/hal-00732512v2)
- González, Dai, Hennig, Lawrence 2016 — *Batch BO via Local Penalization* — [arXiv:1505.08052](https://arxiv.org/abs/1505.08052)
- Wang, Clark, Liu, Frazier 2020 — *Parallel BO of Expensive Functions* (MC qEI) — [arXiv:1602.05149](https://arxiv.org/abs/1602.05149)
- Hernández-Lobato et al. 2017 — *Parallel & Distributed Thompson Sampling* — [ICML PDF](http://proceedings.mlr.press/v70/hernandez-lobato17a/hernandez-lobato17a.pdf)
- Kandasamy, Krishnamurthy, Schneider, Póczos 2018 — *Parallelised BO via TS* — [arXiv:1705.09236](https://arxiv.org/abs/1705.09236)
- Alvi, Ru, Calliess, Roberts, Osborne 2019 — *Async batch BO with improved LP* (PLAyBOOK) — [arXiv:1901.10452](https://arxiv.org/abs/1901.10452)
- Balandat et al. 2020 — *BoTorch* (qEI/qNEI/qKG via SAA) — [NeurIPS PDF](https://proceedings.neurips.cc/paper/2020/file/f5b1b89d98b7286673128a5fb112cb9a-Paper.pdf)
- skopt parallel-optimization example — [docs](https://scikit-optimize.github.io/stable/auto_examples/parallel-optimization.html)
- BoTorch closed-loop qNEI tutorial — [docs](https://botorch.org/docs/tutorials/closed_loop_botorch_only/)
- Trieste async-greedy notebook — [docs](https://secondmind-labs.github.io/trieste/3.0.0/notebooks/asynchronous_greedy_multiprocessing.html)

## Open questions / TODO

### Q1: skopt CL-mean vs BoTorch qLogNEI

**Trade-off.** skopt CL is ~30 LOC of glue inside `cmd_propose`; reuses the
existing GP, EI, and `col5` categorical handling. BoTorch `qLogNEI` with
`X_pending=` is the gold-standard joint acquisition with native async, but
costs a GP-layer rewrite (sklearn → GPyTorch), a categorical encoding (one-hot
or `MixedSingleTaskGP`), and refits hyperparameters from scratch on first run.

**Recommendation — staged path:**
1. **Phase 1 (now):** ship skopt CL-mean q=3. Measures whether batch BO is
   worth the engineering at all on *this* surface. ~30 LOC + pending file +
   `flock`. Risk-free: if it underperforms sequential, revert is one git revert.
2. **Phase 2 (gate on phase-1 evidence):** if after ~5 batches the leaderboard
   shows CL batches clustering (≥2 points in a batch within 10% of each other
   in the dominant `tsda.rin` axis), or the per-batch best-improvement is
   flat vs sequential, **then** commit to BoTorch. Otherwise stay on skopt.
3. **Skip Phase 2 entirely** if `col5` becomes irrelevant (e.g. one
   category dominates the leaderboard); the case for BoTorch is much weaker
   without the mixed-space need.

**Decision criterion for Phase 2 (write this down so we don't relitigate):**
median batch-best-improvement over 5 batches must be ≥ 1.2× sequential-best
over the same wall-clock window, OR cluster fraction must drop below 0.2.
Anything weaker = skopt is already at the Pareto frontier for this problem.

### Q2: helical lengthscale fragility

**Problem.** 10 priors in 5D is sparse — sklearn's `GaussianProcessRegressor`
will fit kernel lengthscales by marginal-likelihood maximization, which is
underdetermined here and frequently snaps to either the bound or a degenerate
near-zero value. `cl_min`'s pessimism repels picks via the *kernel* — if
lengthscales are too short, repulsion is local-only and CL barely diversifies
the batch; if too long, every batch member ends up in the same basin.

**Recommendation — three-step diagnostic + fallback:**
1. **Diagnose first (10 min of work):** after `build_optimizer` + warm-up
   `tell`, dump the fitted kernel via `opt.base_estimator_.kernel_`. For each
   dimension, ratio = `length_scale / (bound_high − bound_low)`. Healthy: 0.1–0.5.
   Pathological: <0.01 (overfit to noise) or >2 (kernel claims everything is
   the same). Add this as a one-shot print in `cmd_propose` behind `--debug`.
2. **If pathological, pin priors:** swap the default kernel for
   `Matern(length_scale=[0.3*(b-a) for each dim], length_scale_bounds="fixed")`
   in `build_optimizer` for helical only. Loses adaptation but buys stability.
   skopt accepts a custom `base_estimator` kwarg — no fork needed.
3. **Until lengthscales stabilize (~30 real points), don't trust CL.** Use
   `strategy="cl_max"` (most exploitative, treats picks as already-good →
   smallest distortion to subsequent picks) at q=2 only. This is counterintuitive
   but right: with bad kernel info, *less* CL distortion is safer than more.

**When to revisit:** every 10 new helical points, rerun the diagnostic. Once
all dim ratios are in 0.1–0.5 stably, switch to `cl_min` q=3.

### Q3: autoresearch_loop.py — auto-evaluate or stay human-gated?

**Problem.** Async batch only pays off if `cmd_evaluate` fires as soon as
each pipeline finishes — otherwise pending rows linger and the next `propose`
gets stale info. But auto-evaluation on a corrupt `summary.json` would
silently poison the leaderboard. We have one known case of that already
([[harvest-denominator-bug]] — the corrected sob was 3% off and the GP would
have happily learned the wrong shape for many batches).

**Recommendation — gated auto-eval with three sanity assertions:**
1. **Harvest writes a `summary.json` + a `harvest.ok` marker** only after
   passing internal checks (file count ratios per [[grid-job-completion-check]],
   non-NaN sob/calo, ce_simulated_events > 0). One-line change in `cmd_harvest`.
2. **`autoresearch_loop.py` polls** for `harvest.ok` across pending configs
   (cheap directory listing every 5 min). On hit, runs `cmd_evaluate` with
   three assertions before the leaderboard append:
   - `0 < sob < 10` (current best 2.71; a value outside this is sensor noise)
   - `0 < calo_per_pot < 1e-4` (orders-of-magnitude sanity)
   - `0.05 < ce_files / ce_njobs_configured < 1.0` (lost-job fraction in
     plausible range — guards against the denominator bug regressing)
   Any assertion fails → leave pending row, log to `autoresearch_loop.errors`,
   page the human (write to stderr, no Slack ceremony).
3. **Human-gated escape hatch:** `--manual-eval CONFIG` flag on the loop
   driver to suppress auto-eval for a specific config if it's known weird.

**What to NOT automate:** `cmd_propose` itself stays human-triggered. The
"submit q new configs" call is the only place a human sanity-checks the
proposed geometries before grid resources commit. Pure-loop autonomy is a
future decision once we have 10+ successful auto-evals on record.

**Definition of done:** loop survives 5 consecutive auto-evals without a
human-triggered correction. At that point, consider relaxing the assertions
or adding more (e.g. preflight-pass requirement on proposed geoms before
they hit the grid).
