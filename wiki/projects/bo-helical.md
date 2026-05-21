---
name: bo-helical
description: 5D BO over helical-plug inner namespace (dx, dy, halflength, z0, angle) with TSdA core + foils pinned at v111
type: project
---

# bo-helical — 5D helical-plug BO

**Type:** project
**Status:** active (**helical045 GLOBAL BEST obj=2.533 on 2026-05-18** — but top-5 are likely G4 sibling-overlap artifacts; see [[tsda-disc-helical-sibling-overlap]]. Refactor in flight: drop `tsda.helical.z0` from search space (Option A), couple `tsda.rin` to plug bounding radius, widen dy/halflen, add source throw + preflight overlap-check.)
**Updated:** 2026-05-18 (Option A coupling + preflight surface-check landed end-to-end on smoke geom)

## Summary
Second BO mode in `autoresearch_bo_michael.py` (select with `--mode helical`).
Optimizes the **inner** `tsda.helical.*` namespace (dx, dy, halflength, z0, angle)
with the [[tsda]] core + foil stack + degrader + COL5 all pinned at v111 values.
Different physics from [[bo-michael]] (foil-stack mode): the helical plug
provides calo rejection by absorbing low-energy beam particles before they
reach the calorimeter, complementing the foil-stack approach.

## Key facts
- **Search space (5D, all Real):**
  - `tsda.helical.dx` ∈ [0.5, 5.0] mm — mmackenz priors use {1, 2}
  - `tsda.helical.dy` ∈ [40, 110] mm — priors use {65, 85, 95}
  - `tsda.helical.halflength` ∈ [25, 300] mm — priors use {30, 75, 125, 150, 250}
  - `tsda.helical.z0` ∈ [4250, 4500] mm — priors use {4270, 4345, 4470}
  - `tsda.helical.angle` ∈ [60, 540] deg — priors use {90, 180, 360}
  - Bounds widened ~30% beyond prior set so GP can extrapolate slightly.
- **Pinned constants (v111-exact):**
  - TSdA core: `hasTSdA=true, r4=600, rin=80, halfLength4=12.5, z0=4195,
    materialName=StoppingTarget_Al`
  - Helical fixed: `nsteps=100, material=StoppingTarget_Al`
  - Foils: `holeRadius=0`, `radii = {125 × 38}` (bigger foils to block calo stops)
  - Degrader: `build=false, rotation=180`
  - COL5: `material1Name=COL5Poly`
- **Baseline:** `geom_run1_a.txt` + manually patched
  `tracker.inDS2Vacuum=true, ds2.halfLength=3825, ds.hasServicePipes=false`
  (mirrors v111 exactly). **NOT** `geom_run1_b_v06.txt` — that one configures
  a single-plate stopping target (`halfThicknesses={5.0}, radii={600,600},
  z0InMu2e=4195`) which is incoherent with the v111 38-foil stack we emit
  (`radii={125 × 38}`) and causes `VirtualDetector_ST_In outside DS2Vacuum`
  in G4. See [[geom-run1a-vs-run1b]].
- **Best-known prior (v111):** `dx=2, dy=85, halflen=150, z0=4345, angle=360`
  → sob=2.12, calo=1.62e-6, **obj=1.958**.
- **Priors loaded:** 10 (v100, v101, v102, v103, v104, v106, v107, v108, v109,
  v111). v110 missing sob; v105 in the v100s range but has no helical plug.
- **Prior parsing:** TSV scraper only captures `tsda_helical_build` (boolean),
  not the inner knobs. `hel_load_priors()` cross-references TSV (for sob/calo)
  with `mmackenz_workflows/config_v##/run1b_beam/geom.txt` (for the 5 knobs).
- **Leaderboard:** `leaderboard_bo_helical.tsv`
  (cols: config dx dy halflength z0 angle sob calo alpha obj)
- **Proposal dir:** `bo_helical_proposals/`
- **Preflight dir:** `bo_helical_preflight/`

