---
marp: true
theme: default
paginate: true
size: 16:9
footer: "FoilsMode — Mu2e Stopping-Target Foil-Stack BO (5D → 6D) · Y. Oksuzian · 2026-06-02"
style: |
  section { font-size: 24px; }
  h1 { color: #003366; }
  h2 { color: #003366; border-bottom: 2px solid #003366; padding-bottom: 4px; }
  table { font-size: 18px; }
  code { font-size: 18px; }
  pre { font-size: 16px; }
---

# FoilsMode
## 5D → 6D Bayesian Optimization of the Mu2e Stopping-Target Foil Stack

**Y. Oksuzian**
2026-06-02
Mu2e — autoresearch / closed-loop BO

---

## Motivation

- Does modifying the **stopping-target foil stack** buy CE efficiency?
- Open a BO line over **extra foils added upstream / downstream** of the
  current deployed stack.
- Keep the deployed 37-foil base **pinned** — any movement in (sob, calo)
  is attributable to the +12 envelope.

---

## The physical knob

**Base 37-foil stack (deployed v02, pinned):**
- `rOut = 75 mm`, `halfThickness = 0.0528 mm` (≈ 105.6 µm full)
- `holeRadius = 21.5 mm`, 37 foils, fixed spacing

**The +12 envelope (optimized):**
- ≤ 6 extra foils **upstream**
- ≤ 6 extra foils **downstream**
- All extras share **one** (rOut, halfThickness, rIn) triple

---

## 5D search space

| Knob                  | Type    | Range          |
|-----------------------|---------|----------------|
| `n_up`                | Integer | 0 – 6          |
| `n_down`              | Integer | 0 – 6          |
| `extra_rOut`          | Real    | 50 – 250 mm    |
| `extra_halfThickness` | Real    | 0.05 – 1.0 mm  |
| `extra_rIn`           | Real    | 0 – 50 mm      |

**Objective:** `obj = S/√B − α · calo / POT`  (α = 1 × 10⁵)

---

## Pipeline

```
propose → preflight (G4 surface check)
       → mubeam → run1b_mubeam → concat → mustops_ce
       → harvest → scan_logs → leaderboard
```

- LangGraph state machine; **q** (batch size) children per round.
- **Gaussian Process (GP)** surrogate refit between rounds.
- **Expected Improvement (EI)** acquisition: exploit (mean) vs explore (σ).
- **Constant Liar — Min (`cl_min`)** for batch: feed in-flight picks
  the worst observed `obj`, refit GP, re-pick. Spreads the batch; cheaper than qEI.
- **Stop:** `--max-rounds`.

---

## Batch BO: qEI — the "proper" multi-point EI

**Plain EI (`q=1`):** pick the single point that maximizes expected
improvement over the current best `obj`.

**qEI (`q>1`):** pick `q` points **jointly** so the **best of the q** is
expected to improve the most. The question changes from
*"what's the best next point?"* to *"what's the best batch of `q` points
to try in parallel?"*

**The math:** integrate over the GP's **joint posterior** at all `q`
candidate locations at once. Points that are correlated (close together)
contribute redundantly to the integral, so the optimizer **naturally
spreads** them. No lies needed — the math handles it.

---

## Why we don't use qEI: cost

**The joint integral has no closed form for `q > 1`:**

- Monte Carlo over **thousands** of GP samples per candidate batch.
- Acquisition optimizer searches over `q × d` dimensions
  (here 5D × q=10 = **50D**) instead of just `d` (5D).
- Each acquisition evaluation costs **~100–1000×** a single-point EI eval.

**Constant Liar is the cheap proxy:**
sequentially pick `q` points, lying about the in-flight ones. You get most
of the spreading benefit at the cost of `q` single-point EI optimizations
— **linear in `q`** instead of exponential.

That's why we run `cl_min`, not qEI. BoTorch supports real
qEI / qNEHVI (Monte Carlo); benchmarked on a sibling problem — skopt's
`cl_min` was good enough at this scale.

---

## Phase 0: preflight passes the extreme corners

Three extreme-corner configs hand-built and run through G4 surface-check **before any grid submit**:

| name         | n_up | n_down | rOut | hT  | rIn | radii len | Result |
|--------------|------|--------|------|-----|-----|-----------|--------|
| `foilsP0_AU` | 6    | 0      | 250  | 1.0 | 50  | 43        | **PASS** |
| `foilsP0_AD` | 0    | 6      | 250  | 1.0 | 50  | 43        | **PASS** |
| `foilsP0_AS` | 6    | 6      | 250  | 1.0 | 50  | 49        | **PASS** |

All three: `total_hits = 1, baseline = 1, managed = 0` — no overlap.

**Full 5D box is buildable** — no defensive clamp needed.

---

## Run timeline

| Run     | q  | Rounds | Evals | Status                                  |
|---------|----|--------|-------|-----------------------------------------|
| X01     | 10 | 1      | 10    | Sobol bootstrap, all PASS preflight     |
| X02     | 10 | 3      | 30    | clean, frontier still moving            |
| X03     | 10 | 5      | 50    | frontier widening                       |
| X04     | 10 | 10     | 0     | **silent fail** (all preflight rc=3)    |
| X05     | 10 | 3      | 30    | clean, frontier tightening              |
| X06     | 10 | 3      | 28    | 2 children lost to name-fork bug (#172) |
| X07     | 10 | 10     | 83    | **champion R01_03 obj=2.178**; SAT R02+ (17 zero-row sidecars) |
| **X08*** | 10 | 5     | 8 / 50 | **qNEHVI picker (BoTorch)** — R00 done best obj=1.79; in-flight |

<!-- run-timeline:start -->
**Leaderboard now: 251 evals** (X01=10, X02=29, X03=34, X05=25, X06=22, X07=83, X08=47; X04 wiped — see ambiguous-preflight incident).
<!-- run-timeline:end -->
*X08 = first qNEHVI production run (`--picker qnehvi`, [[batch-bo]]); contrasts the LOCO finding that CL-min wins 4/5.*

---

## GP cloud evolution (animated)

<div style="display: grid; grid-template-columns: 60% 40%; gap: 20px; align-items: center;">
<div>

![w:100%](gp_predicted_foils_cloud.gif)

</div>
<div>

**Frontier widened across X01 → X07:**

- sob peak: **3.31 → 3.62** (+9 %)
- calo floor: **5.6 × 10⁻⁶ → 1.6 × 10⁻⁶** (3.5× drop)
- Plateau in last 5 rounds — see saturation slide.

</div>
</div>

---

## GP cloud (static snapshot)

<div style="display: grid; grid-template-columns: 60% 40%; gap: 20px; align-items: center;">
<div>

![w:100%](gp_predicted_foils_cloud.png)

</div>
<div>

<!-- highlights:start -->
- **251 evals**, frontier saturated
- Best **obj = 2.18** (sob 3.60, calo 1.42 × 10⁻⁵); calo floor **8.9e-07**
- Winning region: `n_down = 6`, `rOut ≈ 164 mm`, thin `hT`
<!-- highlights:end -->

</div>
</div>

---

## BoTorch cross-check (same data, different surrogate)

<div style="display: grid; grid-template-columns: 60% 40%; gap: 20px; align-items: center;">
<div>

![w:100%](botorch_predicted_foils_cloud.png)

</div>
<div>

<!-- botorch-cross-check:start -->
- BoTorch `SingleTaskGP` re-fit on the same **n=251** rows
- Observed extrema: **sob_max 3.93**; **calo_min 8.95e-07**
- Cross-model agreement → foils saturation is **model-independent** (same conclusion as helical)
<!-- botorch-cross-check:end -->

</div>
</div>

---

## Picker diversity: BoTorch qNEHVI vs skopt CL-min (q=10, n=164)

<div style="display: grid; grid-template-columns: 60% 40%; gap: 20px; align-items: center;">
<div>

![w:100%](diversity_overlay_foils.png)

</div>
<div>

- Intra-batch spread (normalized 5D L2): **BoTorch 0.83**, **CL-min 0.10**
- Predicted Pareto dominance: **CL-min 10/10**, BoTorch 0/10
- **Reversal vs n=128** (was BoTorch 10/10): champion ridge sharpened → CL-min collapses *onto* it; qNEHVI scatters into worse corners
- Operational: keep **both pickers in rotation**, don't crown one

</div>
</div>

---

## Saturation diagnostic (post-hoc FoM)

<div style="display: grid; grid-template-columns: 62% 38%; gap: 12px; align-items: center; font-size: 18px;">
<div>

![w:100%](saturation_bo_foils_v1_slim.png)

</div>
<div>

**Δbest = max(obj_round) − max(obj_all_prior)**
SAT when Δbest ≤ ε·R1-gain for last *k*=2 rounds (ε=0.05).

- Anchor (R1) = **+0.088**, champion obj = **2.178** at X07R01_03
- Δbest **negative for 8 consecutive rounds** (R02–R09)
- Hit-rate first 20 / last 20: **55 % → 65 %** — rebounded after X08 R00 (qNEHVI) scattered into fresh corners; **HV grew but obj-best ceiling did not move** → diversity indicator, not a saturation indicator
- **VERDICT: SATURATED** (per-round Δbest plateau is the load-bearing signal) — next is a dimensionality lift, not more rounds

</div>
</div>

---

## Frontier progress: HV + Pareto-front size

<div style="display: grid; grid-template-columns: 50% 50%; gap: 12px; align-items: center; font-size: 17px;">
<div>

![w:100%](saturation_bo_foils_v1_hv.png)

**Dominated hypervolume (sob, −calo)** — area swept by the
Pareto frontier vs ref point. Monotone non-decreasing; a flattening
curve is the strongest single-number "we have converged" signal.

</div>
<div>

![w:100%](saturation_bo_foils_v1_pf.png)

**Pareto-front size** — number of non-dominated points. Can DROP
(new evals dominate old frontier members) → the GP is *moving*,
not just *extending* the frontier. Healthy churn ≠ saturation.

</div>
</div>

Both panels: x = evaluation index in leaderboard (harvest order).

---

## Obj champion geometry — foilsX07R01_03

![w:78%](foil_champion_foilsX07R01_03_sketch.png)

- **n_up=6 / n_down=6** max-extras; rOut≈160, hT≈0.116, hole rIn≈6.5 mm
- Joint sob+calo optimum (obj = 2.178); pitch ΔZ=22.22 mm from base

---

## Sob-only champion geometry — foilsX08R04_08

![w:78%](foil_champion_foilsX08R04_08_sketch.png)

- Same max-extras corner; **smaller rOut≈124, thinner hT≈0.073, rIn≈1.3 mm**
- Pure S/√B ridge: sob=3.93, but calo ~38% higher → obj=1.97

---

## Top configurations so far

| config             | n_up | n_down | rOut  | hT    | rIn  | sob  | calo (×10⁻⁵) | obj  |
|--------------------|------|--------|-------|-------|------|------|---------------|------|
| `foilsX07R01_03`   | 6    | 6      | 159.9 | 0.116 | 6.5  | 3.60 | 1.42          | **2.178** |
| `foilsX07R01_08`   | 5    | 5      | 150.7 | 0.132 | 6.9  | 3.62 | 1.48          | 2.145 |
| `foilsX03R04_02`   | 5    | 6      | 184.4 | 0.121 | 0.0  | 3.43 | 1.29          | 2.144 |
| `foilsX07R01_01`   | 6    | 6      | 157.2 | 0.116 | 7.3  | 3.60 | 1.47          | 2.128 |
| `foilsX05R01_03`   | 6    | 6      | 165.6 | 0.151 | 0.0  | 3.36 | 1.26          | 2.104 |

**Pattern (top-5):** **max-extras** dominates — `n_up ∈ {5,6}, n_down ∈ {5,6}`,
`rOut ≈ 150-185 mm`, `hT ≈ 0.12-0.15 mm`, `rIn ≈ 0-7 mm`. The X07R01 batch
placed **3 of the top-5** in a tight cluster around (n_up=6, n_down=6, rOut≈160) —
champion ridge sharpened, then 5 rounds of failed exceedence attempts.

---

## Open questions / next steps

- **5D space saturated** at n=212 (R02–R09 all negative Δbest, 8
  consecutive rounds below ε·anchor). Champion **foilsX07R01_03 obj = 2.178**.
- LOCO honest-judge eval (last 5 cohorts, held-out judge GP): **CL-min
  wins 4/5**, Δ(BO−CL) mean = **−0.53**. → keep CL-min as production
  picker; the prior "switch to BoTorch" claim was self-referee bias.
- **Next move is a dimensionality lift, not more rounds:** promote
  base hole-radius and/or base halfThickness to BO knobs (6th/7th
  dim), or open a parallel BO line on stack-spacing.
- Process fixes landed during X04→X07: ambiguous-preflight retry
  (#162), per-launch unique thread_id (#165), zero-row classifier
  + sidecar (#167), `node_propose` re-entry name preservation (#172),
  `sourced_env` stderr leak fix (#170).

---

## v2 — the dimensionality lift (foilsY)

The 5D frontier **saturated** at obj = 2.178 — so the next move is *more
dimensions, not more rounds*. **foilsY** is that lift:

**5D → 6D, per-side decoupled.** v1 forced all extras to share one
`(rOut, hT, rIn)` triple. v2 gives **upstream and downstream their own**:
`(rOut, hT, rIn) × (up / dn)`.

- `n_up = n_down = 6` **pinned** — both v1 champions railed there.
- Base 37 still pinned; a new per-foil **`holeRadii` vector** decouples the
  extras' hole from the fixed base hole = 21.5 mm (patched `StoppingTargetMaker`).
- Warm start: the v2 leaderboard + the **1 base-hole-valid v1 prior** — the
  other 50 v1 rows measured a base geometry v2 can't reproduce, so they're dropped.

→ **First question:** does decoupling up / dn buy anything the diagonal can't reach?

---

## foilsY: first 6D cloud

<div style="display: grid; grid-template-columns: 60% 40%; gap: 20px; align-items: center;">
<div>

![w:100%](gp_predicted_foilsY_cloud.png)

</div>
<div>

**Early v2 read** (n = 18: 1 valid v1 prior + 17 foilsY):

- Best **obj = 2.00** (sob 3.62) at a genuinely **asymmetric** pick
  (up ≠ dn) — beats every near-diagonal v1-style config so far
- `rIn` dims still under-trained → read as interpolation, not extrapolation
- **foilsY03 in flight** (q=3 × 5 rounds) — more rounds landing

</div>
</div>
