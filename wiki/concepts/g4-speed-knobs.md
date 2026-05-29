# Geant4 speed knobs (local bench, 2026-05-22)

**Type:** concept
**Status:** active
**Updated:** 2026-05-24 (FTFP_BERT default extended-validation: FT02 + FT03 + FT04 all landed 24/24 leaderboard rows with zero scan_logs gating; GP Pareto frontier densified 13 → 33 → 626 across the three q=8 batches)

## Promoted to default in all G4-bearing templates (2026-05-23)

After the mubeam-only A/B (graph027 vs helicalQR00_02) showed −20% CPU
with sob/calo deltas inside the ShieldingM-self noise floor on the same
x_point (see helicalQR00_02_noise re-run below), the FCL override
`physics.producers.g4run.physics.physicsListName: "FTFP_BERT"` was added
to all 3 G4-bearing templates:

- `pipeline_templates/mubeam/template.fcl`
- `pipeline_templates/run1b_mubeam/template.fcl`
- `pipeline_templates/mustops_ce/template.fcl`

(`concat` has no G4, skipped.) **Caveat: only the mubeam stage has grid
A/B evidence.** `run1b_mubeam` and `mustops_ce` were flipped on the
assumption that the CPU/noise tradeoff is similar; the latter is the
sob-numerator stage, so first-round monitoring is needed. Validation
batch: closed-loop `helicalFT01R00_*` (q=8, max-rounds=1, calo<2e-6
predicted region, launched 2026-05-23 12:22 thread
`closed-FT01-20260523_122205`). Compare per-stage CPU + sob/calo
against the QR00_02/SR02 history to confirm extrapolation holds before
treating this as the new baseline.

## Grid A/B validation (2026-05-23) — FTFP_BERT vs ShieldingM on full mubeam stage

**Configs:** `graph027` (FTFP_BERT) re-runs the same x_point as baseline
`helicalQR00_02` (ShieldingM): dx=0.134, dy=117.19, halflen=351.24, angle=361.
200 jobs each, identical events_per_job/seeds otherwise. Worker logs at
`/pnfs/mu2e/scratch/users/oksuzian/workflow/default/outstage/{70172746,28239926}/`.

**Scoping (load-bearing):** FTFP_BERT was applied to the `mubeam` stage
ONLY — the FCL edit was a single line in
`pipeline_templates/mubeam/template.fcl`. `run1b_mubeam`, `concat`, and
`mustops_ce` ran ShieldingM in both arms. Wall/CPU/Vm numbers below are
mubeam-stage only (extracted from worker logs); sob and calo are
end-of-chain (after 4 stages, of which only one differed).

| Metric | helicalQR00_02 (ShieldingM) | graph027 (FTFP_BERT) | Δ |
|---|---:|---:|---:|
| CPU mean [s] (n=182/196 successful-only) | 199.6 | 178.5 | **−10.6%** |
| Real mean [s] (n=182/196 successful-only) | 205.8 | 189.3 | **−8.0%** |
| CPU mean [s] (n=200/200 all TimeReport) | 228.3 | 182.8 | **−20.0%** |
| Real mean [s] (n=200/200 all TimeReport) | 235.4 | 193.8 | **−17.7%** |
| VmPeak [MB] | 2664 | 1474 | **−45%** |
| VmHWM [MB] | 2337 | 1149 | −51% |
| sob | 3.70 | 3.77 | +1.9% |
| calo/POT | 1.058e-5 | 1.139e-5 | +7.6% |
| scalarized obj (α=1e5) | 2.642 | 2.631 | −0.4% (flat) |

**Selection bias warning on the CPU mean:** The n=182/196 row counts only
jobs whose `.art` made it to /pnfs (post-stage-out success); these jobs
exclude the slow-tail workers that died during PostEndJob (xrootd
FileOpenError per [[concat-xrootd-fileopen-postendjob]]). The slow-tail
jobs ARE in worker logs (they reach TimeReport before stage-out). Filtering
on /pnfs success preferentially drops slow-tail jobs — and that filter
removed 18 jobs from Shield but only 4 from FTFP, biasing the Shield mean
DOWN more than the FTFP mean. The unbiased n=200/200 comparison (every
worker that emitted TimeReport) puts FTFP wall savings at **−20% CPU /
−17.7% Real**, not the −10.6% I first reported. The wall criterion in
the original plan ("≈ −40 to −50%") still failed, but by less than the
n=182 number suggested.

**Key finding: the local-bench −48% wall did NOT replicate on the grid
(only −8%).** Local bench at 300 events on `helical011` geom predicted
~2× speedup; grid sees ~1.1×.

**Root cause (root-caused 2026-05-23 by pulling per-event timings from
worker logs):** the discrepancy is NOT I/O dilution — it's that the
local bench and the grid A/B measured **different geometries**, and
per-event G4 work is wildly geometry-dependent:

| | per-event wall | geometry |
|---|---:|---|
| local bench (`helical011`) | 266 ms/ev (Shield) → 138 ms/ev (FTFP) = **−48%** | dx=3.12, halflen=55.5, angle=4331 (v1-era) |
| grid (`helicalQR00_02`) | ~40 ms/ev (Shield) → ~36 ms/ev (FTFP) = **−11%** | dx=0.13, halflen=351, angle=361 |