## Cross-links
- Driver: [[autoresearch-bo-michael]] (`--mode helical`)
- Autonomous-exploration driver: [[closed-loop-runner]] (multi-round Pareto
  picks; replaces the operator-paced "compute 5 picks → launch 5 chains →
  refit → repeat" loop used through helicalP01-P05)
- Sibling mode: [[bo-michael]]
- Related concepts: [[tsda]], [[scalarized-objective]], [[fixed-geometry-constraint]]
- Priors: [[mmackenz-priors]]
- Source: `autoresearch_bo_michael.py`
- Reference geom: `/exp/mu2e/app/users/mmackenz/run1b/Run1BAna/workflows/config_v111/run1b_beam/geom.txt`

## Phase 1 result (2026-05-16) — flat objective surface
- q=5 CL-mean batch (helical003–007) returned 5 geometrically distinct
  configs spanning the full bounds box. **All five harvested to
  `sob=2.72000, obj=+2.108`**, bit-identical to the helical002 baseline.
  ce_seen=310485 and ce_abs_eff agree to 16 digits across all six configs.
- Leaderboard has 7 rows; the helical knobs produce zero measurable signal
  in our pipeline. Concat outputs DO differ per config — the failure is
  somewhere between concat and run1b_mubeam/mustops_ce.
- See [[calo-constant-across-helical]] for full evidence + **definitive
  root cause**: helical-plug C++ does not exist in Offline `v13_12_10`
  (Run1Bak Musing). Only mmackenz's local patched Offline at
  `/exp/mu2e/app/users/mmackenz/run1b/Offline/Mu2eG4/src/constructTSdA.cc:322`
  consumes `tsda.helical.build`. **No further helical BO iterations until
  pipeline switches Musing to mmackenz's Muse area.**

## Offline-version dependency (critical)
- This project **requires** the patched `constructTSdA.cc` with the
  `build_helical` branch. Stock Mu2e Offline (any version up through
  `v13_12_10`) silently ignores `tsda.helical.*` parameters.
- mmackenz's `mmackenz_workflows/config_v100..v111` priors show real
  per-config calo variance precisely because they were produced against
  his patched build (`/exp/mu2e/app/users/mmackenz/run1b/build/al9-prof-e29-p094/`).
- Our pipeline's `MUSING` constant at `pipeline.py:45` points to
  `Run1Bak/setup.sh` → unpatched Offline.
- **2026-05-16 simple-swap attempt failed.** Modifying `write_code_tarball`
  to source `muse setup /exp/mu2e/app/users/mmackenz/run1b` and submitting
  helical002 to grid (clusters 84316127 mubeam + 27871333 run1b_mubeam,
  400 jobs total) returned only `.log` files. Worker stderr: `pushd
  /exp/mu2e/app/users/mmackenz/run1b > /dev/null: exit code 1`. **Grid
  workers only mount `/cvmfs/*`** — the entire `/exp/mu2e/app` namespace is
  invisible to jobs. Reverted same session.
- **Resolved 2026-05-17 via canonical muse-tarball path (option 7).**
  Final form: `/exp/mu2e/app/users/oksuzian/autoresearch_muse/` is an mgit
  sparse checkout (Mu2eG4 only) of `Offline/v13_12_10` + helical-plug.patch,
  backed by `SimJob/Run1Bak`. `muse build -j 8` then `muse tarball` produces
  a 56 MB `Code_helical_base.tar.bz2` whose `setup.sh` does
  `muse setup $CODE_DIR -q e29 prof p094` — the local lib wins via Muse's
  normal link/path order, no LD_PRELOAD needed. `pipeline.py:write_code_tarball`
  extracts this base, drops in the per-config geom + a `setup_post.sh` that
  extends `MU2E_SEARCH_PATH`, and repacks. An earlier same-day variant shipped
  the raw `libmu2e_Mu2eG4.so` + LD_PRELOAD (worked but non-canonical); retired
  in favour of `muse tarball`. See [[muse-backing-pattern]] for the build
  recipe and [[calo-constant-across-helical]] for the full incident trail.

## q=5 batch result (helical013-017, 2026-05-17/18)
Second q=5 CL-mean batch (post helical008-012). Final leaderboard rows:

| cfg | dx | dy | halflen | z0 | angle | sob | calo | obj |
|---|---|---|---|---|---|---|---|---|
| 013 | 0.50 | 110.0 | 25.0 | 4250 | 540 | 1.00 | 2.56e-08 | 0.997 |
| 014 | 0.50 |  92.5 |  31.9 | 4438 | 432 | 2.00 | 1.23e-06 | 1.877 |
| 015 | 0.50 |  93.8 | 257.6 | 4298 | 283 | 1.73 | 2.84e-06 | 1.446 |
| 016 | 0.50 |  85.6 | 102.2 | 4347 | 245 | **2.61** | 3.995e-06 | **2.210** |
| 017 | 2.55 |  85.6 | 130.8 | 4500 | 421 | 1.65 | 1.81e-06 | 1.469 |

## q=5 batch result (helical018-022, 2026-05-18)
Third q=5 CL-mean batch — GP refining the dx=0.5, dy~85-95, z0~4300-4400 ridge.

| cfg | dx | dy | halflen | z0 | angle | sob | calo | obj |
|---|---|---|---|---|---|---|---|---|
| 018 | 0.50 | 85.0 |  25.0 | 4396 |  75 | 2.68 | 5.45e-06 | 2.135 |
| 019 | 0.50 | 85.7 | 242.7 | 4250 | 372 | 1.61 | 2.35e-06 | 1.375 |
| 020 | 0.50 | 92.3 |  25.0 | 4346 | 428 | 1.96 | 9.22e-07 | 1.868 |
| 021 | 4.61 | 85.9 |  29.4 | 4287 | 210 | 1.75 | 2.89e-06 | 1.461 |
| 022 | 0.50 | 96.7 | 184.3 | 4423 |  66 | 2.49 | 4.60e-06 | 2.030 |

- helical016 still the global best (obj=2.210); helical018 is 2nd at 2.135.
- **Pattern: dx wants the lower bound.** helical010/014/015/016/018/019/020/022
  all at dx=0.5 (8 of last 11 evaluations). GP keeps pushing dx toward 0;
  consider widening `tsda.helical.dx` lower bound below 0.5 for Phase 2.
- **Cluster long-tail:** helical015 mustops cluster 27819553 and helical019
  mustops cluster 28186753 both took >4 hours to drain — large angle / large
  halflength geometry seems to make mustops_ce slower per job, dragging the
  whole batch's wall clock to ~6 hours.
- **Speed lever applied 2026-05-18:** `STAGES["mustops_ce"]["events_per_job"]`
  dropped 10000 → 5000 in `pipeline.py`. Total CE stats halve (1M → 500k);
  per-A/B noise test on helical001, sob agreement is ~0.4% which is well
  below the q=5 batch-to-batch spread (~0.5–1.5 sob units). Effective
  long-tail reduction depends on how much of the slow geometry's per-job
  cost is event-driven vs. fixed; first batch to benefit is helical023-027.
- **Every mustops_ce submit in the batch hit token contention** (helical018,
  019, 020 all FAIL submit-mustops_ce within 5 min of each other). Previously
  only mubeam/run1b_mubeam/concat were known to collide; mustops_ce is just as
  vulnerable. See [[concurrent-token-contention]].
- **NEW failure mode (helical019):** list-outputs succeeded but cached one
  stale `NNNNN.<hash>` path; harvest 4hr later choked on FileNotFoundError in
  calo extraction subprocess (ROOT couldn't open one file → entire calo step
  bailed → `calo_per_pot: null` → evaluate refused). Fix: re-run `list-outputs
  run1b_mubeam` to refresh state, then re-harvest. See [[stage-out-rename-race]]
  "latent variant" section.
- Six recovery scripts written this batch live in `/tmp/helical_resume_*.sh`;
  `helical_resume_mustops.sh` is new (mustops_ce submit→poll→list→harvest→eval).

## q=5 batch result (helical023-027, 2026-05-18 morning)
Fourth q=5 CL-mean batch — first batch run with the halved `mustops_ce`
events_per_job (10k → 5k); helical023 set a new global best.

| cfg | dx | dy | halflen | z0 | angle | sob | calo | obj |
|---|---|---|---|---|---|---|---|---|
| 023 | 0.50 | 110.0 | 300.0 | 4500 | 287 | **2.62** | 2.42e-06 | **2.378** |
| 024 | 0.50 |  87.1 | 168.0 | 4398 |  60 | 2.45 | 4.33e-06 | 2.017 |
| 025 | 5.00 | 110.0 |  25.0 | 4500 | 154 | 1.71 | 3.07e-06 | 1.403 |
| 026 | 5.00 |  40.0 | 300.0 | 4250 | 358 | 1.34 | 4.46e-06 | 0.894 |
| 027 | 0.50 |  98.6 |  25.0 | 4500 | 196 | 2.62 | 5.56e-06 | 2.064 |

- **helical023 is the new global best (obj=2.378)**, beating helical016
  (2.210) by 8%. It sits at the *upper-corner* of the GP's exploration —
  dy=110 (upper bound), halflen=300 (upper bound), z0=4500 (upper bound),
  angle=287, with dx pinned at 0.5 (lower bound) as the entrenched pattern.
  Same calo as helical015 (~2.4e-6) but with 50% higher sob — the upper-z0
  / upper-halflength corner appears to provide deeper calo rejection at
  equal CE pass.
- **dx=0.5 pattern now 10 of last 14 evaluations** (014/015/016/018/019/
  020/022/023/024/027). GP is confident in lower-bound dx; Phase 2 should
  widen the dx lower bound below 0.5.
- **First clean q=5 launch:** 300s stagger held through all 5 SUBMITS_DONE
  with zero token-race retries — first time at q=5. Then chains drifted into
  sync at the concat boundary (helical026/027 both submit-concat at 09:50
  and 09:54, both hit rename-race variant 2 on stale `state/mubeam_outputs.txt`).
  Both recovered via relist+resume. See [[stage-out-rename-race]] variant 2
  and [[concurrent-token-contention]] drift-after-launch note.
- **Wall clock:** 09:25 → 11:00 = **95 min** from first FULL_START to last
  CHAIN_DONE. helical018-022 batch was ~140 min. Halving mustops_ce
  events_per_job + cleaner stage-out (only two relist+resume detours, no
  mustops_ce token races) shaved roughly 30%.
- **Race recovery cost:** ~17 min per chain (FAIL → relist → re-submit →
  poll → list → mustops_ce); both 026 and 027 finished within the batch
  window so no chain held back the overall completion time.

## q=5 batch result (helical028-032, 2026-05-18 noon)
Fifth q=5 CL-mean batch — GP doubling down on the helical023 upper-corner:
028/029 are near-neighbours of 023 (same dy=110, halflen=300, z0=4500;
varying only angle), 031 probes the lower-bound dy=40 with high sob/calo,
032 explores the opposite anti-corner (dx=5, z0=4250).

| cfg | dx | dy | halflen | z0 | angle | sob | calo | obj |
|---|---|---|---|---|---|---|---|---|
| 028 | 0.50 | 110.0 | 300.0 | 4500 |  60 | 2.38 | 4.17e-06 | 1.963 |
| 029 | 0.50 | 110.0 | 300.0 | 4500 | **510** | 2.39 | **1.66e-07** | **2.373** |
| 030 | 0.50 |  97.0 |  25.0 | 4413 | 230 | 2.58 | 4.89e-06 | 2.091 |
| 031 | 0.50 |  40.0 | 257.0 | 4500 | 506 | **2.67** | 5.13e-06 | 2.157 |
| 032 | 5.00 | 110.0 | 251.9 | 4250 | 284 | 0.844 | **3.49e-07** | 0.809 |

- **helical023 still global best (obj=2.378);** helical031 enters at rank #3
  (2.157). dx=0.5 pattern now 14 of last 19 evaluations.
- **Angle is a first-class knob.** helical023/028/029 are geometrically
  identical except `angle` ∈ {287, 60, 510}. Calo spans **15×**: 2.42e-06
  (023) → 4.17e-06 (028) → 1.66e-07 (029). sob varies only 9% across the
  same trio. helical029 nearly matches helical023's objective (2.373 vs
  2.378) while sitting at the Pareto knee — best calo of any helical run.
