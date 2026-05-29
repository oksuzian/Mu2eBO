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
| **X04** | 10 | 10     | 100   | **in progress**                       |

**End of X04:** ~190 evals total budget.

---

## GP cloud evolution (animated)

![h:500](gp_predicted_foils_cloud.gif)

**Frontier widened across X01 → X03:**
- sob peak: **3.31 → 3.87** (+17 %)
- calo floor: **5.6 × 10⁻⁶ → 8.3 × 10⁻⁷** (6.7× drop)

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

## Open questions / next steps

- **foilsX04** running now (100 evals, q = 10 × 10 rounds).
- If `extra_rIn` remains under-trained after X04: **hand-seed** small-rIn /
  large-rIn probes.
- Consider promoting a **6th dimension** (e.g. base hole radius decoupled
  from extras) if 5D plateaus.
