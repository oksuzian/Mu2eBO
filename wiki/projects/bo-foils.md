---
name: bo-foils
description: 5D BO over +12 extras (≤6 upstream, ≤6 downstream) of the 37-foil stopping-target base; no helical plug
type: project
---

# bo-foils — 5D extras-only stopping-target foil-stack BO

**Type:** project
**Status:** active (Phase 0 preflight PASS on +12 extreme-corner envelope 2026-05-28; awaiting first closed-loop round)
**Updated:** 2026-06-04 (v1→v2 6D prior reuse: 51 of 251 v1 rows — the n_up==n_down==6 subset — project onto the up==dn diagonal as priors; 200 dropped. Also: sob-only ridge differs from obj-champion — top-sob is foilsX08R04_08 at sob=3.93, rOut=124, hT=0.073; obj-champion foilsX07R01_03 at sob=3.60. FoilsMode does NOT touch foil-to-foil z-spacing — pitch inherited from v02 baseline via `geom_run1_a.txt` include; extras land in the next slot up/down on the same evenly-spaced grid as the base 37)

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

- **Foil-to-foil z-spacing is NOT a BO knob.** `_geom_text`
  (`autoresearch_bo_michael.py:602-647`) emits only the `radii` and
  `halfThicknesses` vectors and inherits foil pitch from
  `Offline/Mu2eG4/geom/geom_run1_a.txt` via the include at line 625;
  `StoppingTargetMaker` distributes N foils on that single deployed
  pitch. So `n_up=6, n_down=6` means "6 extras continuing the base
  pitch upstream + 6 continuing it downstream," NOT arbitrarily placed.
  Stack-spacing as a parallel BO line is flagged in the deck's
  open-questions slide but unimplemented.

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

- **No mmackenz priors.** mmackenz's v22-v50 foil-stack runs (consumed by
  [[bo-michael]]) are 7D over different knobs (rIn / halfLength4 / holeRadius
  / col5) and don't project onto this extras-only space. In **v1 (5D)**
  `load_priors` returned `[]` outright.
- **v1→v2 prior reuse (6D migration, uncommitted WIP 2026-06-01):** v2
  `FoilsMode.load_priors` no longer returns `[]` — it projects the
  **n_up==6 AND n_down==6 subset of `leaderboard_bo_foils_v1.tsv`** into the
  new 6D space. Of **251 v1 rows, exactly 51 qualify** (the other 200 have a
  different foil count and are silently dropped — their geometry has no v2
  representation). Each qualifying v1 row had a single *coupled* extras triple,
  so it lands on the **up==dn diagonal**: `x = [rOut, rOut, hT, hT, rIn, rIn]`.
  Both v1 champions (`foilsX07R01_03`, `foilsX08R04_08`) are in the 51, so the
  v2 GP starts knowing the best v1 regions — but the **off-diagonal (up≠dn)
  half of the space is unseeded**, which is the whole point of going 6D. These
  51 enter as priors in BOTH picker paths (`seeds = priors + history` in
  `botorch_predict.py`; same in the sklearn `cl_min` shim) — without them a
  fresh v2 run with an empty `leaderboard_bo_foils_v2.tsv` has nothing to fit.

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
  `botorch_predict.py` (standalone qNEHVI shim with `--mode {foils,helical}`;
  .venv-botorch; not wired into closed_loop; bounds + int-dim mask inlined
  in `MODE_SPECS` since .venv-botorch has no skopt; michael's mixed
  Real+Categorical space NOT supported),
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
- **GIF re-render is byte-identical when leaderboard hasn't grown** (2026-05-29):
  `gp_predict_foils_cloud_anim.py` is deterministic given a fixed leaderboard.
  Running it twice with no intervening rows produces an md5-identical
  `gp_predicted_foils_cloud.gif` (frame contents AND ImageMagick stitch
  output stable). Practical: on a "remake the plot" request, check
  `wc -l leaderboard_bo_foils_v1.tsv` against last commit's row count
  before re-rendering — if equal, the re-render is wasted.

