---
name: bo-foils
description: 5D BO over +12 extras (≤6 upstream, ≤6 downstream) of the 37-foil stopping-target base; no helical plug
type: project
---

# bo-foils — 5D extras-only stopping-target foil-stack BO

**Type:** project
**Status:** active (Phase 0 preflight PASS on +12 extreme-corner envelope 2026-05-28; awaiting first closed-loop round)
**Updated:** 2026-05-29 (parse_geom rIn round-trip fix when n_up=n_down=0)

## Summary
Third BO mode in `autoresearch_bo_michael.py` (select with `--mode foils`).
Opens a parallel BO line over the **stopping-target** foil stack, orthogonal
to [[bo-helical]]'s plug optimization. Motivation: 4D helical Pareto has
saturated (HV +1.6% over last 76 evals, hit-rate 62%→38%), so the next win
is a dimensionality lift, not more 4D evals. This mode pins the deployed
37-foil base (see [[stopping-target-foil-base-spec]]) and explores adding
up to 6 extras upstream and/or 6 downstream — `n_up + 37 + n_down` total,
all extras sharing one (rOut, halfThickness) triple. The helical plug is
**off** (`tsda.helical.build = false`, `hasTSdA = false`) so any movement
in (sob, calo) is attributable to the +12 envelope alone.

## Key facts

- **Search space (5D extras-only, locked):**
  - `n_up`                 ∈ Integer[0, 6]
  - `n_down`               ∈ Integer[0, 6]
  - `extra_rOut`           ∈ Real[50, 250] mm  (floor at 50 per operator decision; 80 was initial)
  - `extra_halfThickness`  ∈ Real[0.05, 1.0] mm  (half-thickness; full = 2×)
  - `extra_rIn`            ∈ Real[0, 50] mm
  - Source of truth: `autoresearch_bo_michael.py:FoilsMode.build_space`.

- **Base 37 foils pinned at deployed v02 spec** (NOT the documents-spec
  "100 µm" number — see [[stopping-target-foil-base-spec]] for the
  deployed-vs-design mismatch):
  - `BASE_ROUT_MM = 75.0`, `BASE_HALFTHICK_MM = 0.0528` (≈105.6 µm full),
    `BASE_HOLE_RADIUS_MM = 21.5`, `BASE_N_FOILS = 37`.

- **`extra_rIn` is necessarily a GLOBAL override.** `stoppingTarget.holeRadius`
  is a single scalar at `StoppingTargetMaker.cc:41` (getDouble) — applies to
  every foil, not per-foil. So when `n_up + n_down > 0`, the emitted
  `holeRadius = extra_rIn` overrides the base 21.5 globally. When
  `n_up == n_down == 0`, emission of holeRadius is skipped and the v02
  include's 21.5 survives. `is_buildable` rejects `rIn >= BASE_ROUT_MM` to
  avoid vanishing the base annulus.
  - **2026-05-29 round-trip fix** (`autoresearch_bo_michael.py:696`):
    `parse_geom` previously returned `extra_rIn = 0.0` when no
    `holeRadius` line was present, but that's exactly the corner where
    the v02 baseline 21.5 mm is in force. Result: round-trip
    `render_proposal → parse_geom` corrupted the no-extras corner from
    21.5 → 0.0, biasing any leaderboard re-load and `cmd_show_priors`-
    style audits. Fix: fall back to `self.BASE_HOLE_RADIUS_MM` when the
    regex misses, matching what `_geom_text` actually emits.

- **Phase 0 preflight result (2026-05-28):** all three extreme-corner
  configs PASS:
  - `foilsP0_AU` (n_up=6, n_down=0, rOut=250, hT=1.0, rIn=50) → 43-entry radii
  - `foilsP0_AD` (n_up=0, n_down=6, rOut=250, hT=1.0, rIn=50) → 43-entry radii
  - `foilsP0_AS` (n_up=6, n_down=6, rOut=250, hT=1.0, rIn=50) → 49-entry radii
  - All `total_hits=1 baseline=1 managed=0` — no `StoppingTargetFoil_*` in
    managed-overlap output. The full 5D box is buildable; no defensive
    clamp on search space needed.
  - Logs: `bo_foils_preflight/foilsP0_{AU,AD,AS}.log`.

- **No mmackenz priors.** `FoilsMode.load_priors` returns `[]`. mmackenz's
  v22-v50 foil-stack runs (consumed by [[bo-michael]]) are 7D over different
  knobs (rIn / halfLength4 / holeRadius / col5) and don't project onto this
  extras-only 5D space.

