# GP density-cloud rendering gotchas

**Type:** concept
**Status:** active
**Updated:** 2026-05-28 (v111repro_twist A/B closed the v111 anomaly to cross-pipeline metric incompatibility: at v111's exact 4D knobs the v2 pipeline produces sob=1.53/calo=2.09e-6, matching the GP cloud rather than v111's mmackenz table.org spec of sob=2.12/calo=1.62e-6)

## Root cause (2026-05-26): N_crit gate threshold mismatch
The "GP fit bias" framing below is INCOMPLETE — the dominant cause is that
top-3 champions are **excluded from GP training** by an over-aggressive
N_crit gate. Two filters use different thresholds:

- **Training** (`gp_predict_helical.py:131`): drops rows where
  `_ncrit(dx, dy, angle) > nsteps` with `nsteps = KNOWN_NSTEPS.get(cfg,
  DEFAULT_NSTEPS=100)`. So the gate is effectively `ncrit > 100`.
- **Sobol cloud** (`gp_predict_helical.py:202`): drops rows where
  `ncrit > nsteps_budget = 2000`.

Top-3 ncrit values (helicalL02=11,179 / graph023=1,551 / helical041a=227)
**all exceed 100**, so the GP never sees them during fit. Direct probe
(2026-05-26): GP's nearest Sobol neighbor to L02 (normalized-L2 = 0.016)
predicts calo=7.39e-6 vs observed 2.46e-6 (2.2× over) — and the 133 Sobol
samples within 0.05 of L02 all predict calo ∈ [5.3e-6, 8.6e-6], a band
that never touches the true value. Bias is structural training
exclusion, not kernel under-fit.

Deeper issue: `_ncrit` measures tessellated-solid self-intersection only.
After the 2026-05-21 G4TwistedBox dispatcher landed
([[tessellated-solid-facet-orientation]] / `tsda.helical.useTwistedBox`),
the constraint is moot for twisted-box runs (analytic solid, no facets).
The gate currently filters real twisted-box results en masse.