- **Marp slide rebuild via npx** (2026-05-29 update): in-place rebuild of
  `docs/foils_talk.md` → `.html` works on this host with
  `npx -y @marp-team/marp-cli@latest --html --allow-local-files
  docs/foils_talk.md -o docs/foils_talk.html`. (`--allow-local-files` is
  required for `![](relative.png)` refs to inline.) Earlier claim that
  "no marp CLI is installed" is superseded — npx auto-fetches. The
  `.html` also references the GIF by filename
  (`<img src="gp_predicted_foils_cloud.gif">` at foils_talk.html:299),
  so swapping the GIF on disk updates the served page without re-running
  Marp; only the `.pdf` goes stale and still needs an off-host rebuild.

- **Per-round GIF animation** (`gp_predict_foils_cloud_anim.py`,
  2026-05-29): renders one cumulative frame per `foils<X##>R##` cohort
  by regex-splitting leaderboard config names (leaderboard row order =
  harvest order, since flock-TSV is append-only). 4 frames at X02 end
  (10→19→29→39 evals). **Non-obvious:** Pareto-count can DROP between
  frames (97→80 across X02R01→R02) — new picks dominate old frontier
  points; the GP "moves" rather than just "extends." Output:
  `gp_predicted_foils_cloud.gif`. Run under `.venv-botorch`; uses
  ImageMagick `/usr/bin/convert` for stitching (`imageio` not installed).
- **foilsX07 saturated at R01 (2026-05-31, mid-run R05 of max-rounds=10):**
  `saturation_report.py --prefix foilsX07` on 164-eval leaderboard reports
  `R01 Δbest=+1.424 round_max=2.178` (foilsX07R01_03 the global champion),
  then R02/R03/R04 all undershoot prior_max: Δbest = −0.51 / −0.19 / −0.86;
  R03 and R04 flagged `[SAT]` against the round-1 anchor gain. 30 evals
  after R01 have not produced a new champion. **Operator implication:**
  the remaining 5 rounds (R05-R09, 50 budgeted evals) are unlikely to
  beat obj=2.178 without changing the picker or the search space. The
  closed_loop has no built-in SAT-kill gate; manual kill of pid 2475792
  is the way to stop without burning the budget.
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

- **sob-only ridge ≠ obj ridge (n=251, 2026-06-01):** ranking by sob alone
  surfaces a different geometry cluster than ranking by joint obj. Top sob
  ties at **3.93** (foilsX08R04_08 and foilsX08R00_00, both n_up=6/n_down=6
  but rOut≈107-124, hT≈0.063-0.073, rIn≈1-4); obj-champion foilsX07R01_03
  sits at sob=3.60 with much larger rOut=160 and thicker hT=0.116. Pattern:
  the sob-maximizing ridge prefers thinner / smaller-rOut foils, which
  trade into higher calo and lose on joint obj. Operator takeaway: if a
  future question is "what maximizes S/√B alone" (e.g. CE-only physics
  case with calo deferred), the answer is NOT the obj-champion — it's
  foilsX08R04_08. Single-column sort: `awk -F'\t' 'NR>1' leaderboard_bo_foils_v1.tsv | sort -t$'\t' -k7,7gr | head`.

- **v2 6D first real-grid round PASS (`foilsY01`, q=3, 2026-06-01):** the
  6D schema ran end-to-end on the real grid for the first time — 6D geom
  built, preflight cleared, full pipeline (mubeam→run1b_mubeam→concat→
  mustops_ce→harvest), round-trip parse → `leaderboard_bo_foils_v2.tsv`
  (created on first append, 3 rows). Clean barrier, no orphans. Results
  (α=1e5): R00_01 obj=1.522 (sob=3.21), R00_02 sob=3.33/obj=1.349, R00_00
  obj=1.290 — **all well below v1 champions (obj=2.178, sob=3.93)**, as
  expected: cl_min round-0 railed every pick's downstream side to floor
  (`rOut_dn=50, rIn=0`) to probe the off-diagonal the 51 diagonal priors
  don't cover. **Physics read: all three cleared sob>2.8 with downstream
  extras collapsed → the upstream extras carry most of the S/√B signal;
  downstream contributes little at these picks.** Don't read R00 obj as
  competitive — it's information-buying about up≠ dn, not exploitation.
