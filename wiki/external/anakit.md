---
type: external
title: anakit — M. MacKenzie's analysis MCP server
description: 'M. MacKenzie''s analysis MCP server, checkout of his main pinned at 53c5afa, run on the SimJob MDC2025ay Musing; feeds the _ax studies and ce_chain; needs mcp<2 (ana 2.7.0, -P)'
status: active
timestamp: '2026-11-06'
---

# anakit — M. MacKenzie's analysis MCP server

## Summary
anakit is M. MacKenzie's analysis MCP server
(github.com/Mu2e/analysis-mcp; until 2026-11-03
github.com/michaelmackenzie/analysis-mcp-server). The contract engine
drives it through `core/adapters/anakit.py`
([contract-engine](/drivers/contract-engine.md), "anakit kit") for every
`kit: "anakit"` step. Since 2026-10-07 the physics lives only in his repo:
the `_ax` studies (`foilspfbpz_ax`, `foilsflash_ax`) chain his separate
analyses step by step, the stopping rate travelling between steps through
`params_from`, and this repo only wires numbers. Until then we ran a fork
with three analyses of our own; a short history is kept below.

## Key facts

**Mu2e/analysis-mcp (2026-11-04)**
- The repo now lives at github.com/Mu2e/analysis-mcp, a new repo (created
  2026-11-03, not a GitHub transfer: michaelmackenzie/analysis-mcp-server
  still exists, unarchived, and the forks still point there). First release
  `v01_00_00` = de4b509 (his PR #12, 2026-11-02), 26 commits past a96b57a.
  Not on cvmfs yet. It does not carry our straw tools.
- It has `edep_occupancy` and `edep_occupancy_combine`: per-component
  occupancy, dose and busiest-channel rates from EdepAna's own
  `EDepAna/occupancy` histograms, scaled per microbunch and summed per
  channel before taking peaks (the same idea as our DoseMap + straw_map +
  straw_rates). Its phi average is a "straw row": one plane and straw number
  over the six panels (6 straws; ours groups 12, station x straw number).
  Those histograms come from Offline PR #2097 (merged 2026-11-03): not in
  v13_43_00 (MDC2025bb), so it cannot run there, but in v13_44_00, behind
  SimJob MDC2025bc (`current` since 2026-11-04; Production v02_23_00,
  mu2e-trig-config v8_12_00). v13_44_00 also has Offline PR #2089, so
  `hasProtonAbsorber = false` builds there (constructStoppingTarget.cc:79
  checks `hasElement`).
- Cross-check 2026-11-05 on nopa01's files (MDC2025bb dts, MDC2025bc EdepAna):
  `v01_00_00` cannot run on v13_44_00 (EdepAna requires FoldTimeOffset and
  Trk/CaloHitTimeMin/Max; analysis-mcp main 7784794 passes them, PR #1). Its
  default hit window is the digitizers' event-window frame (FoldTimeOffset
  -200 ns, tracker 250-1505 ns = 450-1705 ns after the protons), wider and
  earlier than the noipa note's 500-1695 ns: tracker hits per microbunch
  stopped mu-/electron flash/muon flash 1119/193.9/60.9 vs our 1041/141.7/58.4,
  busiest 6-straw row 265.6 vs 236.1 kHz. With our window (offset 0,
  500-1695) the busiest straw (648.8 kHz) and row (236.1 kHz) and the
  stopped-mu total agree exactly; the flash totals are 3.4% and 1.5% higher.
- `v01_01_00` (tagged 2026-11-06) = 7784794, Mu2e/analysis-mcp main with the
  hit-window fix: the commit the cross-check ran. The release to pin for
  MDC2025bc. Not on cvmfs yet.
- Normalization (2026-11-06). `edep_occupancy` scales per STORED event:
  factor = `events_per_microbunch` / n_events (EdepAna's `nevents`). That
  fits production Cat samples, whose stored events per POT are in
  SimEfficiencies. For our per-design samples the stored fraction changes
  with every design, so the right factor is per GENERATED event:
  gen_events_per_pot x POT per microbunch / n_gen (n_events cancels). The
  tool already has n_gen: EdepAna prints `Saw N events (M gen events)` in the
  same job (`edep.py` parses it; `generated_events()` reads `ngen`). On
  nopa01's files M equals our draws exactly: 1e6 stopped mu, 1.1e7 electron
  flash, 3e6 muon flash. Gen events per POT: `stops.stops_per_pot`,
  1/11.536718606512062 (electrons), 0.01278168 (upstream_eff). The same
  repo's `approx_ce_sensitivity` already divides by `ngen` with a
  `stops_per_pot` parameter, and refuses max_events runs (ngen keeps a cut
  subrun's whole count). Our cross-check used 1.6e7 POT per microbunch; the
  tool's help quotes 1.58e7 (Run 1A).
- Michael's analysis-mcp PR #3 (004df54, open 2026-11-06) adds exactly this:
  `gen_events_per_pot`, `pot_per_microbunch` (default 1.58e7) and
  `prescale_filter` (ours stays unset: our Early outputs are unprescaled).
  On nopa01's files with 1.6e7 it gave 710.483 / 6605.06 / 436.963 events
  per microbunch, and all 148 combine numbers equal the hand-normalized run.
- Pin since 2026-11-06: local branch `straw-maps-v01_02` (0df814e) = his
  `v01_02_00` + our straw tools (conflicts only in tests/test_tools.py and
  tools/registry.py, both sides kept; 266 tests ok). Replaying nopa01's
  stops, ce_edep, sob and flash on it gave all 72 recorded metrics bit for
  bit, so `VERSION` stays `anakit-adapter/2`. The old branch `straw-maps`
  (c4c30e3) is kept.
- Region peak (analysis-mcp PR #4, open 2026-11-06): the busiest 12-plane x
  8-straw x 6-panel region. On nopa01 (about 40 / 8 / 15 microbunches of
  stopped mu / electron flash / muon flash) it is 157.3 kHz against 265.6
  for the row. Split test (files cut into 5 groups by grid job, both
  analyses per group): region 156.2 / 154.7 / 146.0 / 177.2 / 156.4 kHz,
  sd 7.3% per group, so 3.3% for the full sample (log10 noise about 0.014),
  and unbiased at 1/5 statistics (mean 158.1); the tool's own `_err`
  understates it by about 2.2x. The row is biased (484 kHz at 1/5
  statistics, 14% sd at full) and the single straw unusable (885 to 2088
  kHz). The split shares one stop sample, so stop-position noise is not in
  it. Stopped mu- carry 88% of the peak region.
- `v01_03_00` (tagged 2026-11-06) = e40d3d4, PR #4 merged as reviewed (my
  review was not posted, so its note that region `_err` is about 2x small
  is still open upstream). The `_bc` studies steer on
  `occupancy.trk_peak_region_hit_rate_khz` (12 x 8 set explicitly, noise
  0.014). Since the _bb studies were dropped (2026-11-06), both the
  foilsnopa and the release-manifest branches pin plain v01_03_00
  (e40d3d4); the local straw-maps* branches stay in the checkout, unused.

**The checkout**
- `$AUTORESEARCH_ANAKIT` (the `activate.sh` default
  `/exp/mu2e/app/users/oksuzian/analysis-mcp-server`) is his `main`,
  at `53c5afa` (2026-10-30: PRs #5-#10 — `total_edep_per_pot` and the
  `parameters` input kind, EdepAna step counts, mu-/mu+ stop split in
  `muon_stop_rate`, SAM/metacat inputs; `edep`'s and `muon_stop_rate`'s
  existing metrics unchanged, col5r01R00_00's stops reproduced exactly, so
  VERSION stays). From this pin `edep` declares the `*_nsteps_*` step
  counts but leaves them out on a Musing without Offline #2067, so the
  adapter treats a missing `_nsteps` metric as absent (`OPTIONAL_METRIC_MARK`);
  every other declared metric is still required, and a study that reads a
  step count fails at scoring. Before: `3ba8d23` (2026-10-07: PR #3 stops_per_pot and
  PR #4 R_mue x captures per stop merged, plus S. Middleton's `fullsim`
  analyses). The fork's local branch `autoresearch` stays in that clone as
  the record of the retired analyses; nothing runs from it.
- **Pull rule:** pull only on purpose; read the diff of the four analyses
  the studies use (`muon_stop_rate`, `edep`, `approx_ce_sensitivity`,
  `trigger_efficiency_ntuple`, and what they import); bump
  `core/adapters/anakit.py:VERSION` if their numbers change. The checkout
  commit is each step's recorded build, never part of `measure_sha`.
- **Pin:** `core/adapters/anakit.py:ANAKIT_PIN_SHA` names the accepted
  commit, and the suite asserts the checkout matches it
  (`tests/test_anakit_kit.py` TestAnakitPin, like `SURROKIT_PIN_SHA`):
  his defaults and the DIO constants sit outside `measure_basis`, so a
  pulled checkout fails the suite instead of moving the numbers. The
  engine itself does not refuse a newer commit (a step records its
  build); bump the pin after re-validating.
- `VERSION = "anakit-adapter/2"` (2026-10-07): the server runs on a Musing.
- The adapter reads each analysis's `input_kind` from `list_analyses`; a
  missing kind or one outside `INPUT_KINDS = ("art_files", "root_file")`
  is refused at launch and at `submit`.
- `kits.toml [servers.anakit]` runs it under ana 2.7.0 (his
  `pyproject.toml` pins `mcp<2`) with `-P`, and sets
  `OPENBLAS_NUM_THREADS=OMP_NUM_THREADS=1` (his `AGENTS.md`).

**The Musing**
- Study setting `kits.anakit = {"musing": "SimJob MDC2025ay"}`; the adapter
  appends `--musing <it>`. His `edep` needs EdepAna from Offline v13_39_00
  (MDC2025ay or later), which writes the `EDepAna/tree` his analyses read;
  our old work area's EdepAna (a Mu2eOptAna build on MDC2025ax) wrote none.
- The grid jobs stay on MDC2025ax (`Code_mdc2025ax.tar.bz2`); only the
  analyses run on MDC2025ay. MDC2025ay's EdepAna reads an MDC2025ax
  CeEndpoint file and its tree agrees with its printed summary (75,000
  generated, 39,152 seen; checked 2026-10-07).
- The study loader takes one spelling only, `<Musing> <version>` with one
  space (`core/kit_registry.py:_musing`, 2026-10-07): the setting is
  hashed as written, so `SimJob/MDC2025ay` would have given the same
  Musing a second `measure_sha`.
- The launch check refuses a missing setting, a value that is not a Musing
  and a version (split as his `Mu2eEnv.for_musing` splits: `/` or spaces),
  and an unpublished one (no `/cvmfs/mu2e.opensciencegrid.org/Musings/<M>/<v>`).
  The work-area checks (`backing_problem`, `code_commit`) are gone; the
  result records `musing` in their place.
- `approx_ce_sensitivity` reads the DIO table from his personal area
  (`/exp/mu2e/app/users/mmackenz/run1b/Run1BAna/data/heeck_finer_binning_2016_szafron.tbl`,
  `DIO_TABLE`, not a parameter) and fixes the DIO fraction (0.391).

**The studies' four steps** (both `_ax` studies)
- `stops`: `muon_stop_rate` on `mubeam` (TargetStops files only),
  `upstream_eff` 0.01278168 (was `input_correction`).
- `ce_edep`: `edep` on `mustops_ce`; its result file, the EdepAna ntuple,
  is the next step's input. The slowest step: 933 s on bpzax01R12_00's
  files on a loaded node (2026-10-07), under the adapter's
  `RUN_TIMEOUT_S` of 3000 s.
- `sob`: `approx_ce_sensitivity` on `ce_edep`, `params_from`
  `{"stops_per_pot": "stops.stops_per_pot"}`, `cosmic_rate_per_s_per_mev`
  0.0018181818181818182 (the macro's 2e4/1.1e7, 141.8x his default).
  Objective `sob.sensitivity`.
- `total_edep_per_pot` (2026-10-29, analysis-mcp-server PR #9; input_kind
  `"parameters"`, no files): electron flash / 11.5367 + muon-beam flash ×
  0.01278168 + muon-stop pileup × stops_per_pot, per POT, with each share.
  `foilsflash_col5bf_ax`'s dose objective. Needs the anakit pin bumped past
  PR #9 once it merges.
- `flash`: `edep` on `elebeam_flash`. Objective
  `flash.avg_trk_edep_per_gen_event_mev` is MeV per generated beam
  electron, not per POT (the engine does no arithmetic), so the budget is
  the per-POT one times 11.536718606512062: 7.506758e-06. Under log10 that
  is a constant shift.
- New boards `leaderboard_bo_<study>_upstream.tsv`; the old `_ax` boards
  are history. sob is about 0.35x the old values: the signal fix (x0.371)
  plus counting only selected events (about 6% more).

**Acceptance (2026-10-07 local, 2026-10-08 grid)**
- `bpzax01R12_00` re-analysed locally through the engine: `stops_per_pot`
  1.2618671e-03 exact; flash 6.58426e-06 per electron vs the fork's value,
  1e-7 relative (so the budget conversion stands); `sensitivity`
  1.3270656749061143, identical to his tool run by hand (old board x0.3474).
- First grid rows on the `_upstream` boards: `bpzup01` (2026-10-08), then
  the refill bpzup02-21 and the `nomup01` baseline (sob 1.14014, flash
  7.50675e-06 = the damage budget to 6 digits).

**`ce_chain`**
- The `plot` step is `trigger_efficiency_ntuple` with `trigger_paths`
  `"apr_TrkDe_80m70p, cpr_TrkDe_80m70p"`; objective `n_selected`, extra
  metrics `efficiency`, `n_triggered`, `n_events`; board
  `leaderboard_ce_chain_upstream.tsv`. The ntuple is the triggered stream
  (`CeEndpointOnSpillTriggered`), so the efficiency is conditional: a
  check of the chain, not a trigger measurement.

**Retired (2026-10-07)**
- The fork's `ce_sensitivity`, `flash_edep_per_pot`, `nts_momentum`; the
  anakit settings `input_correction`, `dio_fraction`, `dio_table`,
  `pot_per_electron` (refused at load); the work area
  `/exp/mu2e/app/users/oksuzian/autoresearch_muse_ax` (left on disk,
  unused).
- Not used: S. Middleton's `fullsim.sensitivity` — it needs mixed,
  reconstructed CE EventNtuples and SAM provenance, which per-point files
  are not.

## History (fork, 2026-09-27 to 2026-10-07)
- We ran a fork (local branch `autoresearch` in the same clone, upstream
  base `039e969`) with three analyses of our own: `ce_sensitivity`
  (S/sqrt(B) from one point's files), `flash_edep_per_pot` and
  `nts_momentum` (reconstructed |p| at the tracker front, the first
  `ce_chain` plot step). The branch stays in the clone as the record;
  nothing runs from it.
- The fork ran with a work area, `autoresearch_muse_ax` (SimJob MDC2025ax +
  a Mu2eOptAna build whose EdepAna printed its summary at full precision).
  It is left on disk, unused. Its EdepAna wrote no `EDepAna/tree`, which is
  why the upstream analyses need the MDC2025ay Musing.
- Until 2026-10-05 the kit version carried the fork commit, so any fork
  commit split every `_ax` board; since then versions are hand-bumped and
  the commit is only each step's recorded build.
- The fork-era EdepAna (Mu2eOptAna) read M. MacKenzie's DIO table from
  his personal area in every job; the module failed to construct without it.
- Check numbers the fork reproduced: the macro's `s_over_sqrt_b` on three
  archived points (gridphaseA01 1.69 -> 1.6922, foilspfbpz07R11_00 4.15 ->
  4.1507, foilspfbpz07R19_00 4.03 -> 4.0272).

## Cross-links
- Related: [contract-engine](/drivers/contract-engine.md) (the `anakit`
  adapter, `step_problems`, the `_ax` engine twins),
  [muse-backing-pattern](/external/muse-backing-pattern.md) (the backing
  mechanism `muse backing` uses, and the multi-repo work-area pattern this
  work area is an instance of), [mmackenz-workflow](/external/mmackenz-workflow.md)
  (the original EdepAna macro this fork's analyses are built from),
  [edepana-saw-events-scientific-notation-parse](/incidents/edepana-saw-events-scientific-notation-parse.md)
  (a sibling EdepAna precision gotcha in the old harvest's regex)
- Source files: `core/adapters/anakit.py`, `kits.toml[servers.anakit]`,
  `core/kit_registry.py` (`KitDecl("anakit", ...)`),
  `tests/test_anakit_kit.py`, `tests/fakeanakit.py`
- External: github.com/Mu2e/analysis-mcp (formerly
  github.com/michaelmackenzie/analysis-mcp-server); the checkout
  at `$AUTORESEARCH_ANAKIT`

## Open questions / TODO
- The sob `noise` 0.0021 is the old scale's 0.006 x 0.3474; re-measure it
  from replicates.