- **GP-predicted Pareto knee confirmed.** Post-helical028 GP analysis
  predicted that the upper-corner geom at angle ~400-540 would hit calo
  ~4e-07 with sob ~2.5 (see `/tmp/gp_pareto.py` and
  `gp_predicted_helical_cloud.png`). helical029 observed 1.66e-07 and 2.39 —
  GP got the trend and order right, even underestimated calo improvement.
  Lesson: when geom is otherwise pinned, the GP's angle-only predictions
  are trustworthy enough to drive directed proposals.
- **dx=5 / z0=4250 anti-corner confirmed broken.** helical032 hit
  record-low calo (3.5e-07, ~7× lower than anything else seen) but sob
  crashed to 0.844 — CE acceptance collapses when the plug sits in the
  upper-stream low-z0 position. Validates the GP's entrenched dx=0.5 preference.
- **dy=40 (lower bound) still viable.** helical031 at dy=40 hit sob=2.67
  (highest sob in any batch). Smaller foils don't kill the CE arm if the
  plug is doing the calo rejection work.
- **NEW recovery scripts (2026-05-18):** `/tmp/helical_recover_listrun1b.sh`
  (re-list run1b after rename race + idle-wait for sibling arm_a's
  `state/mustops_ce_outputs.txt` before harvest) and
  `/tmp/helical_recover_evaluate.sh` (relist run1b + reharvest + reevaluate
  after stage-out rename race latent variant 1 silently nulls calo_per_pot
  in summary.json). See [[stage-out-rename-race]].