**Fix landed 2026-05-26** (`gp_predict_helical.py`): added
`_use_twisted_box(config)` helper that reads
`<grid>/<config>/geom/autoresearch_<config>_geom.txt` — absent or
key-missing means twisted-box (deployed-lib default since May 21).
Training-side N_crit gate now skipped when twisted-box. Sobol-side
gate dropped entirely (`buildable = np.ones(...)`); future tessellated
A/B would need per-pick re-gating. Empirical impact: GP training
**125 → 189 rows** (+64 previously dropped), Pareto frontier **630 → 85**
(GP no longer extrapolating into unanchored regions), new picks reach
sob=3.30 / calo=1.44e-6 (vs L02's 3.33 / 2.46e-6 — GP now predicts a
better champion exists at that region but it's an unverified prediction).

## Summary
The Sobol-sampled GP cloud in `overlay_gp_predictions_helical_mpl.py` can
silently *fail to envelope* the actual top-3 obj points (helicalL02,
graph023, helical050a) even though the GP technically predicts that region.
Two compounding effects: (1) the high-sob tail of Sobol samples is too
sparse to register against the LogNorm density colormap, and (2) the GP
under-predicts calo in the high-sob region (the same late-half log-calo
bias of −0.80 that forward-LOO calibration found). Result: gold-star
overlays of true champions sit "beyond" the visible cloud — but that's a
rendering artifact, not a GP-extrapolation failure.

## Key facts

### Sparse-tail invisibility
- Of 8.4M Sobol predictions (`PRED_TSV = gp_predictions_helical.tsv`):
  - GP sob range: [0.24, 3.71], 99th percentile = 3.23
  - **Only 1.1% (93,393 samples)** land at sob ≥ 3.2
  - `np.histogram2d` bins [230, 200] over [0,1.15] × [−8,−4] log calo;
    rare bins hold ~1 count and disappear under viridis+LogNorm
- Top-3 obj sob/x_scale values: L02 ≈ 1.0+, graph023 ≈ 1.0+, helical050a ≈ 1.0+
  — at or just past the visible density falloff at x ≈ 0.95

### GP under-predicts calo at high sob
- At sob ≥ 3.2: GP-min calo = **3.14e−6**
- Actual top-3 calo: **2.46e−6 (L02), 2.62e−6 (graph023), 3.08e−6 (helical050a)**
- Two of three sit *below* the GP envelope's lower edge
- Magnitude (≈2.3× under-prediction in linear calo) matches the late-half
  log-calo bias of −0.80 measured by `/tmp/residuals_over_iter.py`

### Why the visualization mismatch is structural, not a bug
- Density colormap rewards bulk; champions live in tails → invisible by
  construction unless you switch to scatter+alpha or contour-of-percentile
- Even with a perfect renderer, the GP-predicted lower-calo envelope at
  high sob is biased high — true champions can punch through the floor
- These two effects compound: the cloud is faint where champions live,
  AND its lower edge is too high there

### Low-calo asymmetry (2026-05-26): why no cloud below ~1e-7
The mirror of the high-sob blind spot, with one extra failure mode:

1. **calo=0 rows silently dropped from log-calo fit.** `gp_predict_helical.py:218`
   masks `pos = y_calo > 0` because `log(0)` is undefined. Currently 1
   leaderboard row (sob=1.04, calo=0) is excluded without further
   accounting — just a `dropping 1 rows with calo<=0` print at fit time.
2. **Sparse-tail invisibility (low end).** 15 observed configs sit in
   `0 < calo ≤ 5e-7` (sob 0.19–1.04). GP predictions can reach there:
   2,530 of 8.4M Sobol samples have predicted calo ≤ 5e-7 — but at
   **0.03% of the cloud**, the histogram bins hold ~1 count and vanish
   under LogNorm exactly like the high-sob tail does.
3. **Hard predicted floor at 2.34e-7.** Cloud min predicted calo = 2.34e-7;
   **zero** Sobol samples predict ≤ 1e-7. The WhiteKernel sits at its
   upper rail (`noise_level_bounds=(1e-5, 1e-1)`, rails to 1e-1) which
   noise-floors log-calo predictions. The GP cannot drive predicted calo
   arbitrarily low because the absorbed noise term dominates at that scale.
   Same kernel pathology already documented in `bo-helical` for the high-sob
   end.

### Mechanism of the 2.34e-7 floor (2026-05-26, agentic investigation)
Re-fit on current 188-positive-row training set confirms:
- Fitted kernel: `0.962^2 * Matern(length_scale=[0.1,0.1,0.1,0.1], nu=2.5)
  + WhiteKernel(noise_level=0.1)` — every length-scale railed to lower
  bound 0.1, noise railed to upper 0.1 (dual rail).
- `_y_train_mean = -12.657` ⇒ `exp(-12.657) = 3.18e-6`. With
  `normalize_y=True`, posterior mean far from any support point reverts
  toward `_y_train_mean`, NOT toward the low-calo cluster mean.
- 16 low-calo rows (calo ≤ 5e-7) cluster in a **narrow dy basin**:
  `dy_norm ∈ [0.0, 0.23]` (i.e. `dy ∈ [40, 123]` raw). With length_scale=0.1,
  only Sobol points within ~0.3 normalized of this basin feel any pull;
  outside, the noise rail (σ²=0.1 in normalized log-space) damps each
  row's leverage on μ.
- At the low-calo support points themselves, GP under-predicts by up to
  +3.5 nats (e.g. `graph002` neighbor of low-calo `graph015`: observed
  log=−16.00 vs predicted log=−12.46). Same mechanism the forward-LOO
  calibration found at the champion regime: GP reads sub-population rows
  as "high-variance scatter around bulk mean" rather than fitting them.
- The 2.34e-7 floor isn't a mathematical bound — it's the closest a Sobol
  point gets to the dy-basin cluster, partially pulled toward 3.18e-6 by
  the noise rail.

### `graph015` is the calo=0 row
`dx=0.456, dy=307.1, hl=184.9, ang=476.7, sob=1.04, calo=0.0`. Mid-range
params, meaningful sob — almost certainly a harvest artifact (zero events
survived the calo branch), not a feasibility-zero. Silently dropped by
`pos = y_calo > 0` mask at `gp_predict_helical.py:218`. **Open**: re-harvest
to confirm, then decide impute (0.5×min positive) vs broken-flag.

### Renderer bin occupancy (low-calo end)
For the 2,530 Sobol predictions with calo ≤ 5e-7:
- They concentrate in `sob/x_scale ∈ [0.12, 0.68]` (low-sob region, not
  the champion regime) → only **374 of 19,320 candidate bins** occupied
  (1.9%), max count = 24, 39% of occupied bins hold a single count.
- `LogNorm(vmin=1, vmax=527682)` (`overlay_gp_predictions_helical_mpl.py:182`)
  has 5.7-decade dynamic range; count=1 to 5 bins sit in dark-purple
  bottom-of-cmap, indistinguishable from masked-zero at 140 dpi.
- v2 magenta-star observations themselves ARE visible (15/16 with
  `calo ∈ [1.12e-7, 5e-7]` clear of `ylim` floor 1e-8); only `graph015`
  (calo=0) is unplottable on log-y.

### Fix path — Step A + C landed 2026-05-26
**Step A (WhiteKernel cap, landed).** `gp_predict_helical.py` line ~53
`noise_level_bounds=(1e-5, 3e-2)`. Empirical calibration:
- cap=1e-1 (baseline): floor 2.34e-7, Pareto 85, sob∈[0.24, 3.71]
- cap=1e-2 (overshoot): floor 1.13e-8, Pareto 312, BUT sob∈[−1.06, 9.56]
  and calo_max=1.44 — kernel unconstrained, picks 4–7 had sob<1 (broken)
- **cap=3e-2 (sweet spot, landed):** floor 5.47e-8, Pareto 169,
  sob∈[0.03, 4.67] (clean). Low-calo rows pull μ near the dy<0.23 basin
  without freeing the GP to extrapolate beyond training range.

**Step C (graph015 imputation, landed).** `gp_predict_helical.py`
`_fit_and_sample` imputes calo=0 rows as `0.5 × min(positive y_calo)` =
5.60e-8 before log-fit. Direct ROOT probe (`/tmp/probe_calo_bins.py`)
confirmed graph015's `TargetMuonFinder/stopmat` has 8 bins with **no**
calo crystal materials (vs helicalL02 16 bins with `CarbonFiber=1`).
Real physics zero — geometry absorbs all calo-bound muons (dy=307,
hl=185, ang=477 — full helical plug fills the muon path). The imputed
anchor seeds a new low-calo basin in the picker around dy≈300.

**Post-fix picker behavior** (8 picks from `gp_explore_picks.tsv`):
picks 0–1 sit in the established dy∈[112, 119] champion regime
(sob 2.4–3.8, calo 6.1e-7 to 1.94e-6); picks 2–7 cluster at dy∈[295, 326]
mirroring graph015's geometry, with calo dropping monotonically to
5.47e-8 (pick 7). The cloud now reaches the low-calo gold stars
visually — see `gp_predicted_helical_cloud_mpl.png` regen 2026-05-26.

**Step B (renderer, not landed).** PowerNorm(gamma=0.3) instead of LogNorm
+ scatter+alpha pass for `calo_pred ≤ P1`. Deferred: Step A alone closed
the gap; Step B is cosmetic polish.

**Heteroscedastic `alpha=1/N_jobs`** is still the "right" long-term fix
per `bo-helical.md:656-657`, but requires plumbing `n_jobs_harvested`
into leaderboard columns — significant effort for marginal gain.

### Frontier scope: background points can sit "beyond" the GP Pareto
The Pareto line in both PNGs (`gp_predicted_helical_cloud_mpl.png`,
`botorch_predicted_helical_cloud.png`) is computed **only over GP/BoTorch
posterior mean on the 4D helical space** (`cloud_plot.render_pareto` from
the Sobol prediction grid). mmackenz table.org background points are
real configs from *different topologies* — they can dominate the helical
frontier without violating optimality.

Concrete example (2026-05-27): the point at `(sob_rel≈0.48, calo≈1.07e-6)`
is **v111** — `config_v111: 2.50 cm Al plate with 80 mm hole, 4 mm × 170 mm
× 300 mm helical plug, 360 degree turn, 125 mm radius target with no hole`.
**Correction 2026-05-27 (later same day):** v111's no-hole target is NOT
the off-manifold knob — `HelicalMode.HOLE_RADIUS = 0.0`
(`autoresearch_bo_michael.py:380`) pins **every** v2 emit to
`stoppingTarget.holeRadius = 0.0000` with 38 foils @ 125 mm (verified on
`helicalFT06R00_00/geom/autoresearch_helicalFT06R00_00_geom.txt`). v111
lives on the same target manifold as the magenta v2 cloud.

**Root cause identified (2026-05-27, multi-agent investigation; supersedes
earlier same-day `tsda.rin` claim):** the dominant off-manifold knob is the
**helical solid implementation** — v111 was measured pre-2026-05-21 under
the broken tessellated `G4TessellatedSolid` (see
[[tessellated-solid-facet-orientation]]). Stuck-track absorption at facet
self-intersections killed background before it reached the calo, biasing
v111's calo low by ~2×. v2 runs under the twisted-box dispatcher
(`tsda.helical.useTwistedBox = true` default since 2026-05-21).

**Quantitative match:** the helical041a A/B re-run documented in
[[tessellated-solid-facet-orientation]] shows the same knobs giving
**tessellated calo=2.97e-6** vs **twisted-box calo=6.49e-6** — a **2.2×
inflation** that matches the v111-to-v2 offset exactly. The tessellated
v111 underreports calo by the same multiplicative factor.

**`tsda.rin` hypothesis REFUTED:** earlier same-day claim that Option A
coupling was the dominant knob does not survive leaderboard data. Configs
that happen to render at rin=80 mm (small-dy region; rin formula =
`ceil(√(dx²+dy²)) + 2`) have **lower** median calo (3.62e-6) than the
rin>110 cluster (4.44e-6) — opposite direction from the hypothesis. The
FT06R00_00 reference (rin=115, dy=112) is at calo=1.04e-5, an order of
magnitude above the rin=80 cluster. Direction of rin → calo coupling in the
leaderboard is the inverse of what the "absorber annulus" story predicts.

| Knob | v111 | v2 emit | Effect |
|---|---|---|---|
| Helical solid impl | tessellated (pre-2026-05-21, nsteps=5000) | twisted-box (May-21 dispatcher) | **Dominant**: ~2.2× calo inflation when stuck-track absorption removed |
| `tsda.rin` | 80 mm (fixed) | Option A `ceil(√(dx²+dy²))+2` (range 43–367 mm; median 95 mm in leaderboard n=174) | **Refuted dominance** — leaderboard rin∈[80] subset has *lower* calo than rin>110 |
| `stoppingTarget.foilTarget_supportStructure` | default `true` | `false` (overlap-suppression) | Minor: <5% — W wires at r=125 mm outside forward muon path |
| `ds.lengthRail2/3` | default (4160/5500 mm) | 0.1 (overlap-suppression) | Minor: <2% — rails at z=4400+ mm catch only fastest escape muons |

**Action implication:** rin promotion is NOT recommended. rin is the only
defense against silent disc/plug sibling overlap
([[tsda-disc-helical-sibling-overlap]]); promoting it back to a free knob
re-opens the failure surface that drove the leaderboard purge. Current top-3
champions live at rin∈[111, 149] — they'd fail an `rin=80` pin. Sequencing
remains task #147 (hl4) → #146 (COL5).

**Cheap rin-pin Sobol test (2026-05-27):** filtered the existing 8.4M-row
`gp_predictions_helical.tsv` to the rin≤80 mm subset (`dx²+dy² ≤ 78²`).
Feasible fraction = 884,215 / 8,388,608 = 10.5%. Predicted ceiling drops:

| | sob_max | Pareto n | calo_min on frontier |
|---|---|---|---|
| Unconstrained (Option A) | 4.075 (dy≈132, rin≈135) | 772 | 2.66e-7 |
| rin≤80 pin (v111 style)  | 3.013 (dy=77–78, rin=80) | 611 | 2.66e-7 |
| Δ                         | **−1.063 (−26%)**       |     | unchanged |

The high-sob ridge clusters at dy∈[125, 138] (rin∈[128, 141]); pinning
rin=80 forces dy≤78 and the rin=80 top-10 saturates exactly at the
boundary, confirming the constraint is binding not redundant. Low-calo
end is unaffected (basin already lives at small dy). Net: pin costs 26%
of predicted sob ceiling without buying any calo improvement → rin must
remain free under Option A coupling.
Source files: `autoresearch_bo_michael.py:380` (HOLE_RADIUS pin),
`:410-413` (derive_rin Option A formula),
`leaderboard_bo_helical_v2.tsv` (rin_derived col 7), `/tmp/rin_pin_sobol_test.py`
(the filter script used for this test).

**Companion overlay:** `overlay_gp_with_rin80_pin.py` (next to
`overlay_gp_predictions_helical_mpl.py`) renders the rin≤80 Pareto as a
red dashed line on the standard cloud → `gp_predicted_helical_cloud_rin80_overlay.png`.
Gotcha: must invoke with `/usr/bin/python3` or the `.venv-botorch` interpreter —
`.venv-graph` has sklearn but NOT matplotlib (per
[[graph-runner]]:78-82), so the cloud_plot import dies with
`ModuleNotFoundError: No module named 'matplotlib'`.

Implication: when reading the PNGs, **magenta v2 stars** and
**cyan-diamond picks** live strictly on the BO's 4D search manifold;
mmackenz class markers and the orange **prior stars** do not. Orange
priors come from `HelicalMode.load_priors()`
(`autoresearch_bo_michael.py:415`) — these are 10 mmackenz hand-designed
`config_v100`–`v109`, `v111` configs scraped from
`/exp/mu2e/app/users/mmackenz/run1b/Run1BAna/workflows/config_v###/run1b_beam/geom.txt`.
Their `(dx, dy, halflength, angle)` values are in-domain, but the rest of
their geometry (target topology, COL5 material, foils) is NOT controlled
by the 4D BO — so v111 (the only prior with no-hole target, sob≈2.12,
calo≈1.62e-6) sits "beyond" the GP Pareto by the same mechanism as the
table.org background. "Beating the Pareto line" by any orange star is
**not** a GP failure mode and **not** a bad geometry — it's a ceiling
indicator hinting which off-axis knob to promote next.

### Mitigation options (not yet implemented)
- Add scatter+alpha layer for predicted points with `sob > P95` to make
  the tail visible alongside the density
- Plot calo-at-sob percentile bands (5th, 50th, 95th of predicted calo per
  sob bin) instead of pure density
- Apply the −0.80 log-calo bias correction to GP predictions before
  rendering (caveat: invalidates uncertainty quantification)

### Shared x-axis chokepoint (2026-05-30)
`cloud_plot.py:192` `ax.set_xlim(0, 1.4)` is the **single line** controlling
the x-limit on BOTH the static (`gp_predict_foils_cloud.py`) and animated
(`gp_predict_foils_cloud_anim.py`) renders, plus the helical equivalents
(`overlay_gp_predictions_helical_mpl.py`, `botorch_predict_helical.py`). All
four scripts import `cloud_plot.finalize(...)`, which calls `ax.set_xlim`.
Was 1.15 until 2026-05-30; widened to 1.4 so the GP-predicted Pareto frontier
stops railing the right edge of the foils cloud. To change again, edit one
line in `cloud_plot.py` — not the four caller scripts.

## Cross-links
- Related: [[bfield-at-helical-plug]], [[bo-helical]], [[batch-bo]], [[refresh-foils-slides]]
- Source files: `/exp/mu2e/data/users/oksuzian/autoresearch_grid/mmackenz_table_plots/overlay_gp_predictions_helical_mpl.py`,
  `/exp/mu2e/data/users/oksuzian/autoresearch_grid/mmackenz_table_plots/gp_predict_helical.py`,
  `/exp/mu2e/data/users/oksuzian/autoresearch_grid/mmackenz_table_plots/cloud_plot.py`,
  `/tmp/residuals_over_iter.py`
- Data: `gp_predictions_helical.tsv` (8.4M Sobol), `leaderboard_bo_helical_v2.tsv`

## Downstream consequence: picker collapse
The same −0.80 log-calo bias that hides champions in the cloud also
*biases the picker*. `compute_explore_picks` does Pareto-of-mean on the
GP posterior; if GP overstates calo by 2.3× in the L02-type basin, that
basin appears to violate the 2e−6 feasibility cap and gets skipped.
This is the mechanistic explanation for the empirical observation that
explore picks collapse into `dx∈[1.9, 2.4], dy∈[81, 110]` instead of
finding regions near the actual top-3 (`bo-helical` smoke A/B, see
`/tmp/picker_smoke_ab.py`). The pessimistic-calo plan
(`~/.claude/plans/zazzy-booping-ladybug.md`) only patches the *fallback*
prior for unobserved regions — it does NOT fix the fitted-bias on
in-distribution observations, so the picker keeps mis-ranking even
under that flag.

## Impl-tracing rule (2026-05-27): geom-file grep is NOT a reliable impl tracer
Grep for `useTwistedBox` in `<grid>/<config>/geom/autoresearch_<config>_geom.txt`
ONLY works for configs whose geom was emitted on/after **2026-05-26** when both
the C++ dispatcher and the Python FCL-emission line landed (tasks #134–136;
source mtimes `autoresearch_muse/.../constructTSdA.cc` 2026-05-26 10:46,
lib 10:51, tarball 10:56; `autoresearch_bo_michael.py:377` HELICAL_USE_TWISTED_BOX
env-gated, `:490-491` emits the FCL key). Pre-2026-05-26 geom files lack the
key entirely — the impl actually used at runtime is whatever
`Code_helical_base.tar.bz2` shipped to the worker.

### Deployed `Code_helical_base.tar.bz2` timeline (verified via .snap audit)
Daily NetApp snapshots of `/exp/mu2e/app/users/oksuzian/autoresearch_muse/.snap/`
preserve the actually-shipped tarball state at end-of-day. Tarball size +
mtime tracks impl:

| Snap | size | mtime | inferred impl |
|---|---:|---|---|
| ≤ 2026-05-21 | 56,081,079 | May 17 11:19 | tessellated (broken) — matches `.bak-2026-05-17-broken` exactly |
| 2026-05-22 → 2026-05-26 | **56,081,079** | May 21 00:29 | **still tessellated** (same size as broken-bak; the `.patched-twistedbox` sidecar was 59,813,044 bytes — clearly NOT what was deployed) |
| ≥ 2026-05-27 | 59,825,830 | May 26 10:56 | dispatcher tarball |

The `.patched-twistedbox` sidecar (59.8 MB, built 2026-05-20 23:19) was a
ready-to-ship build of the stacked-G4TwistedBox lib that **was not actually
deployed** until the 2026-05-26 dispatcher repackage. Consistent with
[[tessellated-solid-facet-orientation]] Key facts line 193-198:
*"The production Code_helical_base.tar.bz2 is the OLD tessellated lib
(swapped in for the helical050a_n5000 test on 2026-05-21, not yet swapped
back)"* and the defensive HELICAL_NSTEPS 100 → 5000 → 2000 flips were
nsteps bumps under the broken lib, not a flip to a clean lib.

### Corrected impl per geom-emit-date

| Geom emit date | Deployed lib | Actual impl |
|---|---|---|
| ≤ 2026-05-20 | tessellated (broken), `nsteps=100` | **tessellated**, all configs floored on GeomSolids1001 |
| 2026-05-21 → 2026-05-25 | tessellated (broken), `nsteps=5000` then `nsteps=2000` defensive | **tessellated under N_crit gate**; scan_logs blocks rows where N_crit > nsteps from leaderboard |
| ≥ 2026-05-26 | dispatcher tarball (default `useTwistedBox = true`) | per FCL key, default twisted-box |

**Confirmed via direct inspection (2026-05-27):** FT01–FT07, SR01/02, QR00,
PC01–03, F01, NG/CB/P, helical050a_n5000, graph015 geom files all **lack
the `useTwistedBox` key** because the FCL emitter didn't land until 2026-05-26.
Only FT08R00_00 (geom mtime 2026-05-26 17:20) onward carries the key.

### `leaderboard_bo_helical_v2.tsv` impl mixture (175 rows) — CORRECTED
- **Pre-2026-05-21 broken-tessellated rows:** ~10 (`graph*`, `helical050a_n`,
  `helicalH01`); mostly retro-scan flagged → `.broken.tsv` sidecar (#150–151).
- **2026-05-21 → 2026-05-26 tessellated-under-N_crit-gate rows:** ~120
  (FT01–FT07, SR/QR/PC/F01/NG/CB/P cohorts). These were run under the SAME
  broken tessellated lib, but the scan_logs gate + nsteps=5000→2000 ceiling
  was supposed to reject configs whose N_crit exceeded the nsteps budget.
  scan_logs imperfections (per [[scan-broken-codes-too-narrow]] and the
  retro-scan flip in tasks #143-144) mean some are still tainted at lower
  severity than the pre-May-21 cohort.
- **Post-2026-05-26 dispatcher-era rows:** ~12 (FT08, TWB A/B pairs) —
  explicit per-row tracer via `useTwistedBox` key; the only era with
  guaranteed-clean twisted-box.
- **mmackenz priors** (10 rows `v100`–`v109`, `v111` via
  `HelicalMode.load_priors()` at `autoresearch_bo_michael.py:415`) are
  tessellated-era. The v111 "beyond Pareto" anomaly is the tessellated-vs-
  twisted-box 2.2× calo offset documented in
  [[tessellated-solid-facet-orientation]], not an off-manifold geometry.

**GP training-set implication:** the dominant ~130/175 rows are tessellated
(broken-lib regime, modulated by N_crit gating after 2026-05-21). The
twisted-box regime is the small minority (~12 dispatcher-era rows). GP cloud
predicted calo therefore reflects mostly the tessellated regime; v111
"sitting below the Pareto" is consistent with v111 being in that same
regime, not below it. Cross-era twisted-box rows (FT08, TWB) read ~2.2×
higher calo per [[tessellated-solid-facet-orientation]] TWB01 A/B and
helical041a tess-vs-twist measurement.

**Operational consequence:** for any cross-era leaderboard comparison,
infer impl from the geom-emit *date* (against the 2026-05-21 / 2026-05-26
cuts above), not from the `useTwistedBox` key. Treat pre-2026-05-26 rows
as tessellated under varying N_crit gates; treat post-2026-05-26 rows as
twisted-box per FCL key.

## v111 anomaly status (2026-05-27): ruled-out chain, still unexplained
After correcting the lib-deployment timeline (`.snap` audit showed deployed
`Code_helical_base.tar.bz2` was tessellated through 2026-05-26, not
twisted-box), v111 sits in the same tessellated regime as ~130/175 v2
leaderboard rows, so impl-mismatch cannot be the 6× calo gap. Cumulative
ruled-out list (in order of elimination, with refuting evidence):

| Hypothesis | Status | Why ruled out |
|---|---|---|
| `tsda.rin` Option A coupling (rin=80 forced pin) | **Refuted** | rin=80 leaderboard subset has *lower* median calo (3.62e-6) than rin>110 cluster (4.44e-6); cheap Sobol rin-pin test costs 26% sob but doesn't move calo floor |
| Target hole topology (v111 no-hole vs v2 default) | **Ruled out** | `HelicalMode.HOLE_RADIUS = 0.0` at `autoresearch_bo_michael.py:380` pins every v2 emit to 0 (verified on FT06R00_00/geom) |
| Broken-tessellated stuck-track absorption (helical041a-style 2.2×) | **Ruled out** | v111 N_crit ≈ 33 (dx=4, dy=170, hl=300, angle=360) is far below nsteps=2000 budget → no GeomSolids1001, no stuck-track flood. Wrong regime. |
| Clean-tess kCarTolerance halo bias (TWB01-03 mechanism) | **Wrong sign + too small** | Tess clean A/B shows tess +1-12% *higher* calo than twist (TWB01: 6.55e-6 vs 6.49e-6). v111 is tess; if the bias applied, v111 would be slightly *over*-reported, not 6× under-reported. Direction inverted from what would explain v111. |

**Remaining live candidates** (next investigation steps when this priority resurfaces):
1. **Non-4D knobs**: v111 spec has degrader=2.5 cm Al plate (vs v2 default), COL5 material categorical (task #146 still pending promotion), `stoppingTarget.foilTarget_supportStructure` true (v2 forces false for overlap suppression), `ds.lengthRail2/3` default (v2 forces 0.1). Per-knob effect in earlier section ranked <5% individually but **never measured in combination at v111's knob set**.
2. **Cross-pipeline metric incompatibility**: v111's sob/calo come from mmackenz's `table.org`, not our v2 grid harvest. Different stage chain, different physics list, different denominators, different event counts. Numbers may not be cross-comparable.

**Cheapest discriminator next:** rerun v111's exact knob set through our v2
pipeline (current dispatcher tarball, `useTwistedBox=true`, force the 4D + degrader thickness + COL5 + target topology to v111 values). If calo lands at v111's ~1e-6, gap is a real non-4D-knob effect → promote degrader (or COL5) to BO knob. If calo lands at cloud ~6e-6, gap is cross-pipeline metric incompatibility → v111 is not actually a champion under our methodology and the orange star should be re-labeled.

**v111repro A/B result (2026-05-28):** `v111repro_twist` at v111's 4D point
(dx=2, dy=85, hl=150, ang=360) landed **sob=1.53, calo=2.09e-6, obj=1.321**
on the v2 pipeline (twisted-box, current dispatcher tarball, only the 4D
knobs forced to v111 values — degrader/COL5/topology left at HelicalMode
defaults). v111's mmackenz `table.org` spec is sob=2.12, calo=1.62e-6.
Twist landed near the GP cloud mean (sob~1.5-2.0, calo~3-6e-6) rather
than near v111's spec.
Implications:
- **Cross-pipeline metric incompatibility is the dominant hypothesis.**
  Even keeping degrader/COL5/topology at v2 defaults (which v111 spec
  varies), the v2-grid harvest reproduces the cloud envelope, not v111's
  ~1e-6 calo. Most of the 6× gap appears to come from pipeline
  differences (event counts, denominators, physics list, mu_beam stage
  chain), not from a missing geometry knob.
- **Orange-star "v111 = champion" claim is suspect under our methodology.**
  When recomputed under v2 grid harvest at the same 4D knobs, v111
  becomes a midpack point.
- **Non-4D knobs cannot be fully ruled out yet** — the v111repro_twist
  chain only forced the 4D, not the degrader/COL5/topology. To close that
  loop, a follow-up "v111repro_full" with all v111 non-4D knobs pinned
  would be needed; deprioritized because the dominant gap already closed
  to 2-3× with just the 4D match.
- **Tess A/B half closed:** `v111repro_tess` landed sob=1.55, calo=2.33e-6,
  obj=1.317. Tess +11% calo over twist (within TWB01-03 1-12% halo,
  direction matches); sob statistically identical. Both fall on cloud
  envelope; neither approaches v111 spec. Conclusion firm:
  cross-pipeline metric incompatibility, not tess/twist.

## Open questions / TODO
- Implement scatter-tail overlay so champions are visible without needing
  a separate gold-star pass.
- Refit GP on log(calo) with target-rebalanced training weight on the
  high-sob slice; check if the late-half bias collapses.
- Decide whether to report calo-bias-corrected predictions in the
  closed-loop picker (`compute_explore_picks`) — currently it uses raw
  GP mean and so inherits the same optimistic bias for unobserved
  high-sob regions.
- Diagnostic to run before refit: residual-vs-dim + residual-vs-magnitude
  on current leaderboard to isolate which of {heteroscedastic noise,
  kernel over-smoothing, target transform, train-distribution shift} is
  driving the −0.80 late-half log-bias.