- **cl_min looks EXHAUSTED on the v2 6D surface (2026-06-02, strategic):**
  three consecutive cl_min campaigns have not beaten **obj=2.00**
  (`foilsY02R03_01`, itself below the v1 champ 2.178): Y02 climbed to 2.00,
  Y03 consolidated (best 1.899, no beat), **Y04 COMPLETE — per-round best obj
  1.39 / 0.68 / 1.90 / 1.96 / 1.89** (best 1.963, no beat). The R1=0.68 was a
  **transient** boundary dip, NOT a terminal collapse — cl_min escaped it on
  its own R2–R4 and recovered to the ridge. But the **plateau is now settled:
  four cl_min campaigns, none has cracked 2.00**, all topping ~1.9–2.0. The
  surface is mapped; cl_min reliably finds the ridge and reliably fails to
  exceed it. **Implication: the next lever is exploration (qnehvi) or a
  dimensionality lift (promote base holeRadius / halfThickness to a 7th knob,
  per the deck's "next steps"), NOT a 5th cl_min run.**
  - **Mechanism (diagnosed 2026-06-02 from Y04 geometry):** every Y04 pick
    railed `rOut` to **250** (the max), R1 also railed `hT` to **~1.0** — the
    big-thick-foil **boundary corner** — vs the champion's moderate rOut≈150 /
    thin hT≈0.05. The low obj is **low SOB (0.6–2.2), not a calo penalty**
    (calo is tiny there): big thick foils stop muons poorly → weak CE signal.
    This is the LIVE realization of the [[batch-bo]] n=193 note ("CL-min
    spends 8/10 picks on the rOut=250, hT=1, rIn=0 boundary corner —
    mode-collapse to a GP-predicted safe extreme"), amplified by the
    running-min lie getting more pessimistic as low-obj rows accumulate.
    **NOT a prior effect** — the single filtered prior can't pull the GP off
    29 history rows. qnehvi scatters AWAY from this exact boundary, so it's
    the right escape lever.
- **foilsY03 5-round campaign COMPLETE (q=3, cl_min, 2026-06-02):** first
  campaign run with all of today's fixes committed (filtered priors,
  retry-protected preflight, consolidated env-source). **15/15 evals landed —
  ZERO losses across all 5 rounds** (vs foilsY02's 4 losses), a clean
  production validation of the preflight cvmfs-flake retry
  ([[sourced-env-stderr-swallowed]]). **No new champion:** best
  foilsY03R01_00 obj=1.899; v2 leader stays foilsY02R03_01 obj=2.00. A
  consolidation run — filled in the 6D space, didn't exceed. Cloud refreshed
  to n=30 (1 prior + 29 foilsY), GP Pareto frontier 75→181. Deck (foils_talk)
  v2 coda updated to the n=30 numbers.
- **foilsY02 5-round campaign COMPLETE (q=3, cl_min, 2026-06-01→02):** the
  multi-round refit paid off — best obj climbed **1.71 (R0) → 2.00 (R3)**;
  champion **foilsY02R03_01 obj=2.00, sob=3.62** (approaches but doesn't beat
  the v1 obj champion foilsX07R01_03 at 2.178). Per-round best obj:
  R0 1.71 / R1 1.24 / R2 1.88 / **R3 2.00** / R4 0.61 — **R4 regressed hard**
  (obj 0.61/0.44), cl_min wandering into a low-signal corner late (the
  documented [[batch-bo]] cl_min late-collapse). **11 of 15 evals landed**
  (2 lost to the R0 cvmfs preflight flake, R01_01 + an R04 child to harvest
  `metrics_none`). **Caveat: this run used the OLD cached `load_priors`**
  (51 base-hole-mismatched priors) — the parent launched before the prior
  filter fix and holds the cached module, so the picker/prior code change does
  NOT apply mid-campaign (same long-lived-parent nuance as
  [[sourced-env-stderr-swallowed]]); the next launch uses the corrected
  1-prior version.
- **v1→v2 priors are base-hole MISMATCHED (bug, found by /code-review
  2026-06-01).** `FoilsMode.load_priors` projects each v1 row to
  `x=[rOut,rOut,hT,hT,rIn,rIn]` and carries its `(sob,calo)` as the y-value.
  But v1 `_geom_text` emitted `stoppingTarget.holeRadius = extra_rIn`
  **globally** (base 37 + extras) whenever extras were present, while v2 pins
  the base 37 at `BASE_HOLE_RADIUS_MM=21.5` and only the extras get
  `rIn_up/dn`. So the prior's y was measured with base-hole = `extra_rIn`, but
  the v2 x-point it's attached to builds base-hole = 21.5. **50 of the 51
  reused priors have `extra_rIn != 21.5`** (range 0–50, mean 15.9; only 1 near
  21.5). Because the base 37 dominate the 49-foil stack and hole radius
  strongly changes stopping material, both pickers (cl_min seeds via
  `gp_predict_foils`, qNEHVI seeds via `botorch_predict`) are trained on
  systematically mismatched (x,y) pairs. Net effect: the rOut/hT prior
  dimensions are clean (base unchanged v1→v2) but the rIn dimension — and the
  shared y — is biased. **FIXED 2026-06-01:** `load_priors` now keeps only
  rows with `abs(extra_rIn - BASE_HOLE_RADIUS_MM) <= PRIOR_BASE_HOLE_TOL_MM`
  (1.5 mm; ~0.83%/mm base-area sensitivity → ≤1.3% mismatch). **Live effect:
  51 → 1 prior** (only `foilsX07R05_07`, rIn=21.93, survives). The v2
  leaderboard's own history is now the primary warm start; the 50 dropped
  rows simply don't transfer to v2's fixed-base parameterization. To rebuild
  a richer warm start the only sound path is re-measuring v1 champions under
  v2 geometry (grid work). Regression: `test_audit_fixes.py:
  test_load_priors_drops_base_hole_mismatch`.
  **Duplicate-logic warning (2026-06-02):** the v1→6D projection exists in a
  SECOND place — `mmackenz_table_plots/foils_v2_loader.py:_load_v1_projected`
  (on /data; feeds the static GP cloud `gp_predict_foils_cloud.py`). It had
  its own unfiltered copy; the same `abs(extra_rIn-21.5)<=1.5` filter was added
  there so the cloud's GP trains on the same data the optimizer sees (else the
  cloud shows a belief the optimizer no longer holds). A 3rd function,
  `foils_v2_loader.load_history_all_v1_symmetric`, is ANIMATION-ONLY and
  intentionally projects every v1 row (no filter). Any future change to which
  v1 rows project must touch `load_priors` AND `_load_v1_projected` in lockstep.
- **Asymmetric-rIn champion pattern CONFIRMED across the top-5 (n=50,
  2026-06-03):** the 5 best v2 configs all share a geometry v1's *coupled*
  triple could not express — **moderate rOut (≈130–195, NOT the rOut=250
  boundary cl_min drifts to), thin hT, and a sharp rIn split: upstream solid
  (rIn↑=0), downstream fully holed (rIn↓=50) in 4 of 5.** Physically the
  downstream extras want a big hole, the upstream extras want solid foils.
  This is the concrete payoff of the 5D→6D lift — the optima live in an up≠dn
  region v1 was blind to — **even though the scalar obj still caps at ~2.0**
  (`foilsY02R03_01` obj=2.003, sob=3.62; next `foilsY04R03_00` 1.963). Top-5
  rows: foilsY02R03_01 / foilsY04R03_00 / foilsY04R03_01 / foilsY02R03_02 /
  foilsY04R02_02. Upgrades the n=1 note below into a settled pattern.
  - **rIn pegs at the RANGE EXTREMES — and the two ends mean different things
    (diagnosed 2026-06-03, all 50 evals):** rIn↑ distribution 39 solid(0) / 6
    mid / 5 max(50); rIn↓ 30 max(50) / 14 solid(0) / 6 mid. Physics:
    upstream-solid stops muons; downstream-holed lets the CE (+ beam core)
    pass to the detector. **rIn↑=0 is a HARD physical floor** (can't be more
    solid than solid — not wideable). **rIn↓=50 is the SEARCH-RANGE CEILING**
    (`build_space` caps rIn at 50) — pegging there is the classic sign the
    optimum wants rIn_dn > 50 but can't reach it. **ACTIONABLE: widen the
    rIn_dn upper bound (e.g. 0–100 mm) — a bigger downstream hole may be the
    2.0-plateau breaker that lives OUTSIDE the current box, which no amount of
    cl_min rounds can find.** Caveat: cl_min also collapses to boundary
    corners, so some pegging is picker-artifact; the up≠dn asymmetry argues
    real signal underneath. qnehvi (interior probe) or the widened range would
    disentangle.
  - **Only rIn_dn warrants widening — NOT rOut (2026-06-03).** The discriminator
    is *which* configs sit at the bound: for **rIn_dn the CHAMPIONS** (top-5)
    are pegged at 50 → optimum likely outside the box → widen. For **rOut the
    bound-pegs are the BAD picks** — best configs are interior (rOut_up ~105–160,
    rOut_dn ~160–190, both well inside [50,250]); `rOut_up=50` floor → obj
    0.9/−0.03, and `rOut=250` ceiling is where cl_min boundary-collapses (low
    sob). So widening rOut just hands cl_min more boundary to collapse onto;
    if anything the rOut high end is a dead zone to NARROW. Next-campaign spec:
    change **only** `rIn_dn: 0–50 → 0–100`, leave the other 5 knobs as-is.
  - **BLOCKER before widening rIn (found 2026-06-03):** widening `rIn_dn` past
    `rOut_dn`'s floor (50) creates an INVERTED-foil region (`rIn_dn >= rOut_dn`,
    hole bigger than outer radius). `is_buildable` rejects it
    (`autoresearch_bo_michael.py:98`), BUT the **closed-loop picker does not
    enforce it** — `gp_predict_foils.compute_explore_picks` has no is_buildable
    call, and the `--x-point` child path bypasses `propose_one`'s guard
    (`graph/pipeline_io.py:86`). Current ranges are safe ONLY by accident
    (`max(rIn)=50 == min(rOut)=50`). So naive widening → cl_min (which pegs at
    boundaries) piles picks at `rIn_dn=100`, half infeasible → preflight
    failures, wasted evals. **Fix first:** either (1) reparameterize the hole as
    a FRACTION of rOut (`rIn = f·rOut`, `f∈[0,0.95]` — always valid, scale-free,
    arguably more physical), or (2) add the is_buildable retry loop to
    `gp_predict_foils.compute_explore_picks`. See [[closed-loop-runner]].
  - **The fraction reparam is LOSSLESS — opposite of v1→v2 (2026-06-03).**
    `rIn = f·rOut` is an invertible coordinate change of the SAME geometry, so
    every existing v2 row transfers EXACTLY: `f = rIn/rOut`, rOut/hT unchanged,
    `(sob,calo)` valid because the physical foil is identical (no base-hole
    mismatch). So a v3 mode's loader is a pure `rIn→rIn/rOut` conversion — NO
    filtering (vs v2's `load_priors` which had to drop 50/51 because the
    geometry changed). All ~47 v2 evals + the 1 v1 prior reuse; the old data
    fills the low-f region and the new `f≤0.95` range opens big holes (rIn up
    to ~0.95·rOut) with NO infeasible region (f<1 ⇒ hole<rOut). Bonus: fraction
    is likely better-conditioned for the GP than the under-trained absolute-mm
    rIn dims. (rOut≥50 always ⇒ no div-by-zero.)