- **Original chain-script CHAIN_FAIL events are misleading noise** when a
  RESUME_* or RECOVER_* event for the same config preceded them — the
  recovery script will emit its own CHAIN_DONE once it succeeds. Read the
  event log latest-event-wins per config, not first-event-wins.
- **Wall clock:** ~95 min for 4 of 5 chains (matches helical023-027 pace);
  helical029 still resolving the relist+arm-A-mustops wait.

## GP calibration + Pareto cloud structure (2026-05-18)
Post-helical029 surrogate analysis using two standalone GPs (sklearn-side,
mirroring skopt's kernel: `ConstantKernel * Matern(nu=2.5) + WhiteKernel`,
`normalize_y=True`, inputs normalized to `[0,1]^5`; sob linear, calo
log-transformed). Trained on 35 points (10 priors + 25 helical).

**Calibration via leave-one-out (helical only, N=25):**
- sob mean residual −0.017, RMSE 0.265, MAE 0.21
- mean predictive σ 0.23; fraction |z|<1 is **0.48** (ideal 0.68) → GP is
  mildly **over-confident**. Trust the *direction* of GP predictions more
  than the magnitude of σ.

**Dense Pareto sweep** (`gp_predict_helical.py` + `overlay_gp_predictions_helical.py`):
- 8388608 (2^23) Sobol points across the 5D box → predicted (sob, calo) cloud.
- Achievable cloud has a sharp vertical Pareto wall at S/√B ≈ 0.78
  (foil-stack + plug ceiling on CE acceptance with the v111 surround).
