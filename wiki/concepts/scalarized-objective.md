# Scalarized objective — `obj = S/√B − α·calo/POT`

**Type:** concept
**Status:** active
**Updated:** 2026-05-15

## Summary
[[bo-michael]] is a multi-objective problem (maximize Run1A CE S/√B, minimize
Run1B calo_stop_per_pot) collapsed to a single scalar so a stock GP-EI
optimizer can drive it. The weight α controls the trade-off rate: how many
units of S/√B we are willing to give up to halve the calo nuisance.

## Key facts
- **Definition:** `obj = sob − α · calo`, maximized.
- **α default:** `1.0e5` (CLI flag, can be swept)
- **Why 1e5:** mmackenz calo range is 4e-8 .. 2.5e-5; with α=1e5,
  a 1e-5 reduction in calo equals 1.0 unit of S/√B. This is the natural
  cross-over given observed scales.
- **GP convention:** `opt.tell` minimizes, so we feed it `-obj`.
- **Reported alongside obj:** raw `sob` and `calo` are always logged in the
  leaderboard so we can re-scalarize post-hoc with a different α.

## Cross-links
- Driver: [[autoresearch-bo-michael]]
- See also: [[bo-modes]] (which `sob` value the optimizer reads vs the report)
