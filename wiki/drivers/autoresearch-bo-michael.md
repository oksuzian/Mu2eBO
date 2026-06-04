# autoresearch_bo_michael.py — driver

**Type:** driver
**Status:** active
**Updated:** 2026-06-04

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
  registry argparse selects from.
- **Adding a closed-loop-capable mode touches 7 places — 8 if you ever run it
  with `--picker qnehvi` (checklist, 2026-06-03 from `foilsf`/v3; item 8 added
  2026-06-04):** "subclass + register" is NOT enough — a propose-only
  mode is, but a closed-loop one also needs the graph + picker wiring:
  1. subclass (e.g. `FoilsFracMode(FoilsMode)` — reuse via `super()`) +
     `MODES["<name>"] = ...` in `autoresearch_bo_michael.py`;
  2. the **3 surface-check gates** `if mode.name in ("helical","foils",…)` in
     `cmd_preflight` (~`:1048,:1114,:1148`) — MISS these and preflight skips
     managed-overlap detection for the mode;
  3. `graph/state.py` mode `Literal`;
  4. `graph/closed_loop.py:_import_gp` `elif mode=="<name>": import
     gp_predict_<name>`;
  5. `graph/closed_loop.py` `--mode` argparse `choices=[…]` (graph/run.py has
     NO choices restriction, so children are fine);
  6. `graph/closed_loop.py:_DRY_RUN_KNOB_LABELS` (optional — falls back to
     `x{i}`, no crash);
  7. the off-repo picker shim `gp_predict_<name>.py` in
     [[mmackenz-table-plots-dir]] (binds `MODES["<name>"]`, delegates to
     `build_space` so it auto-tracks the dims).
  8. **qnehvi ONLY:** add the mode to `botorch_predict.py`'s **inlined
     `MODE_SPECS` dict** (`botorch_predict.py:62`) — `{lo,hi,int_dims}` lists.
     This is a SECOND, hand-maintained copy of the bounds, deliberately
     duplicated so `.venv-botorch` (no skopt) needn't import `build_space`;
     order MUST match `build_space`. Items 1–7 (the cl_min/skopt path) are NOT
     enough for qnehvi: `--picker qnehvi` shells into `.venv-botorch` to run
     `botorch_predict.py --mode <name>`, which `raise SystemExit`s at
     `botorch_predict.py:85` "mode not supported" if the mode is absent from
     `MODE_SPECS`. Caught 2026-06-04 launching `foilsZ02` (foilsf+qnehvi) —
     `foilsf` was in `bo.MODES` and all 7 cl_min places but missing here, so
     qnehvi would have died on arrival every round. `foilsf` spec = `foils`
     spec with the last two dims `f∈[0,0.95]` instead of `rIn∈[0,50]`.
- **Render template:** each mode's `_geom_text(x)` returns a FHiCL string;
  base-class `render_proposal(name, x)` writes it to `proposal_dir/`.

## Cross-links
- Projects: [[bo-michael]], [[bo-helical]], [[bo-foils]] (modes registered in `MODES`)
- Predecessor driver: [[autoresearch-bo]]
- Priors: [[mmackenz-priors]]
- Helper: [[preflight]]
- Consumed by: [[pipeline]], [[graph-runner]], [[closed-loop-runner]]
- Regression tests: [[tests]]
- Known render bug: [[geom-run1a-vs-run1b]]
