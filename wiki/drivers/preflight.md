# preflight — local G4 init feasibility check

**Type:** driver
**Status:** active
**Updated:** 2026-05-20

## Summary
Runs a single `mu2e -n 1` locally (Musing setup) on a BO proposal's geom file
to verify that Geant4 geometry construction succeeds before paying for grid
submission. Catches overlapping-volume errors, bad placements, and
missing-include-chain issues. Subcommand of [[autoresearch-bo-michael]].

## Key facts
- **Path:** `autoresearch_bo_michael.py cmd_preflight`
- **FCL selection (single G4 init, landed 2026-05-19):**
  - helical mode → `surfacecheck.fcl` (init + surface-check overlap scan).
  - non-helical modes → `preflight.fcl` (init only — no overlap diagnostics needed).
  - Replaces the prior two-pass design (preflight.fcl, then surfacecheck.fcl)
    which paid G4 geometry construction ~3 min twice per iteration. Single-pass
    wall is ~4m20s (slightly more than plain init because surface-check
    samples ~1k points per volume) but ~33% faster overall than the two-pass
    chain. For q=5 batches this saves ~15 min/iteration.
- **Templates:** inline `PREFLIGHT_FCL_TEMPLATE` + `SURFACE_CHECK_FCL` +
  `SURFACE_CHECK_GEOM_OVERLAY` constants. **No `#` comments** (fhicl
  interprets `#` as include); also no `//` comments — bare statements only.
- **Geom-fail regex:** `G4Exception.*?(GeomMgt000\d|GeomVol1002|placement|outside mother|overlap)`.
  **Only consulted when `past_init=False`** — surface-check emits ~117
  `GeomVol1002` WWWW advisory warnings on every baseline overlap, which
  would falsely trip this regex during the single-pass design. If the run
  reached the event loop, geometry constructed successfully; surface-check
  WWWW lines are diagnostic, not failures.
- **Surface-check parse:** `SURFACE_OVERLAP_RX` collects every "Overlap is
  detected for volume X" line; `SURFACE_OVERLAP_MANAGED` filters to volumes
  our BO knobs touch (TSdA region). Baseline overlaps (~117 stock-geometry
  hits like FoilSupportStructure, DS3 rails) are reported as info and
  ignored.
- **Pass condition:** `rc==0` OR `past_init` (BeginRun / event-loop tokens
  in stdout) OR timed-out, AND (helical only) no managed-volume overlap.
  `rc != 0` is *expected* because g4run.produce() needs a primary particle
  source we don't supply — beginRun (geom build) ran first, which is what
  we test.
- **Timeout:** 600 s (G4 init failures usually surface in <60 s)
- **Logs:** `bo_michael_preflight/<cfg>.log` (non-helical),
  `bo_helical_preflight/<cfg>.log` (helical). Single log per run since 2026-05-19;
  the prior two-pass design wrote `<cfg>.log` + `<cfg>_surfacecheck.log`.
- **Setup:** sources `setupmu2e-art.sh` then `Musings/SimJob/Run1Bak/setup.sh`
- **MAJOR CAVEAT — patched lib NOT loaded (2026-05-20).** `cmd_preflight`
  sources only the stock CVMFS `Run1Bak/setup.sh`; it does NOT source
  `autoresearch_muse/`'s muse setup or the shipped `Code/setup.sh`. So the
  helical plug (`TSdAHelicalTube`) is constructed using the **stock** Offline
  code, not the patched library that grid jobs use. Helical-plug-specific
  bugs (e.g. the negative-volume defect — see
  [[tessellated-solid-facet-orientation]]) are therefore invisible to
  preflight. To fix: source the local muse setup before running `mu2e -n 1`,
  or extract `Code_helical_base.tar.bz2` and source its `setup.sh`. Until
  then, helical-plug failures only surface in grid worker logs (and the
  end-of-workflow scan_logs node).

## Cross-links
- Used by: [[autoresearch-bo-michael]]
- Surfaced bug: [[geom-run1a-vs-run1b]]