- Pareto knee at (sob≈0.72, calo≈1.7e-07); **helical029 sits on the knee**
  (observed 0.768, 1.66e-07 in plot units after x_scale).
- 69-point non-dominated frontier from the dense cloud, extending from
  (~0.78, 5e-06) through the knee to (~0.32, 4e-08).
- helical029 calo (observed 1.66e-07) **beat the GP's prediction of ~4e-07**
  at this corner — GP got direction right, underestimated improvement
  magnitude.

**The BO α=250000 scalarization probes one Pareto-tangent point.** Each
proposal maximizes `sob − α·calo`, which picks the cloud point whose Pareto
tangent has slope α. To map more of the frontier, either:
1. multiplex α across the q-batch (`/tmp/gp_pareto.py` shows the
   λ-sweep — λ=50k → angle near 287, λ=2M → angle near 540), or
2. switch to a proper multi-objective acquisition (qNEHVI / qParEGO, BoTorch).

**GP-prediction validation (helical033-042 batches, 2026-05-18 PM/evening)**
Picked 10 points across the 69-pt GP Pareto frontier (ranks 0/8/17/25/34/42/51/55/65/68)
to test GP calibration at the predicted-best locations. Batch 1 (033-037)
complete; batch 2 (038-042) in flight, 2/5 done as of 19:04.

| cfg | GP sob | obs sob | sob % | GP calo | obs calo | calo % | obs obj |
|---|---|---|---|---|---|---|---|
| 033 | 2.77 | 2.65 |  96% | 4.97e-06 | 5.18e-06 | 104% | 2.132 |
| 034 | 2.57 | 2.52 |  98% | 1.55e-06 | 1.16e-06 |  **75%** | **2.404** |
| 035 | 2.61 | 2.58 |  99% | 2.30e-06 | 2.43e-06 | 106% | 2.072 |
| 036 | 2.30 | 1.27 |  55% | 4.10e-07 | 4.14e-07 | 101% | 1.166 |
| 037 | 1.40 | 1.89 | 135% | 3.13e-07 | 1.16e-07 |  37% | 1.881 |
| 038 | 2.55 | 2.52 |  99% | 4.20e-06 | 5.03e-06 | 120% | 2.066 |
| 040 | 2.50 | 2.39 |  96% | 9.85e-07 | 1.30e-06 | 132% | 2.261 |

- **helical034 is NEW GLOBAL BEST** (obj=2.404, beats helical023 by 1%). GP
  picked the geom (dy=109, halflen=290, z0=4479, angle=333) and underestimated
  its calo performance. Third "upper-corner" winner alongside 023/029.
- helical040 enters at rank #4 (obj=2.261). dx pinned at lower bound 0.5
  on **every** GP-picked frontier point — see widening probe below.
- **sob calibration**: excellent for batch 1 (96–104%) except at high-angle
  corner (036 dropped to 55%; 037 jumped to 135%). Batch 2 holds at 96–99%.
- **calo calibration**: batch 1 conservative (75–106%, obs ≤ pred at the
  knee). Batch 2 mildly **over-confident** at 120–132% — GP underestimates
  observed calo by ~25% in a different region of the frontier.
- Lesson: GP-frontier picks are trustworthy on sob (when angle is in the
  trained range) but calo calibration is region-dependent. Trust direction
  more than magnitude.

## Helical-plug geometry semantics (2026-05-18)
Verified against `/exp/mu2e/app/users/oksuzian/autoresearch_muse/Offline/Mu2eG4/src/constructTSdA.cc:60–90`:
- `tsda.helical.dx` and `tsda.helical.dy` are **half-widths** of the ribbon
  cross-section (mm). Full extent in beam-transverse plane is `2·dx` by `2·dy`.
  Code: `G4ThreeVector b1(-dx, -dy, 0), b2(dx, -dy, 0), b3(dx, dy, 0), b4(-dx, dy, 0)`.
