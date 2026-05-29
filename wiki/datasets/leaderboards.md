# Leaderboards — TSV result history

**Type:** dataset
**Status:** active
**Updated:** 2026-05-27

## Summary
One TSV per BO driver, append-only, recording every evaluated configuration
along with the metrics and scalarized objective. Used both as the BO history
(re-fed to GP via `opt.tell` on next propose) and as the human-readable record.

## Key facts
- **`leaderboard.tsv`** — **REMOVED 2026-05-21** (original 1D thickness scan;
  only consumer was `autoresearch_loop.py`, also removed).
- **`leaderboard_bo.tsv`** — 7D foil BO history (kept). Sole readers are now
  `slides/analyze_bo.py` and the data-side
  `mmackenz_table_plots/overlay_bo_on_s_sqrt_b.py`; the producing driver
  `autoresearch_bo.py` was removed 2026-05-21.
- **`leaderboard_bo_helical.tsv`** — 5D helical history (kept).
  Rows contaminated by silent disc/plug sibling overlap; still consumed as
  legacy training data by `mmackenz_table_plots/gp_predict_helical.py`
  (HELICAL_LEGACY) and overlay scripts, with N_crit predicate filter applied.
  **2026-05-27 cleanup**: dropped 213→175 main rows (38 quarantined), and
  47→44 for the legacy 5D file (3 quarantined). See sidecar entries below.
- **`leaderboard_bo_helical_v2.tsv`** — current canonical helical leaderboard
  (4D Option-A coupling). Actively appended by [[graph-runner]] iterations.
- **`leaderboard_bo_helical_v2.broken.tsv`** + **`leaderboard_bo_helical.broken.tsv`**
  (created 2026-05-27, re-created after the 2026-05-21 deletion) — sidecar
  quarantine of all rows flagged by the [[scan-broken-codes-too-narrow]]
  full census (LikelyGeomOverlap > 100). 38 rows in the v2 sidecar
  (helicalL01–L05, helical037a/041a/050a/051a/052a, helicalH2, graph007–024,
  graph027, helicalNG02/05, helicalRA01–04, helicalPC01R00_02,
  helicalPC02R00_03/04, helicalPC03R01_00, helicalFT03R00_02,
  helicalQR00_02_noise, helicalTWB04_tess), 3 in the legacy sidecar
  (helical015, helical022, helical028). **Future loaders MUST NOT silently
  union these back into training**; the `_is_broken` gate in
  `gp_predict_helical.py:117` was already excluding them so the GP cloud is
  unchanged, but plot-overlay scripts that read the main TSV directly
  benefit from the cleanup.
- **Backup convention**: pre-cleanup snapshots at
  `<file>.tsv.bak.YYYYMMDD_HHMMSS` (2026-05-27 backups timestamped
  `20260527_121530`).
- **`leaderboard_bo_michael.tsv`** — [[bo-michael]] history
  - Columns: `config tsda_rin tsda_halfLength4 holeRadius col5 sob calo alpha obj`
  - Created on first append; header is locked once written
- **Re-scalarization:** since both raw `sob` and `calo` are stored, you can
  recompute `obj` for any α post-hoc without re-running.

## Cross-links
- Consumed by: [[bo-michael]] (`load_history`), [[bo-foil]],
  [[bo-helical]], [[graph-runner]]
