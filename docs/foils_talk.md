---
marp: true
theme: default
paginate: true
size: 16:9
header: "FoilsMode — 5D BO on the Mu2e Stopping-Target Foil Stack"
footer: "Y. Oksuzian · 2026-05-29"
style: |
  section { font-size: 24px; }
  h1 { color: #003366; }
  h2 { color: #003366; border-bottom: 2px solid #003366; padding-bottom: 4px; }
  table { font-size: 18px; }
  code { font-size: 18px; }
  pre { font-size: 16px; }
---

# FoilsMode
## 5D Bayesian Optimization of the Mu2e Stopping-Target Foil Stack

**Y. Oksuzian**
2026-05-29
Mu2e — autoresearch / closed-loop BO

---

## Motivation: why a new BO line?

- 4D helical-plug BO has **saturated**:
  - HV +1.6 % over last 76 evals
  - Hit-rate decayed 62 % → 38 %
- More 4D evals will not buy us much.
- **The next win comes from a dimensionality lift**, not from running the same loop longer.
- Open a parallel BO line over the **stopping-target foil stack** — orthogonal to the helical plug.

---

## The physical knob

**Base 37-foil stack (deployed v02):**
- `rOut = 75 mm`, `halfThickness = 0.0528 mm` (≈ 105.6 µm full)
- `holeRadius = 21.5 mm`, 37 foils, fixed spacing
- **Pinned** — not optimized.

**The +12 envelope (optimized):**
- ≤ 6 extra foils **upstream**
- ≤ 6 extra foils **downstream**
- All extras share **one** (rOut, halfThickness, rIn) triple

**Helical plug OFF** (`hasTSdA = false`, `tsda.helical.build = false`)
→ keeps result orthogonal to bo-helical.

---

## 5D search space

| Knob                  | Type    | Range          |
|-----------------------|---------|----------------|
| `n_up`                | Integer | 0 – 6          |
| `n_down`              | Integer | 0 – 6          |
| `extra_rOut`          | Real    | 50 – 250 mm    |
| `extra_halfThickness` | Real    | 0.05 – 1.0 mm  |
| `extra_rIn`           | Real    | 0 – 50 mm      |

**Gotcha:** `stoppingTarget.holeRadius` is a single scalar at
`StoppingTargetMaker.cc:41` — `extra_rIn` is necessarily a **global**
override when extras are present.
**`is_buildable`** rejects `rIn ≥ BASE_ROUT_MM` (vanishing base annulus).

---

## Objective + pipeline

**Scalarized objective:** `obj = S/√B − α · calo / POT`  (α = 1 × 10⁵)

**Pipeline (per child, 4 grid stages):**

```
propose → preflight (G4 surface check)
       → mubeam → run1b_mubeam → concat → mustops_ce
       → harvest → scan_logs → leaderboard
```

- LangGraph state machine, SqliteSaver checkpointed.
- Outer **closed-loop runner**: q parallel children per round, GP refit between rounds.
- Stop criteria: `--max-rounds`, Pareto-hash convergence, or operator `STOP_CLOSED_LOOP`.

---

## Phase 0: preflight passes the extreme corners

Three extreme-corner configs hand-built and run through G4 surface-check **before any grid submit**:

| name         | n_up | n_down | rOut | hT  | rIn | radii len | Result |
|--------------|------|--------|------|-----|-----|-----------|--------|
| `foilsP0_AU` | 6    | 0      | 250  | 1.0 | 50  | 43        | **PASS** |
| `foilsP0_AD` | 0    | 6      | 250  | 1.0 | 50  | 43        | **PASS** |
| `foilsP0_AS` | 6    | 6      | 250  | 1.0 | 50  | 49        | **PASS** |

All three: `total_hits = 1, baseline = 1, managed = 0` — no `StoppingTargetFoil_*` overlap.

**Full 5D box is buildable** — no defensive clamp needed on the search space.

---

## Bootstrap: no priors, Sobol seed

- **No mmackenz priors** apply: mmackenz v22–v50 are 7D over different knobs (rIn / halfLength4 / holeRadius / col5) — don't project onto this 5D extras-only space.
- Closed-loop GP picker builds its **own** Optimizer with `n_initial_points = q` on round 0 (otherwise skopt: *"Random evaluations exhausted and no model has been fit"*).
- **Parallel strategy:** `cl_min` (collapse-resistant for mixed Integer + Real dims; skopt `cl_mean` warns about fake-y collapse here).

---

## Closed-loop wiring (mode-generic)

Single-line plumbing — FoilsMode rode on the same infrastructure as helical:

- `graph/state.py:32` — `Literal["helical", "michael", "foils"]`
- `graph/closed_loop.py` — `_import_gp(mode)` dispatches to `gp_predict_<mode>`
- `graph/pipeline_io.py` — `mock_metrics` widened to 5D
- New `gp_predict_foils.py` shim (~50 LOC)

**One side-fix:** `HelicalMode.FOIL_COUNT = 38 → 37` to match deployed v02 base.

---

## Run timeline

| Run     | q  | Rounds | Evals | Status                                |
|---------|----|--------|-------|---------------------------------------|
| X01     | 10 | 1      | 10    | Sobol bootstrap, all PASS preflight   |
| X02     | 10 | 3      | 30    | clean, frontier still moving          |
| X03     | 10 | 5      | 50    | 5 distinct Pareto-hashes, non-converged |
| **X04** | 10 | 10     | 100   | **in progress** (push past non-convergence) |

**End of X04:** ~190 evals total budget.

---

## GP cloud evolution (animated)

![w:900](gp_predicted_foils_cloud.gif)

**Frontier widened across X01 → X03:**
- sob peak: **3.31 → 3.87** (+17 %)
- calo floor: **5.6 × 10⁻⁶ → 8.3 × 10⁻⁷** (6.7× drop)
- Pareto count oscillates 80 – 106 between cohorts.

---

## Top configurations so far

| config             | n_up | n_down | rOut  | hT    | rIn  | sob  | calo (×10⁻⁵) | obj  |
|--------------------|------|--------|-------|-------|------|------|---------------|------|
| `foilsX03R04_02`   | 5    | 6      | 184.4 | 0.121 | 0.0  | 3.43 | 1.29          | **2.14** |
| `foilsX03R03_03`   | 5    | 6      | 203.4 | 0.080 | 0.0  | 3.51 | 1.42          | 2.09 |
| `foilsX03R04_00`   | 5    | 6      | 174.1 | 0.125 | 0.0  | 3.47 | 1.40          | 2.07 |
| `foilsX03R02_06`   | 5    | 6      | 225.4 | 0.080 | 0.0  | 3.41 | 1.45          | 1.96 |
| `foilsX03R02_03`   | 6    | 6      | 198.5 | 0.050 | 0.0  | 3.63 | 1.73          | 1.90 |

**Pattern (top-5):** **max-extras** dominates — `n_up ∈ {5,6}, n_down = 6, rIn = 0`.
Optimum sits in the **thin-foils / large-radius** regime.

---

## What the GP has learned

**Length-scale rails diagnostic (sklearn ConvergenceWarning):**

| dim                       | n=10  | n=29  | n=47        |
|---------------------------|-------|-------|-------------|
| `n_up`                    | OK    | OK    | OK          |
| `n_down`                  | rails | freed | freed       |
| `extra_rOut`              | OK    | OK    | OK          |
| `extra_halfThickness`     | OK    | OK    | OK          |
| `extra_rIn`               | rails | rails | **rails**   |

**Take-away:** `extra_rIn` remains the worst-trained dim
→ next batch should **explicitly probe rIn** instead of trusting the GP's marginal there.

---

## Bugs hit + fixes (framework hardening)

1. **`numpy.int64` msgpack crash** — skopt `Integer` dims returned `np.int64`; LangGraph SqliteSaver checkpoint died at round transition.
   *Fix:* cast Integer picks to native `int` in `gp_predict_foils.compute_explore_picks`.

2. **Barrier false-positive on round ≥ 1** (helical-side; inherited to foils) — empty `StateSnapshot` indistinguishable from terminal.
   *Fix:* require `snap.next` empty **AND** `snap.values` non-empty **AND** `metadata.step ≥ 1`.

3. **Concat convergence-poll never-converges** — `pipeline.py:470` counted only **bare-form** (`00000`) outstage dirs as "settled"; hash-suffix dirs from failed art jobs spun the poll forever.
   *Fix:* failure-aware exit when `in_queue == 0` AND all `njobs` dirs present in either form.

---

## Lesson: convergence-by-hash is the wrong stop criterion early

Across **X03** (5 rounds, 50 evals):

- Pareto-hashes: `a8f16932 → ddf0adc1 → b30ac643 → 62608fc9 → 6459d20d`
- **All 5 distinct** → no convergence by `k = 2` repeat criterion.
- But frontier still **measurably expanded** (sob 3.52 → 3.87, calo 1e-6 → 8.3e-7).

**The hash flips on every new Pareto-dominating point** — by design, but useless as a stop criterion in early phase.

**Use instead:** HV-delta (hyper-volume increment) or absolute eval-budget cap.

---

## Open questions / next steps

- **foilsX04** running now (100 evals, q = 10 × 10 rounds) — push past X03 non-convergence.
- If rIn still rails after X04: **hand-seed** small-rIn / large-rIn probes.
- Re-render **GP cloud at n ≥ 60** — current dim-4 length-scale rail invalidates extrapolation.
- Consider promoting a **6th dimension** (e.g. base hole radius decoupled from extras) if 5D plateaus.
- **Cross-compare X04 final frontier** with helical Pareto envelope — is the foil DOF additive or partially redundant?

---

## Backup: references

**Wiki pages**
- [bo-foils](../../app/users/oksuzian/autoresearch/wiki/projects/bo-foils.md)
- [closed-loop-runner](../../app/users/oksuzian/autoresearch/wiki/drivers/closed-loop-runner.md)
- [stopping-target-foil-base-spec](../../app/users/oksuzian/autoresearch/wiki/concepts/stopping-target-foil-base-spec.md)

**Source files**
- `autoresearch_bo_michael.py` — `FoilsMode` class (~L547)
- `graph/closed_loop.py` — multi-round Pareto-pick driver
- `gp_predict_foils.py` — skopt EI picker shim
- `gp_predict_foils_cloud_anim.py` — per-cohort GIF renderer

**Leaderboard**
`/exp/mu2e/app/users/oksuzian/autoresearch/leaderboard_bo_foils_v1.tsv`
