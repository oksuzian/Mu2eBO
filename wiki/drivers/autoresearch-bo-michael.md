# autoresearch_bo_michael.py — driver

**Type:** driver
**Status:** active
**Updated:** 2026-05-15

## Summary
Main driver for [[bo-michael]]. Implements the four-step BO loop as
subcommands, each independently runnable.

## Key facts
- **Path:** `autoresearch_bo_michael.py`
- **Subcommands:**
  - `show-priors --top K` — print top-K mmackenz priors by current α (no GP fit)
  - `propose <config_name>` — seed GP from priors+history, ask one candidate,
    render `bo_michael_proposals/<config_name>_geom.txt`
  - `evaluate <config_name> <summary.json>` — record completed run in
    `leaderboard_bo_michael.tsv` (see [[leaderboards]])
  - `preflight <config_name>` — see [[preflight]]
- **GP config:** `Optimizer(GP, EI, n_initial_points=0, random_state=42)`
- **α flag:** `--alpha 1e5` default ([[scalarized-objective]])
- **Search space:** see [[bo-michael]] / [[bo-helical]] (per mode)
- **Architecture:** `BOMode(ABC)` with two adapters (`MichaelMode`, `HelicalMode`).
  Each subclass owns its pinned constants + 7 mode-specific methods
  (`load_priors`, `build_space`, `_geom_text`, `parse_geom`, `format_row`,
  `load_history_row`, `print_top`). Shared concerns (history I/O, optimizer
  build, proposal write) are concrete on the base class. `MODES` is the
  registry argparse selects from. Adding a third mode = subclass + register.
- **Render template:** each mode's `_geom_text(x)` returns a FHiCL string;
  base-class `render_proposal(name, x)` writes it to `proposal_dir/`.

## Cross-links
- Project: [[bo-michael]]
- Priors: [[mmackenz-priors]]
- Helper: [[preflight]]
- Known render bug: [[geom-run1a-vs-run1b]]