- `tsda.helical.halflength` is the half-length along z (mm); ribbon spans
  `[z0 - halflength, z0 + halflength]`.
- `tsda.helical.angle` is total twist in degrees from upstream to downstream
  end, applied uniformly over `nsteps=100` extruded slices.
- mmackenz priors used dx ∈ {1, 2} mm (i.e. 2-4 mm full width); GP-favoured
  dx=0.5 mm corresponds to a 1 mm ribbon — already near the manufacturable
  limit for self-supporting Al shim.

## GDML dump recipe (2026-05-18)
Materialize any helical geom to GDML for visualization:
1. Write `gdmldump.fcl` in `<DATA_ROOT>/<cfg>/` containing:
   ```
   #include "Offline/Mu2eG4/fcl/gdmldump.fcl"
   services.GeometryService.inputFile : "autoresearch_<cfg>_geom.txt"
   physics.producers.g4run.debug.GDMLFileName: "mu2e_<cfg>.gdml"
   ```
2. `source setupmu2e-art.sh && pushd /exp/mu2e/app/users/oksuzian/autoresearch_muse && muse setup -q p094 && popd`
3. `export MU2E_SEARCH_PATH=<DATA_ROOT>/<cfg>/geom:$MU2E_SEARCH_PATH`
4. `mu2e -c gdmldump.fcl -n 1` (must be `-n 1`, NOT `-n 0`, or GDML write skips).
- helical034 confirmed: emits 4.4 MB GDML with `AbsorberPV`/`AbsorberS`
  helical-plug volumes inside DS2Vacuum.

## Current top-5 (2026-05-18 evening) — silent-overlap cluster

| cfg | dx | dy | halflen | z0 | angle | sob | calo | obj |
|---|---|---|---|---|---|---|---|---|
| **045** | 0.20 | 109.0 | 289.68 | 4479 | 333 | 2.65 | 1.174e-06 | **2.533** |
| 043 | 0.10 | 109.0 | 289.68 | 4479 | 333 | 2.63 | 1.015e-06 | 2.529 |
| 046 | 0.30 | 109.0 | 289.68 | 4479 | 333 | 2.62 | 1.136e-06 | 2.506 |
| 044 | 0.15 | 109.0 | 289.68 | 4479 | 333 | 2.63 | 1.258e-06 | 2.504 |
| 047 | 0.40 | 109.0 | 289.68 | 4479 | 333 | 2.59 | 1.023e-06 | 2.488 |
| 050 | 0.105 | 109.6 | 194.68 | 4496 | 460 | 2.45 | 6.52e-08 | 2.443 |
| 049 | 0.167 | 107.1 | 187.79 | 4498 | 293 | 2.62 | 1.99e-06 | 2.421 |

Top-5 are dx-clones at `(dy=109, halflen=289.68, z0=4479, angle=333)`. With
`tsda.z0=4195 + halfLength4=12.5 = 4207.5` (disc back face) and plug
upstream face at `z0 - halflen = 4189.32`, **all five overlap the disc by
~18 mm in z**. Gap-cluster reps helical049/050 (z0 placed downstream of
disc) underperform by ~4%, consistent with the overlap acting as free Al.
See [[tsda-disc-helical-sibling-overlap]].

## Option A coupling redesign (approved 2026-05-18)
**Search-space change:** drop `tsda.helical.z0`. New 4D space:
- `dx` ∈ [0.01, 5.0], `dy` ∈ [40, 400], `halflen` ∈ [25, 500], `angle` ∈ [60, 540]

**Derived knobs in `HelicalMode.render_geom`:**
- `tsda.helical.z0 = tsda.z0 + halfLength4 + halflen`
  (plug upstream face touches disc downstream face → no z-overlap by
  construction; downstream face at `tsda.z0 + halfLength4 + 2·halflen`)
- `tsda.rin = ceil(sqrt(dx² + dy²)) + 2 mm`
  (disc hole matches the plug's bounding circle plus 2 mm clearance —
  prevents disc/plug r-overlap when dy is widened past current 110)

**Source-side guard in `constructTSdA.cc:~350`:** throw if
`z0_helical - halflength < tsda.z0 + halfLength4` (defensive; render
should never produce this). See [[tsda-disc-helical-sibling-overlap]].