- **v3 / `foilsf` mode BUILT + launched (`foilsZ01`, 2026-06-03).** New mode
  `FoilsFracMode(FoilsMode)` (name `foilsf`): hole = fraction `f=rIn/rOut`,
  `f∈[0,0.95]` (`F_MAX`), `is_buildable` ≡ True, writes
  `leaderboard_bo_foils_v3.tsv`. `_geom_text`/`parse_geom` just wrap the v2
  methods with the f↔rIn transform (geometry layer unchanged). `load_priors`
  returns **51 lossless priors** (all v2 evals + the 1 v1 prior, `f=rIn/rOut`).
  Validated: 51 priors load, round-trip exact, dry-run cl_min immediately pegs
  `f_dn=0.95`/`f_up=0` (wants the big downstream hole), and a **rIn_dn=180 mm
  geom — impossible in v2 — PASSES real G4 preflight**. **Naming: foilsX (v1
  5D) → foilsY (v2 6D abs) → foilsZ (v3 6D fractional).** foilsZ01 = q=3,
  max-rounds 5, cl_min, thread `closed-d163308e`. Tests the hypothesis: does a
  downstream hole bigger than v2's 50 mm cap break the obj≈2.0 ceiling?
  (Y05 was killed at round 2 to pivot here.) Uncommitted.
  - **foilsZ01 R0 (preliminary, n=3): the reparam MOVED cl_min's collapse but
    didn't kill it.** All 3 R0 picks peg `f_dn=0.95` (max fraction) AND collapse
    `rOut_dn` to its FLOOR (50) → `rIn_dn = 0.95·50 ≈ 48 mm` — basically v2's
    old cap, reached via small foils, NOT the big absolute hole v3 was built to
    test (which needs big rOut_dn × big f_dn → rIn_dn ~190 mm). Those
    small-foil/full-hole picks are high-sob (~3.43)/high-calo (~2.3e-5) → obj
    only ~1.1, no beat. So in fraction space cl_min corner-seeks a DIFFERENT
    corner than v2 (v2: rOut→250; v3: rOut→50 + f→0.95) but still doesn't reach
    the big-absolute-hole region. **Implication if R1–R2 don't pull rOut_dn up:
    the fraction reparam is necessary but NOT sufficient — qnehvi (interior
    explorer) is still needed to actually probe `large rOut_dn × large f_dn`.**
  - **foilsZ01 R1 PROBED the big hole — and it FAILED (key result, n=6,
    2026-06-03).** R1 best pick was `rOut_dn=250, f_dn=0.95 → rIn_dn=238 mm`
    (impossible in v2) and **sob collapsed to 1.69** (obj 1.11) vs ~3.4 for the
    small-hole picks. Physics: a thin ring (`f=0.95`) at large rOut sits far
    from the beam axis → misses the muons → low signal. **Implications that
    UPDATE the earlier "widen rIn_dn = plateau-breaker" hypothesis:** (a) the
    v2 `rIn_dn=50` pegging was mostly **cl_min boundary artifact, NOT a real
    out-of-box optimum** — the big-hole region is bad; (b) **obj≈2.0 looks like
    a real ceiling, not a box edge**; (c) cl_min STILL boundary-collapses in
    f-space (pegs `f_dn=0.95`, the wrong region — the v2 champion is at
    `f_dn≈0.31`, a MODERATE hole). So the real lever is **qnehvi to explore the
    moderate-hole interior (`f≈0.3`) cl_min won't reach**, NOT further box
    widening. Confirm if R2–R3 keep pegging f_dn=0.95.
  - **foilsZ01 R2–R3 RESOLVE the watch-item: the f_dn=0.95 peg SELF-CORRECTED
    (2026-06-04, n=12 thru R03).** Once R1's wide-hole probes harvested sob≈1.69,
    the GP learned big holes kill signal and cl_min **moved into the interior on
    its own** — R02 best `f_dn=0.11` (obj 1.317), R03 best `f_dn=0.66`
    (obj 1.409). So cl_min did NOT need qnehvi rescue *here*; boundary-collapse
    is GP-data-dependent, not a fixed cl_min pathology. **Per-round best obj
    climbs 1.120→1.110→1.317→1.409 (R00→R03)** but stays **far below the v2 bar
    obj=2.003** — every wide-hole config is low-sob, and the climb back toward
    1.4 comes from *retreating* to small/moderate holes. **Verdict: opening the
    downstream hole does NOT break the obj≈2.0 ceiling; the ceiling is real, not
    a v2 box-edge artifact** — which is exactly what foilsZ01 was built to test.
    R04 (final round of max-rounds 5) running 2026-06-04; an optimistic R04
    won't leap 1.4→2.0, so v3 is expected to confirm the ceiling, not break it.
  - **foilsZ01 COMPLETE (2026-06-04, 15 rows, all 5 rounds, parent exited
    clean).** R04 **regressed** — its 3 picks returned to the big-foil/big-hole
    corner (`rOut_dn=250, sob≈3.1, calo≈1.9e-5`) for obj≈1.20, beating nothing;
    the optimizer found nothing better in the final round. **v3 champion =
    `foilsZ01R03_00`, obj=1.409 (sob=2.37, f_dn=0.66)** — peaked at R03. Final
    standings across all foils campaigns: **v1 champion `foilsX07R01_03`
    obj=2.178 (sob=3.60, coupled up==dn diagonal) remains the ALL-TIME best**;
    v2 best 2.003; v3 best 1.409. **Conclusions the campaign settled:** (1) the
    obj≈2.0 ceiling is robust under v2 (abs rIn) AND v3 (fractional rIn); (2)
    cl_min DID reach the moderate-hole interior on its own (R02 f_dn=0.11, R03
    f_dn=0.66) yet still couldn't break 2.0 — so **qnehvi-interior is NO LONGER
    a compelling lever** (that region got sampled, ceiling held); (3) decoupling
    up≠down (the entire 6D v2+v3 effort) never beat the 5D coupled-diagonal v1
    champion. **The foil-stack GEOMETRY line (rIn/rOut/halfThickness) is
    saturated at obj=2.178.** The one genuinely unexplored lever is foil-to-foil
    **z-spacing/pitch**, which `FoilsMode` currently PINS to the v02 baseline
    (deck open-questions slide) — that, not another rIn reparam or picker swap,
    is the real next dimensionality lift.