helicalQR00_02's per-event G4 wall is **6.6× lower than helical011's** —
absorber/scattering load is dramatically different across geometries.
FTFP_BERT's savings come from cheaper hadronic models; in a regime where
hadronic cascades are already a small fraction of total G4 work (efficient
absorber, less secondary production), there's less for it to save.

Init times are NOT the differentiator (grid worker logs show 35s FTFP vs
37s Shield — only 2s gap, fully amortized over 5000-event production
runs).

**Operational rule: physics-list speedups are geometry-dependent. A
single-x_point local bench cannot be extrapolated to other geometries.
Always cross-check local-bench speedups against a full grid A/B before
flipping a default;
local bench overestimates by ~5× on this stage, not because of stage
overhead but because of geometry-specific G4 sensitivity.**

**The memory drop is the headline win, not wall.** −45% VmPeak (2.66
→ 1.47 GB) is a substantial OOM-safety margin — production mubeam
flirts with 2.5 GB limits routinely. Memory drop is consistent across
all sampled workers (FTFP_BERT VmPeak clustered at 1473-1524 MB; ShieldingM
clustered at 2663-2667 MB). Mechanism inference: FTFP_BERT's hadronic
table set is much smaller than ShieldingM's, which carries
multi-physics-model coverage (HP-style data files, neutron data, etc.).

**Decision-rule outcome:** plan required wall ≈ −40 to −50% AND sob/calo
within noise to flip default. Wall criterion FAILED (−8% vs target
−40-50%); sob/calo are within noise (sob +1.9%, scalarized obj flat).
Template was reverted to ShieldingM after the A/B chain materialized.
**Re-open question for the user:** does the memory win justify flipping
default anyway? Not a decision-rule call.

**What the A/B does NOT prove (2026-05-23):** "graph027 sob/calo close
to baseline at one x_point" is NOT "FTFP_BERT gives the same physics
as ShieldingM." Specifically:

- **No A/B noise repeat.** We never re-ran helicalQR00_02 with same
  x_point under ShieldingM to measure 200-job run-to-run scatter. The
  +7.6% calo gap could be inside noise or real — undetermined.
  Closest existing noise measurement is the helical001 mustops_ce A/B
  noise test (task #29); whether that floor applies to mubeam-stage
  calo at this x_point is itself unverified.
- **Single x_point.** Physics-list disagreement can be x_point-dependent
  (material composition near stopping target). One geometry near the
  sob-max isn't generalizable.
- **No kinematic spectrum comparison.** Never opened the `.art` files
  to check momentum spectra, vertex distributions, per-material
  stopping rates, or EarlyMuBeamFlash flux into downstream stages.
  Two physics lists can match on summed BO objectives while differing
  on distributions that matter for other analyses.
- **Downstream-stage drift cancellation.** sob/calo are 3-stage
  products (mubeam → run1b_mubeam → concat → mustops_ce). A mubeam
  physics-list shift could cancel by mustops_ce, hiding intermediate
  drift.

**Minimum bar to actually claim physics-equivalence:** re-run
helicalQR00_02 once under ShieldingM (cheap; same template, same
x_point) to measure the noise floor at this point, then re-evaluate
the FTFP_BERT delta against that floor. For a stronger claim, also
compare materialized `.art` momentum spectra. Until then, the only
defensible claim is "FTFP_BERT produces similar end-stage BO
objectives at the helicalQR00_02 x_point."

**Noise floor measured (2026-05-23) — FTFP_BERT delta IS inside the
ShieldingM-vs-ShieldingM noise.** Re-ran `helicalQR00_02_noise` at
the same x_point under default ShieldingM (200 jobs each stage):

| Comparison | Δsob | Δcalo | Δobj (α=1e5) |
|---|---:|---:|---:|
| **Noise** (QR00_02 vs QR00_02_noise) | +1.62% | **+8.32%** | **−1.06%** |
| **FTFP_BERT** (graph027 vs QR00_02) | +1.89% | +7.66% | −0.42% |

The +7.6% calo gap I'd flagged as uncharacterized is actually *smaller*
than the measured ShieldingM-self noise floor (+8.3%). The FTFP_BERT
"effect" on sob/calo/obj is statistically indistinguishable from
run-to-run noise at n=200. **Defensible claim upgraded**:
"FTFP_BERT is physics-equivalent to ShieldingM on the BO objective
at the helicalQR00_02 x_point within measured noise (n=200, 1
A/B repeat)."

Caveats that still hold: single x_point, no kinematic spectrum check.
A grid-A/B at a second x_point + one `.art` momentum-spectrum spot-check
would close the remaining gap.

**Implication for the flip decision**: the original "wall criterion
FAILED" verdict (Δwall=−10.6% << −40% target) still stands as the
reason NOT to flip on speed alone. But the OOM-safety motive
(−45% VmPeak) is now unencumbered by any "but did it perturb the
physics?" concern at this x_point. Re-open: flip FTFP_BERT default
for memory-driven OOM safety. Decision still pending.

Raw rows in `leaderboard_bo_helical_v2.tsv`:
- `helicalQR00_02`: sob=3.700 calo=1.0577e-05 obj=2.6423 (ShieldingM)
- `helicalQR00_02_noise`: sob=3.760 calo=1.1457e-05 obj=2.6143 (ShieldingM)
- `graph027`: sob=3.770 calo=1.1386e-05 obj=2.6314 (FTFP_BERT)

**Footgun re-confirmed:** the `--config-name helicalQR00_02_ftfp` CLI flag
silently fell through to auto-increment `graph027` due to the pending-row
collision in propose_one — see [[graph-runner]] for the workaround
(clear pending TSV row before reusing a name from the CLI).

---


## Summary
Local A/B measurements of Geant4 production-cut / field-stepping / physics-list
knobs on (a) the CE harness `g4test_03.fcl` and (b) the real `mubeam` stage.
The point: identify FCL overrides that cut CPU per event without shifting the
leaderboard metrics (`s_over_sqrt_b`, `calo_per_pot`) outside Poisson noise.
One arm is safe (`minRangeCut=0.05`); two intuitively-promising arms turned
out to be unsafe (`Minimal` physics list breaks the workflow; `bfieldMaxStep`
/ `protonProductionCut` / `stepMinimum` are noise-floor).

## Key facts

- **FCL override path** for all of these knobs:
  `physics.producers.g4run.physics.<knob>` (NOT `physics.physicsList.*`).
- **Local bench location:** `/tmp/g4_speed_bench/` (CE harness) and
  `/tmp/g4_mubeam_bench/` (real mubeam stage with helical011 geom). All
  variants `#include` a baseline fcl and override one knob.
- **CE harness bench (g4test_03.fcl, 1000 events, baseline 86.9 ± 1.7%):**
  - `minRangeCut 0.01→0.1 mm`: −8.9% CPU
  - `minRangeCut 0.01→0.5 mm`: −15.6% CPU
  - `minRangeCut 0.01→1.0 mm`: −18.5% CPU
  - `protonProductionCut`, `bfieldMaxStep`, `stepMinimum`: all within ±2%
  - `physicsListName "Minimal"`: −82% CPU (4.5× speedup), but drops
    hadronic / decay processes.
- **mubeam stage bench (300 events, helical011 geom, baseline 58 s wall):**
  - `minRangeCut=0.05`: −6% CPU. TargetStops 33→35, PolyStops 7→8, FlashOut
    1→1. All Δ < 1σ Poisson — safe.
  - `physicsListName "Minimal"`: −82% CPU. **TargetStops 33→0**,
    **PolyStops 7→0**, **FlashOut 1→0**. Workflow is broken — no muons
    reach the foils despite EmStandard being included. `Minimal` is OUT
    as a speedup arm even though the workflow is "muon transport +
    geometric stop classification."
- **Why Minimal failed (root-caused 2026-05-22 via SimParticleAnalyzer on
  unfiltered g4run output, 100 events each, same input file & geom):**
  - Same 108 mu- per run (resampler is deterministic on seed).
  - Baseline: 8 mu- end in Target_Al Z-window (5471 < z < 6371 mm), all
    with `stoppingCode=32 (muMinusCaptureAtRest)`, all with KE=0.
    54 / 108 mu- already at rest (mu2eMaxSteps, KE=0), and 54 die
    spread through the TS / TSdA / downstream — physical mix.
  - Minimal: **0 mu- end in the target Z-window. 0 muMinusCaptureAtRest.**
    The "same" 54 already-at-rest mu- still end at vid=1128 with KE=0
    (these are the resampler ghosts — input file already had them stopped).
    The OTHER 54 in-flight mu- all end at **z = 52,265 mm** (world
    boundary) with `stoppingCode=182 (CoupledTransportation)` and
    KE distribution unchanged from baseline (20 mu in [1,10] MeV,
    34 mu in [10,100] MeV). Median end-Z in Minimal = 52,265 mm vs
    36.9 mm baseline.
  - Verdict: option **(a)** muons fly straight through the Al — they
    don't stop *anywhere*; `Minimal` lacks `muIoni` so muons don't lose
    energy in matter, transport-only the whole way out of the world.
    "End-process == wrong code" or "stop in wrong volume" are wrong
    framings; muons keep their multi-MeV KE all the way to the world
    boundary.
- **Diagnostic recipe** (kept in `/tmp/g4_mubeam_bench/`):
  - `diag_simp_baseline.fcl` / `diag_simp_Minimal.fcl` — minimal path
    `[genCounter, protonTimeOffset, beamResampler, g4run, g4consistentFilter]`
    + `SimParticleAnalyzer` reading `g4run` (no stop filters), `outputs: {}`,
    100 events.
  - `analyze_diag.py` — PyROOT summary: per physics-list table of mu-
    end-Z bins, stoppingCode histogram, end-KE histogram (also mu+).
  - Wall: baseline 59 s, Minimal 10 s; together comfortably <2 min.
- **Recommended grid A/B arm:** single override
  `physics.producers.g4run.physics.minRangeCut: 0.05` on mubeam +
  run1b_mubeam stages. Expected −5–10% wall reduction; verify
  `calo_per_pot` and `s_over_sqrt_b` stay within leaderboard noise on at
  least 2 replicates.
- **Env-var gotcha:** locally running `mu2e -c <fcl>` with a geom overlay
  in a non-standard directory requires BOTH `FHICL_FILE_PATH` (for
  `#include "bench_baseline.fcl"`) AND `MU2E_SEARCH_PATH` (for
  `services.GeometryService.inputFile: "bench_geom.txt"`) to be prepended.
  Setting only `MU2E_SEARCH_PATH` fails the include resolution silently
  with exit 90 "Can't find file".

## Cross-links
- Related: [[scalarized-objective]], [[bo-helical]], [[mmackenz-workflow]]
- Source files: `/tmp/g4_mubeam_bench/run_bench.sh`,
  `/tmp/g4_mubeam_bench/bench_*.fcl`
- External: [Geant4 production cuts](https://geant4-userdoc.web.cern.ch/UsersGuides/ForApplicationDeveloper/html/TrackingAndPhysics/cuts.html)
- Skills: should have used `coding-with-fhicl` for the FCL composition

## Alternative physics lists — benched 2026-05-22 (300 events mubeam, helical011 geom, parallel)

| Arm | Wall (s) | Speedup | TargetStops | PolyStops | Verdict |
|---|---:|---:|---:|---:|---|
| baseline ShieldingM | 79.83 | — | 33 | 7 | control |
| `QBBC` | 38.18 | −52% | crash | crash | **broken** — `ProcessCode` enum |
| `FTFP_BERT` | 41.38 | **−48%** | 37 | 6 | **viable**, Δ ≤ 1σ Poisson |
| `FTFP_BERT_EMV` | 42.10 | −47% | 39 | 6 | viable, Δ ≤ 1σ |
| `MinDEDX` | 29.13 | **−64%** | 34 | 8 | viable! (see caveats below) |

**FTFP_BERT is ~2× faster than ShieldingM** with stop counts unchanged
within Poisson noise. Zero code change. This dwarfs `minRangeCut=0.05`
(−6%) and is the recommended first grid A/B arm.

**Stacking bench (2026-05-22, 4-way parallel, 300 events, helical011 geom,
files `/tmp/g4_mubeam_bench/bench_FTFP_BERT_rc{05,10}.fcl` +
`run_bench3.sh`):**

| Arm | Wall (s) | vs baseline | vs FTFP_BERT alone | TargetStops | PolyStops |
|---|---:|---:|---:|---:|---:|
| baseline ShieldingM | 55.12 | — | — | 33 | 7 |
| FTFP_BERT | 21.08 | −62% | — | 37 | 6 |
| FTFP_BERT + rc=0.05 | 20.70 | −62% | −1.8% | 33 | 7 |
| FTFP_BERT + rc=0.10 | 21.08 | −62% | 0% | 34 | 5 |

**`minRangeCut` does NOT meaningfully stack on FTFP_BERT.** It gave
−6% on ShieldingM (additive) but stacks to ~0% within run-to-run jitter
on FTFP_BERT. Mechanism (best inference): ShieldingM's bottleneck was
EM cascade work that minRangeCut suppresses; FTFP_BERT already has a
lighter EM + faster hadronic (BERT) so the cuttable secondaries aren't
the bottleneck anymore. **Implication for the grid A/B: use
`FTFP_BERT` alone — second knob buys nothing and adds an audit-trail
defense.** (Caveat: baseline ShieldingM's wall is inflated by parallel
contention here vs prior 5-way bench (55.12s vs 79.83s) because it ran
solo for ~35s after the 3 FTFP arms exited. Cohort-internal FTFP
ratios are clean since they have identical contention profiles.)

**Aggressive `minRangeCut` sweep at 3k events (2026-05-22, 5-way parallel,
`run_bench4.sh` + `bench_FTFP_BERT_rc{50,100,500}_3k.fcl`):** confirms
the 300-event finding wasn't statistics-limited.

| Arm | Wall (s) | vs baseline | vs FTFP_BERT | TargetStops (σ≈18) | PolyStops (σ≈10) |
|---|---:|---:|---:|---:|---:|
| baseline ShieldingM | 114.97 | — | — | 342 | 96 |
| FTFP_BERT | 49.24 | −57% | — | 356 (+0.8σ) | 80 (−1.6σ) |
| FTFP_BERT + rc=0.5 mm | 47.28 | −59% | −4.0% | 349 (+0.4σ) | 93 (−0.3σ) |
| FTFP_BERT + rc=1.0 mm | 48.29 | −58% | −1.9% | 368 (+1.4σ) | 90 (−0.6σ) |
| FTFP_BERT + rc=5.0 mm | 47.82 | −58% | −2.9% | 363 (+1.2σ) | 89 (−0.7σ) |

Pushing minRangeCut to 5.0 mm (500× the 0.01 mm default) gives <4% wall
reduction over FTFP_BERT alone, with no monotone trend across the three
rc values — it's noise. **Stop counts are remarkably robust to
minRangeCut: even rc=5.0 mm shifts TargetStops by only 1.2σ.**
Mechanism inference: minRangeCut controls EM secondary tracking depth,
not the parent muon trajectory; TargetStopFilter only cares whether the
muon got to the Al, so killing the gamma/electron cascade around it
doesn't move that count. Important corollary: the CE-harness's
`−18.5% at rc=1.0` (g4test_03) does NOT transfer to mubeam — CE-harness
extrapolation overstates minRangeCut's value at the production stage.

**`QBBC` failure (rc=1) — Mu2e Offline incompatibility:** PostEndJob
exception "There was one or more phyics processes that are not in the
ProcessCode enum. Number of processes: 1." QBBC introduces a G4 process
that `Offline/MCDataProducts/inc/ProcessCode.hh` doesn't enumerate.
Would need an enum extension + Offline rebuild — not worth it when
FTFP_BERT delivers comparable speedup with zero patches. **Implication:
the Mu2e ProcessCode enum is a hidden constraint on physics-list
substitution; any candidate must be checked at runtime, not just on
process-coverage grounds.**

**`MinDEDX` surprise — works despite lacking `G4StoppingPhysics`:**
Agent prediction said TargetStops=0 (no `muMinusCaptureAtRest`).
Empirical: 34 vs baseline 33. **Root cause: `TargetStopFilter` selects
on kinematic state (KE≈0 in Al volume), not on end-process code.**
MinDEDX has `muIoni`, so muons physically slow to rest in the foils;
the absence of capture-at-rest just means the muon sits at the end of
its step list (mu2eMaxSteps or step-limiter), which still satisfies the
filter's KE≈0 cut. This refines the
earlier-recorded Minimal failure mode: `Minimal` fails not because it
lacks `G4StoppingPhysics`, but because it lacks `muIoni` so muons fly
ballistically through the Al at multi-MeV KE (see "Why Minimal failed"
above).

**MinDEDX kinematic validation (2026-05-22, SimParticleAnalyzer on
unfiltered g4run, 100 events; diagnostic in
`/tmp/g4_mubeam_bench/diag_simp_MinDEDX.fcl` + `analyze_diag2.py`):**
- mu- ending in Target_Al Z (5471<z<6371 mm): **MinDEDX 9 vs baseline 8**
  (Δ < 1σ Poisson). Same 9 muons have KE≈0.
- End-Z histogram bin-by-bin matches baseline: MinDEDX 87/3/5/0/9/0/4 vs
  baseline 88/1/6/0/8/0/5 across the 7 Z windows.
- End-KE distribution **bit-identical** to baseline both globally
  (54@KE≈0, 20@[1,10] MeV, 34@[10,100] MeV) and restricted to the
  target window (8 @ KE≈0 baseline, 9 @ KE≈0 MinDEDX).
- Total SimParticles: baseline 35,827 vs MinDEDX 1,315 = **27× fewer
  secondaries**. This is where the −64% wall comes from — MinDEDX skips
  the EM cascade in TS material.
- **Caveat — different at-rest stoppingCode label:** MinDEDX uses
  `code_31` (likely `hMinusCaptureAtRest` or a generic atomic-capture
  handler) where baseline uses `code_32 = muMinusCaptureAtRest`. Both
  fire on 54 muons; **kinematic outcome identical** but the process-code
  metadata differs. **Production-blocker CONFIRMED (2026-05-22):**
  `stoppedMuMinusList(simh)` in
  `Offline/Mu2eUtilities/src/simParticleList.cc:15` does
  `inpart.stoppingCode() == ProcessCode::muMinusCaptureAtRest` (hard
  equality on code 32). Called by `CeEndpoint_module.cc:120`,
  `FlatMuonDaughterGenerator_module`, and `Pileup_module`. MinDEDX
  code-31 stops are silently dropped → `mustops_ce` stage's CeEndpoint
  generator throws. MinDEDX is **NOT** usable as a drop-in for the full
  production chain. To use MinDEDX in production needs one of: (a)
  patch `simParticleList.cc:15` to accept {31, 32} (Muse-backed Offline
  rebuild — see [[muse-backing-pattern]] for the helical-plug
  precedent), or (b) re-tag code 31 → 32 in
  `Mu2eG4CustomizationPhysicsConstructor` before the SimParticle is
  written out. Either is a bigger change than the bench warranted.
  **Recommendation: use `FTFP_BERT` (−48% wall, zero code change,
  fires code 32) for the grid A/B instead.**

**MinDEDX open questions:**
- Does any downstream stage filter on `stoppingCode == 32`? If no,
  MinDEDX is production-ready at −64% wall.
- `G4Decay` presence unverified — but irrelevant for TargetStops
  generation (DIO is generated downstream from TargetStops).
- Calo flash spectrum unchecked; calo_per_pot impact unknown (measured
  in run1b_mubeam, not mubeam — would need separate bench).

## Alternative physics lists — pre-bench analysis (kept for context)
The `Minimal` failure mode generalizes: the **required** constructors for
the mubeam workflow are (a) an EM constructor that defines `muIoni`
(any `G4EmStandardPhysics[_optN]`), (b) `G4DecayPhysics`, (c)
`G4StoppingPhysics` (owns `muMinusCaptureAtRest`). Drop anything else.

**`physicsListDecider.cc` accepted names** (`Offline/Mu2eG4/src/physicsListDecider.cc`,
inspected against Musings/Offline/v10_07_00):
- 3 Mu2e-defined hard-coded names at lines 69-81:
  - `Minimal` → `Mu2eG4MinimalModularPhysicsList` (transportation +
    step-limiter only; no muIoni, no capture — broken for mubeam)
  - `MinDEDX` → `Mu2eG4MinDEDXModularPhysicsList` (EM only; has muIoni
    but **no `G4StoppingPhysics`** → muons ionize and slow to rest but
    do not capture. Useful as an *ablation* arm to confirm root cause
    from the other direction.)
  - `ErrorPhysicsList` → `G4ErrorPhysicsList` (for track-error
    propagation; unrelated to production)
- Anything else is delegated to `G4PhysListFactory` at line 89 — accepts
  `ShieldingM` (the default), `Shielding`, `FTFP_BERT`, `QGSP_BERT`,
  `QBBC`, and `_EMV`/`_EMX`/`_EMY`/`_EMZ` suffixed variants.
- Every list (including the Mu2e-defined ones) gets
  `Mu2eG4StepLimiterPhysicsConstructor` + `Mu2eG4CustomizationPhysicsConstructor`
  appended at lines 101-104.
Ranked candidates:
- **`FTFP_BERT_EMV`** — stock G4 list with "EM opt1" (designed for HEP
  production). Includes Stopping + Decay + EM-with-muIoni. Qualitatively
  1.5×–2× vs ShieldingM. Zero code change if `physicsListDecider.cc`
  already registers it (TBD).
- **Custom ModularPhysicsList** "Mu2e-Lite" =
  `G4EmStandardPhysics_option1 + G4DecayPhysics +
  G4StoppingPhysics(useMuonMinusCapture=true)`. Largest possible
  speedup — close to Minimal's −82% but workflow-safe. Needs a new
  constructor class in `Mu2eG4/src/` registered via
  `physicsListDecider.cc`.
- **`QGSP_BERT_EMV`** — equivalent to FTFP_BERT_EMV for our muon-only
  stage (no hadronic showers); listed only as backup.
- **Footgun:** `G4StoppingPhysics(useMuonMinusCapture=false)` silently
  kills capture. The default is `true` — keep it.

## G4 ODE stepper (`physics.producers.g4run.physics.stepper`)

**Default (Offline v10_07_00):** `G4DormandPrince745` — adaptive embedded
5(4) RK, set in `Offline/Mu2eG4/fcl/prolog.fcl:47`. Already the modern
"fast" choice; limited headroom expected.

**5-arm bench (2026-05-22, FTFP_BERT × stepper, 3k events parallel,
`run_bench5.sh` + `bench_FTFP_{dp745,helixSR,helixIE,rk4,bs23}_3k.fcl`):**

| Arm | Wall (s) | vs dp745 | TargetStops | PolyStops |
|---|---:|---:|---:|---:|
| **FTFP_dp745 (default)** | **47.46** | **—** | 356 | 80 |
| FTFP_helixSR | 50.83 | +7.1% | 363 (+0.4σ) | 88 (+0.8σ) |
| FTFP_helixIE | 49.66 | +4.6% | 354 (−0.1σ) | 89 (+0.9σ) |
| FTFP_rk4 | 54.97 | +16% | 344 (−0.7σ) | 95 (+1.5σ) |
| FTFP_bs23 | 95.25 | **+101%** | 340 (−0.9σ) | 94 (+1.4σ) |

**`G4DormandPrince745` is already optimal — no stepper swap helps.**

- **Helix-aware steppers LOSE** (5-7% slower) despite TS being solenoidal.
  Mubeam transport spans the whole geometry (DS, calo, world), not just
  the TS solenoid; helix steppers assume pure-helix motion and degrade
  in non-helical regions. dp745's adaptive step expansion in
  low-gradient regions wins on net.
- **`G4BogackiShampine23` is 2× slower** — counterintuitive for an
  adaptive 3(2). At the tight `epsilonMin/Max = 1.0e-5` in
  `prolog.fcl:53-54`, the lower-order method needs dramatically more
  steps to hit the same error bound. Lower-order adaptive RK is an
  anti-pattern at this tolerance.
- **Subtle PolyStops pattern (caveat):** all 4 non-default steppers
  gave higher PolyStops (88-95) than dp745 (80), clustering closer to
  baseline ShieldingM's 96. Joint probability of 4 same-side draws by
  chance ≈ 6%. May indicate dp745+FTFP has a small systematic PolyStop
  suppression vs other steppers; TargetStops unaffected. Re-bench with
  more replicates if PolyStops matter to the BO objective.

**All 10 registered stepper names** (enumerated in
`Offline/Mu2eG4/src/Mu2eWorld.cc:440-477`; everything else throws
`cet::exception("GEOM") "Unrecognized stepper"` at line 479):
- `G4DormandPrince745` (default, adaptive 5(4))
- `G4DormandPrince745WSpin`
- `G4ClassicalRK4` (classic fixed-order)
- `G4ClassicalRK4WSpin`
- `G4ImplicitEuler` / `G4ExplicitEuler` (low-order)
- `G4SimpleRunge` / `G4SimpleHeum` (2nd-order)
- `G4HelixImplicitEuler` / `G4HelixSimpleRunge` (helix-specialized,
  designed for solenoidal fields like our TS)
- `G4BogackiShampine23` (adaptive 3(2), lower-order embedded RK)

**Hidden constraint (`physicsListDecider.cc:152-157`):** if
`decayMuonsWithSpin: true`, the code throws unless stepper is one of
`G4ClassicalRK4WSpin` / `G4DormandPrince745WSpin`. The default chain
(MuBeamResampler + epilog_1b) does NOT set `decayMuonsWithSpin`, so any
of the 10 above are legal in our mubeam path.

**Spin-equation note:** the WSpin variants instantiate the stepper at
order 12 with `G4Mag_SpinEqRhs` instead of the default order-6
`G4Mag_UsualEqRhs` — i.e. they integrate spin alongside position/momentum.
Don't enable WSpin unless you need spin output; it doubles state per
step.

## Untapped FCL knobs (audited 2026-05-22, Mu2eG4Config.hh + prolog.fcl)

All of these are reachable from MuBeamResampler chain via
`physics.producers.g4run.<group>.<knob>` with one-line FCL override — no
code change, no Offline rebuild. NOT YET BENCHED.

**Per-region production cuts (highest FCL-only lever, ~5–20% expected):**
- `physics.minRangeRegionCuts: {<region>: <mm>, ...}` — `Mu2eG4Config.hh:143`,
  applied in `Mu2eWorld.cc:276-312`, defaulted unset (commented in
  `prolog.fcl:19`). Bigger lever than global `minRangeCut` because tight
  cuts can be retained at the Al target / TS while loosened elsewhere.
  Risk: collapsed calo secondaries if `CalorimeterMother` ≥ 1 mm.

**Output / runaway hygiene (near-zero physics risk):**
- `TrajectoryControl.mcTrajectoryMomentumCut` — default 50 MeV/c
  (`prolog.fcl:85`). Raising to 200 cuts trajectory storage for low-p
  tracks; transport-CPU unchanged, I/O shrinks.
- `TrajectoryControl.defaultMinPointDistance` — default 500 mm
  (`prolog.fcl:83`); `perVolumeMinDistance` table at `prolog.fcl:88-101`
  (PSVacuum/CalorimeterMother = 15 mm).
- `ResourceLimits.maxStepsPerTrack` — default 100000
  (`Mu2eG4ResourceLimits.cc:5`, enforced in `Mu2eSpecialCutsProcess.cc:64`).
  Hard-kills runaway tracks; lowering catches cascade pathologies.
- `ResourceLimits.maxStepPointCollectionSize` / `maxSimParticleCollectionSize`
  — default 100000 each; **truncate output silently** if hit, dangerous to
  lower without measuring saturation rate first.

**Composable per-step / per-stack kill predicates (powerful but risky):**
- `Mu2eG4SteppingOnlyCut`, `Mu2eG4StackingOnlyCut`, `Mu2eG4CommonCut`
  (DelegatedParameter) — `Mu2eG4Config.hh:228-230`. Predicate algebra
  (`union/intersection/plane/inVolume/notInVolume/pdgId/notPdgId/isNeutral/`
  `isCharged/kineticEnergy/globalTime/primary/constant`) lives in
  `Mu2eG4Cuts.cc:744-769`. Composable kills entirely in FCL. Example:
  `{type: kineticEnergy, cut: 10, pdg: [11,22]}` would kill low-E EM
  secondaries. Risk: easy to break calo_per_pot.

**Other physics knobs:**
- `physics.strawGasMaxStep` — default −1 (disabled), `prolog.fcl:61`.
  Local step limiter in straw gas only (tracker stage, not mubeam).
- `physics.limitStepInAllVolumes` — default false, `prolog.fcl:63`.
  Globally applies `bfieldMaxStep` everywhere (typically a slowdown).
- `physics.noDecay` — PDG-list of particles whose decay is disabled;
  empty by default (`prolog.fcl:14`).

## Framework-level fast-sim options (audited 2026-05-22, ranked for mubeam)

**Production-deployable today:**
- **G4ImportanceProcess / Russian-roulette biasing** — **highest absolute
  leverage (2–5× estimated)** for mubeam by killing muons that miss the
  TS aperture and splitting survivors near TSdA. Requires `G4IStore`
  wired into `Mu2eWorld` (~1 week). **BLOCKER:** downstream must be
  weight-aware — `s_over_sqrt_b`, `calo_per_pot` need to propagate
  per-track weights. Major analysis audit; not a drop-in.
- **Kill-shell at world boundary** — `G4UserStackingAction` flag.
  Estimated 2–8% by killing back-scattered secondaries. Cheap fallback
  if importance biasing's weight audit blows up.

**Defer / not applicable:**
- **AdePT** (CERN GPU EM transport) — no GPUs on Mu2e grid; muons not
  offloaded yet. CHEP 2025: still in integration phase. Non-starter
  today.
- **Celeritas** (ORNL/FNAL GPU) — muon EM support recently added
  (brems/ioni/pair-prod) but still e±/γ-first. **No Mu2e integration
  exists.** Mubeam gain ~0 today without GPUs. CMS Run-3 is the only
  production deployment. Revisit in ~12 months.
- **VecGeom** — vectorized geometry. 5–15% on tube-heavy geometry like
  ours but **requires Offline rebuild** to link/swap solid impls.
  Tessellated-plug fragility (see [[tessellated-solid-facet-orientation]])
  raises overlap/boundary risk. Not worth it for marginal gain.
- **G4-MT** — Mu2e has `Mu2eG4MT_module.cc` but hardcodes
  `SetNumberOfThreads(1)` (line 82). No FCL exposure of nThreads. Even
  if exposed: 1-slot grid jobs → MT overhead dominates, near-0% real
  gain. Per-thread RNG re-seeding is the main code change.
- **GFlash / G4FastSimulationManagerProcess** — parametrized EM showers.
  **Wrong stage for mubeam** (no calo). Worth re-evaluating for
  `run1b_mubeam` if/when calo stage is benched.
- **EM physics opt0–4** — already covered: `FTFP_BERT_EMV` (opt1) vs
  `FTFP_BERT` (opt0-ish default) was −1.4% in our 5-arm bench (see
  table above). Diminishing returns; FTFP_BERT default is essentially
  HEP-tuned EM already.

## Mu2e community precedent (audited 2026-05-22)

**No prior collaboration fast-sim work on mubeam exists.** No Musing
tagged `fast/lite/smoke/quick`; no `FastSim`/`GFlash` in Offline; no
benchmark notes from mmackenz; `Mu2eG4MT_module.cc` ships but no
production benchmark on-disk; `mu2ewiki.fnal.gov` pages paywalled (HTTP
402 from this env), DocDB unchecked.

**Two non-obvious facts that change our priors:**

1. **Production POT-beam already uses `minRangeCut: 1.0` (100× the
   `0.010 mm` default in `Offline/Mu2eG4/fcl/prolog.fcl:16`).** Sites
   that override: `Musings/SimJob/Run1Bak/Production/JobConfig/beam/`
   `{epilog_1b.fcl:18, POT.fcl:71, POT_extmon.fcl:71,`
   `POT_validation.fcl:113}` + `cosmic/S1DSStops.fcl:77` +
   `extmon/extmonbeam_g4s2.fcl:149`, all tagged "coarse range for this
   stage." **Implication:** our `0.05/1.0/5.0` mubeam sweep arms are
   *more conservative* than what production already trusts for sibling
   beam stages. The reason the Run1B mubeam stage doesn't have this
   override is asymmetric inheritance (next point), not a deliberate
   safety choice.

2. **mmackenz mubeam (and our autoresearch chain mirroring it) `#include`s
   `Production/JobConfig/pileup/epilog_1b.fcl`, NOT
   `JobConfig/beam/epilog_1b.fcl`.** These are different files in
   different subdirs. The `beam/epilog_1b.fcl` carries both
   `minRangeCut: 1.0` AND a `Mu2eG4CommonCut` block (volume/KE/pdgId
   kills via `KillerVolumesCache` from `Mu2eG4Cuts.cc:456`); the
   `pileup/epilog_1b.fcl` carries neither. **Two unexplored axes for
   free speedup on our mubeam stage:** (a) raise `minRangeCut` to
   production-blessed `1.0` (already shown ~0% extra on top of
   FTFP_BERT in our 3k bench — confirms no harm), (b) port the
   `beam/epilog_1b.fcl` `Mu2eG4CommonCut` block. (b) is orthogonal to
   physics-list choice and not yet benched.

**FTFP_BERT is genuinely new ground for mubeam.** Mu2e's `ShieldingM`
choice was made for hadronic backgrounds at the production target
(pion-production Bertini transition); no published Mu2e benchmark of
swapping it out *for the mubeam stage only* — our −48% finding appears
to be the first.

## Open questions / TODO
- **Production-blocker check (MinDEDX):** grep Mu2e Offline + workflow FCLs
  for selectors on `stoppingCode == 32` (`muMinusCaptureAtRest`). Candidates:
  `mustops_ce`, `CeEndpoint` generator, `StoppedMuonResampler`. If any of
  these filter on code 32, MinDEDX's code-31 stops are invisible
  downstream and the −64% wall is unusable as-is.
- **G4FastSimulationManagerProcess / GFlash** is the right tool for the
  *calo* stage (`run1b_mubeam`) where EM showers dominate, NOT for mubeam
  where the cost is muon transport through the TS. Don't invest in GFlash
  until run1b_mubeam is locally profiled and confirmed CPU-bound on calo
  EM showers. Pure `G4EmStandardPhysics` (no FastSim) would be slower than
  MinDEDX since it still generates the full secondary cascade — MinDEDX's
  −64% comes from cascade suppression (27× fewer SimParticles), not from
  EM-only-ness.
- **Stacking-action cuts (orthogonal axis):** `Mu2eG4StackingAction.cc` +
  `Mu2eG4CustomizationPhysicsConstructor` may already kill known-irrelevant
  secondaries; tightening them is independent of physics-list choice and
  composable with MinDEDX/FTFP_BERT.
- Run a 2-replicate grid A/B at `minRangeCut=0.05` against current
  best-known config (e.g. `helicalP01`) to confirm leaderboard-noise
  preservation on full-statistics jobs.
- Try `minRangeCut=0.1` as a more aggressive arm if 0.05 holds.
- Re-test `bfieldMaxStep` / `stepMinimum` directly on mubeam, not CE
  harness — they were noise-floor on g4test_03 but muon helical motion
  through the TS may be more sensitive.
- Bench the Mu2e-Lite modular list (custom
  `G4EmStandardPhysics_option1 + G4DecayPhysics + G4StoppingPhysics`)
  only if MinDEDX is blocked by code-32 downstream filters; otherwise
  MinDEDX is the empirical winner and a custom list is overkill.