- **Empty-history bootstrap (gp_predict_foils.py):** because there are no
  priors and `BOMode.build_optimizer` uses `n_initial_points=0`, the
  closed-loop GP picker on round 0 builds its own Optimizer with
  `n_initial_points=q` (Sobol-seeded) — otherwise skopt raises
  "Random evaluations exhausted and no model has been fit". Smoke
  (`--mode foils --q 2 --max-rounds 1 --dry-run` on 2026-05-28) produced 2
  spatially-distinct picks across all 5 knobs.

- **Parallel strategy:** `cl_min` (matches [[batch-bo]] helical default).
  skopt's `cl_mean` warns about fake-y collapse with mixed Integer+Real
  spaces — `cl_min` uses the running minimum which is more
  collapse-resistant for the n_up/n_down Integer dims.

- **Closed-loop wiring (Step 4 complete 2026-05-28):**
  - `graph/state.py:32` Literal extended to `["helical", "michael", "foils"]`.
  - `graph/closed_loop.py:_import_gp(mode)` dispatches on mode arg; threaded
    through `node_predict_picks`, `node_refit_and_check`, `_dry_run`.
  - `graph/pipeline_io.py:mock_metrics` widened to accept 5D x; uses
    `_FOILS_KNOB_RANGES` and dim-agnostic `u[-2] * u[-1]` for the calo
    "more-material" direction.
  - New `gp_predict_foils.py` shim in `mmackenz_table_plots/`.

- **Side-fix:** HelicalMode `FOIL_COUNT = 38 → 37` at
  `autoresearch_bo_michael.py:379` (2026-05-28) — matches deployed
  v02 base. Pre-existing helical leaderboard rows unaffected (each
  config carries its own geom snapshot).

## Cross-links
- Related: [[bo-helical]] (parallel BO line; saturation motivated this),
  [[bo-michael]] (original 7D foil-stack mode this supersedes for
  extras-only),
  [[stopping-target-foil-base-spec]] (load-bearing base + scalar-holeRadius
  gotcha),
  [[batch-bo]] (cl_min strategy choice),
  [[closed-loop-bo-design]] (mode-generic barrier/leaderboard plumbing),
  [[closed-loop-runner]] (driver this rides on)
- Source files:
  `autoresearch_bo_michael.py` `FoilsMode` class (~L547),
  `autoresearch_bo_michael.py:379` (HelicalMode.FOIL_COUNT side-fix),
  `autoresearch_bo_michael.py:769` (SURFACE_OVERLAP_MANAGED regex with
  StoppingTargetFoil_),
  `autoresearch_bo_michael.py:790, 843` (cmd_preflight mode gate widened
  to foils),
  `graph/closed_loop.py` (_import_gp + 3 call sites),
  `graph/pipeline_io.py:mock_metrics` + `_FOILS_KNOB_RANGES`,
  `/exp/mu2e/data/users/oksuzian/autoresearch_grid/mmackenz_table_plots/gp_predict_foils.py`,
  `leaderboard_bo_foils_v1.tsv` (created on first append)
- External: [[mu2e-overlap-check]] (Phase 0 preflight recipe)

- **First closed-loop round (`foilsX01`, 2026-05-28):** all 10 Sobol-bootstrap
  picks PASS preflight end-to-end through the real grid pipeline — confirms
  the +12 envelope is not just buildable at the extreme corners (Phase 0)
  but also at interior Sobol-sampled points. No managed-volume overlaps
  across any of the 10 picks. Per-child logs at
  `graph_data/closed_loop_logs/foilsX01R00_{00..09}.log`.

- **Round 0 results (10 evals, 2026-05-28):** all 10 harvested cleanly,
  none rejected by scan_logs. Range: `sob ∈ [1.88, 3.32]`,
  `calo ∈ [8.2e-6, 2.4e-5]`, `obj ∈ [0.51, 1.55]` (α=1e5). Top by obj:
  - **R00_00**: n_up=2, n_down=4, rOut=236.6, hT=0.350, rIn=33.5 → sob=2.50, calo=9.5e-6, **obj=1.55**
  - R00_01: n_up=2, n_down=2, rOut=197.9, hT=0.339, rIn=32.4 → sob=2.81, calo=1.3e-5, obj=1.48
  - R00_05: n_up=4, n_down=2, rOut=164.5, hT=0.519, rIn=26.6 → sob=2.31, calo=9.9e-6, obj=1.32
  R00_07 (max extras: n_up=6, n_down=5, small rOut=64) gives highest
  sob=3.32 but worst-of-top calo=2.4e-5 → obj=0.94. Pattern: large-rOut /
  moderate-halfThick / mid-rIn picks dominate; max-extras-small-rOut
  trades into a worse calo penalty.

