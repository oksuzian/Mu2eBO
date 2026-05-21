# Leaderboards — TSV result history

**Type:** dataset
**Status:** active
**Updated:** 2026-05-21

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
- **`leaderboard_bo_helical.broken.tsv`** — **REMOVED 2026-05-21**
  (explicitly quarantined snapshot from the pre-fix calo-constant era; no
  consumer; preserved in git history if needed).
- **`leaderboard_bo_helical.tsv`** — 5D helical history (kept).
  Rows contaminated by silent disc/plug sibling overlap; still consumed as
  legacy training data by `mmackenz_table_plots/gp_predict_helical.py`
  (HELICAL_LEGACY) and overlay scripts, with N_crit predicate filter applied.
- **`leaderboard_bo_helical_v2.tsv`** — current canonical helical leaderboard
  (4D Option-A coupling). Actively appended by [[graph-runner]] iterations.
- **`leaderboard_bo_michael.tsv`** — [[bo-michael]] history
  - Columns: `config tsda_rin tsda_halfLength4 holeRadius col5 sob calo alpha obj`
  - Created on first append; header is locked once written
- **Re-scalarization:** since both raw `sob` and `calo` are stored, you can
  recompute `obj` for any α post-hoc without re-running.

## Cross-links
- Consumed by: [[bo-michael]] (`load_history`), [[bo-foil]],
  [[bo-helical]], [[graph-runner]]
