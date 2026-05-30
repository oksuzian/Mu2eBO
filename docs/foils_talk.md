---
marp: true
theme: default
paginate: true
size: 16:9
footer: "FoilsMode — 5D BO on the Mu2e Stopping-Target Foil Stack · Y. Oksuzian · 2026-05-29 (X05 mid-run)"
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

- LangGraph state machine, q parallel children per round.
- GP refit between rounds (skopt EI, `cl_min` parallel strategy).
- Stop criteria: `--max-rounds`, Pareto-hash convergence, or operator
  `STOP_CLOSED_LOOP`.

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

| Run     | q  | Rounds | Evals | Status                                |
|---------|----|--------|-------|---------------------------------------|
| X01     | 10 | 1      | 10    | Sobol bootstrap, all PASS preflight   |
| X02     | 10 | 3      | 30    | clean, frontier still moving          |
| X03     | 10 | 5      | 50    | frontier widening, non-converged      |
| X04     | 10 | 10     | 0     | **silent fail** (all preflight rc=3)  |
| **X05** | 10 | 3      | 9+    | **in progress** (R0 done, R1 on grid) |

**Leaderboard now: 82 evals** (X04 wiped — see ambiguous-preflight incident).

---

## GP cloud evolution (animated)

<div style="display: grid; grid-template-columns: 60% 40%; gap: 20px; align-items: center;">
<div>

![w:100%](gp_predicted_foils_cloud.gif)

</div>
<div>

**Frontier widened across X01 → X03:**

- sob peak: **3.31 → 3.87** (+17 %)
- calo floor: **5.6 × 10⁻⁶ → 8.3 × 10⁻⁷** (6.7× drop)

</div>
</div>

---

## GP cloud (static snapshot)

<div style="display: grid; grid-template-columns: 60% 40%; gap: 20px; align-items: center;">
<div>

![w:100%](gp_predicted_foils_cloud.png)

</div>
<div>

**Latest frame**, x-axis extended to **Relative S/√B = 1.4** so the
GP-predicted Pareto frontier no longer rails the right edge. Pinned 37-foil
base sits near `x = 1.0`; +12 envelope picks land in the 1.05 – 1.35 band.
Calo-floor unchanged: best-known config sits at ~1.3 × 10⁻⁶.

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

- Anchor (R1) = **0.096**
- Δbest **+0.058 → +0.161** thru R04
- Hit-rate **55→50 %** (healthy)
- **not saturated** — keep going

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

## Top configurations so far

| config             | n_up | n_down | rOut  | hT    | rIn  | sob  | calo (×10⁻⁵) | obj  |
|--------------------|------|--------|-------|-------|------|------|---------------|------|
| `foilsX03R04_02`   | 5    | 6      | 184.4 | 0.121 | 0.0  | 3.43 | 1.29          | **2.14** |
| `foilsX05R00_09`   | 5    | 6      | 186.3 | 0.146 | 7.8  | 3.28 | 1.19          | 2.09 |
| `foilsX05R00_08`   | 4    | 6      | 189.4 | 0.150 | 8.6  | 3.29 | 1.20          | 2.09 |
| `foilsX03R03_03`   | 5    | 6      | 203.4 | 0.080 | 0.0  | 3.51 | 1.42          | 2.09 |
| `foilsX05R00_06`   | 5    | 6      | 184.1 | 0.149 | 7.9  | 3.27 | 1.18          | 2.09 |

**Pattern (top-5):** **max-extras** still dominates — `n_up ∈ {4,5}, n_down = 6`,
`rOut ≈ 180-200 mm`, `hT ≈ 0.08-0.15 mm`. X05 R0 placed 3 fresh entries
clustering tightly around the X03 champion, now probing **non-zero rIn (~8 mm)**
— frontier tightening, not shifting.

---

## Open questions / next steps

- **foilsX05** in flight (q=10 × 3 rounds; R0 harvested, R1 on grid).
- X04 silent total-fail (20/20 children at `preflight=ambiguous rc=3`) —
  convergence check needs a "new evals this round" gate. Tracked.
- `extra_rIn` length-scale still rails to upper bound at n=82 — next:
  **hand-seed** small-rIn / large-rIn probes if X05 doesn't sharpen it.
- Consider promoting a **6th dimension** (base hole radius decoupled
  from extras) if 5D plateaus.