- **`numpy.int64` SqliteSaver crash (2026-05-28, foilsX01 round 0→1):**
  skopt's `Optimizer.ask` returns `np.int64` for `Integer` dims (n_up,
  n_down). closed_loop.py barrier + refit succeed, but the post-refit
  checkpoint write raises `TypeError: Type is not msgpack serializable:
  numpy.int64` in `langgraph/checkpoint/serde/jsonplus.py:_msgpack_enc`.
  Round 0 leaderboard is intact (written via flock-TSV, not the saver);
  only the round-1 state transition dies. Fix: cast Integer picks in
  `gp_predict_foils.compute_explore_picks` to native `int` before
  returning (e.g. `(int(p[0]), int(p[1]), float(p[2]), ...)`).
  Helical mode never hit this — all 4 dims are `Real`.

- **GP cloud at n=10 in 5D (`gp_predict_foils_cloud.png`, 2026-05-28):**
  Renders, but length-scales for dim 1 (`n_down`) and dim 4
  (`extra_rIn`) rail to the upper bound 1e3 — GP treats them as
  effectively flat. Honest under-training signal, not a bug.
  Predicted-cloud envelope `sob∈[1.86, 3.31]`, `calo∈[5.6e-6, 3.1e-5]`,
  82 Pareto pts. Use the rendered cloud as smoothed interpolation
  between the 10 obs, NOT for extrapolation. Re-render at n≥30 once
  more rounds land.
- **GP cloud at n=29 (foilsX01 + X02R00 + X02R01, 2026-05-28):**
  Dim 1 (`n_down`) length-scale freed up vs n=10, but dim 4
  (`extra_rIn`) still rails to upper bound 1e3 — rIn remains the
  worst-trained dim and the next to target with explicit picks.
  Frontier widened: `sob∈[0.86, 3.54]` (was 3.31), `calo∈[1.0e-6,
  3.6e-5]` (floor dropped ~5×), 97 Pareto pts.
  Renderer: `mmackenz_table_plots/gp_predict_foils_cloud.py` — must run
  under `.venv-botorch` (not `.venv-graph`; only botorch venv has
  matplotlib).
- **Per-round GIF animation** (`gp_predict_foils_cloud_anim.py`,
  2026-05-29): renders one cumulative frame per `foils<X##>R##` cohort
  by regex-splitting leaderboard config names (leaderboard row order =
  harvest order, since flock-TSV is append-only). 4 frames at X02 end
  (10→19→29→39 evals). **Non-obvious:** Pareto-count can DROP between
  frames (97→80 across X02R01→R02) — new picks dominate old frontier
  points; the GP "moves" rather than just "extends." Output:
  `gp_predicted_foils_cloud.gif`. Run under `.venv-botorch`; uses
  ImageMagick `/usr/bin/convert` for stitching (`imageio` not installed).
- **foilsX03 complete (q=10, max-rounds=5, 2026-05-29):** all 5 rounds
  resolved cleanly; pareto_hash walked `a8f16932 → ddf0adc1 → b30ac643 →
  62608fc9 → 6459d20d` — 5 distinct hashes, never converged on k=2 repeat.
  50 new evals → leaderboard at 74 lines (73 data). New frontier highs:
  sob peak 3.87 (was 3.52 at X02 end), calo floor 8.3e-7 (was 1.0e-6 at
  X02 end). **Operator takeaway: 5D foils BO frontier still expanding
  at 5-round / 60-eval budget — convergence-by-hash is the wrong stop
  criterion in early phase; use HV-delta or eval-budget cap instead.**
- **foilsX02 complete (q=10, max-rounds=3, 2026-05-28):** all 3 rounds
  resolved cleanly; pareto_hash walked `6b50bc44 → e881587c → 6e15e014`
  — frontier still moving at round 2→3 boundary (no convergence by
  k=2 hash repeat). 30 new evals → leaderboard at 38 lines (37 data
  rows incl. foilsX01 R00_09 missing). np.int64 msgpack fix
  (`gp_predict_foils.compute_explore_picks` int/float cast) held
  through 3 predict_picks invocations. **Followed by foilsX03** (q=10,
  max-rounds=5, pid 29851, started 2026-05-28T23:50) — 50-eval budget
  to push past current non-convergence.

## Open questions / TODO
- First closed-loop round (`foilsX01`) — children running mubeam/mustops_ce;
  Hand-seed 5-8 small-extras configs (n_up/n_down ∈ {0,1,2}, mid-range
  rOut/halfThick) in round 0 if the Sobol bootstrap proves too spread-out
  after eyeballing the picks vs the +12 envelope.
- No GP-cloud rendering for v1 (helical-side `cloud_plot.py` is GP+Sobol
  and 4D-specific; revisit after 20-30 evals if the leaderboard alone is
  hard to interpret).
- Convergence-poll gating: re-use helical's existing
  `pipeline.py` plumbing as-is — no foils-specific tuning until first
  round shows whether stage-out timing changes meaningfully when no
  helical plug is present.
