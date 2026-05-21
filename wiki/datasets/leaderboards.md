# Leaderboards — TSV result history

**Type:** dataset
**Status:** active
**Updated:** 2026-05-15

## Summary
One TSV per BO driver, append-only, recording every evaluated configuration
along with the metrics and scalarized objective. Used both as the BO history
(re-fed to GP via `opt.tell` on next propose) and as the human-readable record.

## Key facts
- **`leaderboard.tsv`** — original 7D foil BO ([[bo-foil]])
- **`leaderboard_bo.tsv`** — refactored 7D BO history
- **`leaderboard_bo_michael.tsv`** — [[bo-michael]] history
  - Columns: `config tsda_rin tsda_halfLength4 holeRadius col5 sob calo alpha obj`
  - Created on first append; header is locked once written
- **Re-scalarization:** since both raw `sob` and `calo` are stored, you can
  recompute `obj` for any α post-hoc without re-running.

## Cross-links
- Consumed by: [[bo-michael]] (`load_history`), [[bo-foil]]