- **First asymmetric pick beats the diagonal (preliminary, n=1, 2026-06-01;
  note the prior bias above weakens this signal):**
  foilsY02R00_02 — up `(rOut=143, hT=0.05, rIn=23.96)`, dn `(rOut=250,
  hT=0.05, rIn=0)`, a genuinely up≠dn geometry — harvested **obj=1.711
  (sob=3.55, calo=1.84e-5)**, outscoring *every* foilsY01 row (best was the
  near-diagonal R00_01 at obj=1.522). First empirical signal that decoupling
  upstream/downstream extras (the reason for the 5D→6D lift) actually buys
  something the diagonal priors can't reach. **Caveat: single eval** — the
  remaining foilsY02 rounds confirm or overturn it; don't over-weight n=1.
- **v2 naming + leaderboard split (2026-06-01):** the **`foilsY` config-name
  series marks the 6D era**, parallel to `foilsX0N` = the v1 5D campaigns.
  v2 evals append to a **separate `leaderboard_bo_foils_v2.tsv`** (`v1` stays
  read-only prior source); don't `wc -l` v1 to gauge v2 progress. First v2
  campaign: `foilsY01` (q=3, `--max-rounds 1`, `--picker cl_min`,
  thread_id `closed-63c24563`) launched 2026-06-01 on uncommitted v2 code;
  round-0 cl_min picks all railed the downstream side to floor
  (`rOut_dn=50, rIn_dn=0`) and varied upstream — expected, since the 51
  priors all sit on the up==dn diagonal so EI probes the unseen off-diagonal.
- **A foils dim-count change must touch FOUR places in lockstep** (the v2
  6D cutover missed the last one): (1) `FoilsMode.build_space`, (2) the
  cl_min shim `mmackenz_table_plots/gp_predict_foils.py` (delegates to
  `build_space`, so auto-OK), (3) `botorch_predict.py` `MODE_SPECS["foils"]`
  lo/hi/int_dims, (4) `graph/closed_loop.py:_DRY_RUN_KNOB_LABELS["foils"]`.
  #4 was left at the old 5 labels → `_dry_run` threw
  `IndexError: tuple index out of range` at `closed_loop.py:593`
  (`labels[i]` for a 6-tuple pick) on the FIRST foils dry-run after cutover.
  Fixed to the 6D labels `(rOut_up, rOut_dn, hT_up, hT_dn, rIn_up, rIn_dn)`;
  the generic `x{i}` fallback only fires for modes absent from the dict, so
  a stale-but-present entry silently mismatches.

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