**Anchor re-evaluations to bridge leaderboards:**
- helical044 re-eval under Option A render (z0 will become
  4195+12.5+289.68 = 4497.18, ~18 mm downstream of current 4479) →
  delta against current obj=2.504 quantifies the silent-overlap bonus.
- helical049 re-eval → already in gap cluster, should be near-invariant.

**Bound widening rationale:**
- dy 40 → 400: BO has been pinned at 109 (upper bound). Disc r4=600 and
  coupled `rin=ceil(sqrt(dx²+dy²))+2` automatically keeps disc/plug clear;
  DS2Vacuum `ds.rIn=950` is the hard ceiling.
- halflen 25 → 500: BO pinned at 289-300 (upper bound). Joint with new
  z0-coupling, downstream face at `4207.5 + 2·500 = 5207.5 mm` still
  upstream of first ST foil at z≈5460.

## Preflight overlap-check integration (landed 2026-05-18)
`cmd_preflight` (helical mode only) now runs a Stage-2 surface check after
G4 init passes:
1. Materializes `<cfg>_surfacecheck.fcl` (`#include`s
   `Offline/Mu2eG4/fcl/surfaceCheck.fcl`, overrides
   `services.GeometryService.inputFile` to a per-config geom overlay that
   adds `g4.doSurfaceCheck=true` on top of the proposal's geom).
2. Runs `mu2e -c surfacecheck.fcl -n 1` in the same preflight workdir;
   ~7 min wall on `/exp` head node.
3. Greps for `Overlap is detected for volume <NAME>` lines, filters child
   names through `SURFACE_OVERLAP_MANAGED = r"^(TSdA|AbsorberPV|AbsorberS)"`,
   fails only on managed-volume hits.

**Stock-geometry baseline (load-bearing):** vanilla Run1Bak Musing
geom_common_current.txt emits **117 overlap lines** out of the box (114
FoilSupportStructure_NN:NN + StoppingTargetMother, 2 rails + DS3Vacuum, 1
VirtualDetector_EMC_0_Front + StoppingTargetMother). The whitelist exists
purely to suppress these — without it the smoke geom looks like 117
failures. See [[mu2e-overlap-check]].

**Helical plug volume name confirmed:** GDML dump of a smoke geom shows the
placement volume as `AbsorberPV:0` (G4Box) — the whitelist anchors on this.
Disc daughters are `TSdA[0-4]:0` (G4Tubs).

**End-to-end smoke verified 2026-05-18:** Option A render on
`helical_optionA_smoke` (x = [0.5, 109, 188, 333] → derived z0=4395.5,
rin=112) preflighted clean: 117 baseline hits, 0 managed hits → PASS.

## Envelope analysis (2026-05-18)
**No code-level envelope assertions** in `constructTSdA.cc:58–128` (`makeHelicalPlug`).
G4 would silently overlap and bias tracking if knobs poked past DS2Vacuum or
collided with the stopping target. Hard physical limits derived from geom:

| Knob | Current BO upper | Physical limit | Headroom | Constraint source |
|---|---|---|---|---|
| `dy` (mm)         | 110  | ~900 | **~8×**   | DS2Vacuum `ds.rIn=950`; TSdA `r4=600` is the only nearby structure |
| `halflength` (mm) | 300  | ~670 | **~2×**   | downstream face must clear first ST foil at z≈5460 |
| `z0` (mm)         | 4500 | ~5160 | ~660 mm | same ST-foil constraint, joint with halflength |

Computation of `vac_zLocDs23Split` (DS2/DS3 split) from
`DetectorSolenoidMaker.cc:254`:
```
vac_zLocDs23Split = ts.rTorus + 2·ts5.halfLength + 2·ds2.halfLength
                  = 2929 + 1250 + 7650         # ds2.halfLength=3825 override
                  = 11829 mm
```
DS2 vacuum spans z ∈ [4179, 11829]. Stopping target z0=5871 mm
(`stoppingTarget_CD3C_34foils.txt:18`); 38 foils × 22.222 mm deltaZ →
first foil at z ≈ 5460.

All three knobs (dy, halflen, z0) have substantial headroom. Recommendation:
widen to `dy ∈ [40, 400]`, `halflength ∈ [25, 500]`, `z0 ∈ [4250, 4800]`.
Caveat: still need preflight `mu2e -n 1` per proposal because constructTSdA
won't catch silent overlaps.

## dx widening probe (helical043-047, 2026-05-18 evening)
Optimizer has pinned dx at the lower bound 0.5 in 14 of last 19 evals plus
**every** GP-Pareto frontier pick. Bounds widened in
`autoresearch_bo_michael.py:374` from `Real(0.5, 5.0)` to `Real(0.1, 5.0)`.
Seeded 5 manual probes all pinned at helical034's other knobs (dy=109,
halflen=289.68, z0=4479, angle=333) with α=100000 and varying dx:

| cfg | dx (mm) | full width 2·dx |
|---|---|---|
| 043 | 0.10 | 0.2 mm — Al shim minimum |
| 044 | 0.15 | 0.3 mm |
| 045 | 0.20 | 0.4 mm |
| 046 | 0.30 | 0.6 mm |
| 047 | 0.40 | 0.8 mm |

- All 5 launched 18:15-18:35 with 300s stagger via
  `/tmp/launch_helical043_047.sh`. All through arm B by 19:05.
- GDML preflight on dx=0.1 builds cleanly (G4 geometry is valid at 0.2 mm).
- **Result**: dx widening paid off — helical047 set new global best at
  obj=2.488 (dx=0.40), then helical044 (dx=0.15) topped it at obj=2.504.
  Followup batch (049/050) at dx≈0.1-0.17 also entered top-4.
- **dx bounds widened again to 0.01** in `autoresearch_bo_michael.py:374`
  and `gp_predict_helical.py` BOUNDS (since helical050 sits at the previous
  lower bound 0.105 ≈ 0.1).
- **GP fix**: `gp_predict_helical.py:make_gp` `length_scale_bounds` floor
  raised from sklearn default 1e-5 to **1e-1** to prevent the dx dimension
  from collapsing to noise-only (was producing a vertical-line cloud in the
  Pareto overlay plot). 67-point Pareto frontier (was 25) after refit.

## Mechanical buildability concern (2026-05-18)
Optimizer keeps pushing dx toward 0 (thinner ribbon = less mass to disturb CE
arm, while still casting calo-stops downstream). The geometric optimum
(dx=0.5 → 1 mm ribbon, 290 mm long, 109 mm tall, 333° twist) is at or beyond
the limit of self-supporting Al shim stock and would require a structural
support frame in practice.
- Mu2e Offline already has `tsda.tubes.*` infrastructure for concentric Al
  absorber tubes (verified in mmackenz workflows: `grep -E "^bool\s+tsda\.tubes\.build\s*=\s*true"`
  across all configs returns zero matches — never activated).
- mmackenz "offset plug" class (v48, v55-v61) places solid Al disks at z
  offsets, not tube housings around ribbons.
- **Novel design candidate for Phase 2**: tube-housing-around-ribbon — use
  thin Al tube as the structural element with a twisted ribbon suspended
  inside. Combines proven `tsda.tubes` machinery with helical plug ribbon.
  Not in mmackenz's prior search vocabulary.

**Two-script overlay pattern** (sklearn + ROOT envs are incompatible):
- `gp_predict_helical.py` runs in `/usr/bin/python3` (has sklearn/scipy,
  no ROOT). Fits GPs, samples Sobol, computes Pareto mask, writes
  `gp_predictions_helical.tsv` + `gp_observed_helical.tsv`.
- `overlay_gp_predictions_helical.py` runs in the muse SimJob env
  (`muse setup SimJob` → ROOT 6.32.06, no sklearn). Reads the TSVs,
  overlays on mmackenz's `plot_table_configs` background scatter,
  emits `gp_predicted_helical_cloud.png`.
- Lives in `/exp/mu2e/data/users/oksuzian/autoresearch_grid/mmackenz_table_plots/`.

## Chain-script evaluate bug (recurrent, 2026-05-18)
`/tmp/helical_full.sh:59-60` has a line-continuation in the `run evaluate`
call that mangles argument splitting → `evaluate` exits rc=2 with
CHAIN_FAIL. **summary.json has already been written by harvest by the time
evaluate runs**, so manual recovery is one-line:
`./autoresearch_bo_michael.py --mode helical evaluate <cfg> <DATA>/<cfg>/harvest/summary.json`
Hit by helical043, helical045, helical046 in succession (all three dx-probe
configs that completed). Fix the chain-script line continuation when
touching it next.

## Open questions / TODO
- helical001 (`dx=2.32, dy=84, halflen=263, z0=4500, angle=452`) PASSED
  preflight with the v111-style baseline. Submit to grid; target obj > 1.958.
- The v111-baseline render emits the same TT_MidInner patches as v111. If
  task #21 someday switches the project to a stage-aware baseline (one geom
  per stage), revisit whether this manual patch can be dropped.
- michael-mode load_priors does NOT exclude helical configs — v111 enters the
  michael GP as if its low calo (1.62e-6) came from foil stack alone, when
  actually the helical plug is doing most of the rejection. This contaminates
  the michael GP signal at low-calo region. Consider filtering helical priors
  out of michael mode (separate concern from this project).
