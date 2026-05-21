# closed-loop-runner — multi-round Pareto-pick BO driver

**Type:** driver
**Status:** active
**Updated:** 2026-05-21

## Summary
Multi-round closed-loop runner that wraps q parallel
[[graph-runner]] children per round, refits the GP between rounds, and loops
until budget/convergence/operator stop. Replaces the prior operator-paced
loop (human computes 5 Pareto picks → launches 5 chains by hand → waits 2 h
→ refits → repeats) with a checkpointed LangGraph driver. Helical mode only
in this phase.

## Key facts
- **Code**: `graph/closed_loop.py` (one file, ~470 lines). Outer state:
  `RoundState` TypedDict (mode/alpha/q/round_idx/children/completed_names/
  pareto_hashes/converged/errors + knobs). Outer graph nodes:
  `predict_picks → assign_names → launch_children → barrier →
  refit_and_check → decide_next`; `decide_next` either loops back to
  `predict_picks` or ENDs.
- **Children are subprocesses, not LangGraph `Send()` branches.** Each pick
  becomes `python -m graph.run --thread-id <name> --config-name <name>
  --x-point dx,dy,hl,ang --no-mock --mode <mode>` via
  `subprocess.Popen(..., start_new_session=True)`. Subprocess isolation
  means a child OOM/kill doesn't touch siblings or the parent; restart of
  the parent doesn't re-launch in-flight children (barrier just re-polls).
- **Barrier polls the SqliteSaver checkpoint, NOT the leaderboard TSV.**
  Per `[[closed-loop-bo-design]]` revision #3: the TSV is a derived
  end-of-harvest artifact, so using it as the barrier source-of-truth
  conflates "child crashed mid-harvest" with "child still running." A child
  is treated as resolved when ANY of: (a) its leaderboard row appears, (b)
  `<grid>/<name>/state/broken.txt` exists, (c) `saver.get_tuple(...).next`
  is empty (terminal checkpoint). Leaderboard read goes through
  `bo.MODES[mode].load_history()` which acquires the `flock` lock added in
  task #90.
- **CLI**:
  ```
  python -m graph.closed_loop \
    --mode helical --q 5 --max-rounds 10 --name-prefix helical \
    [--alpha 1e5] [--nsteps-budget 5000] \
    [--stagger 90] [--barrier-poll-sec 300] [--barrier-timeout-min 240] \
    [--convergence-k 2] [--min-spacing 0.05] \
    [--thread-id auto] [--dry-run]
  ```
  Child names are derived as `{prefix}R{round:02d}_{j:02d}` — the `R` is
  the round marker, not part of the prefix. Default prefix `helical` →
  `helicalR00_00 … helicalR00_04` for the first round of q=5.
- **Stop semantics**:
  - **Clean stop**: `touch
    /exp/mu2e/app/users/oksuzian/autoresearch/graph_data/STOP_CLOSED_LOOP`.
    Both `barrier` and `decide_next` poll this flag. In-flight children
    continue to completion (subprocess isolation); the parent exits at the
    next barrier poll or round boundary.
  - **Hard kill**: `kill <parent_pid>`. Children continue. Restart with the
    same `--thread-id` resumes from the last round checkpoint;
    `assign_names` treats names already in leaderboard or with broken.txt
    as completed, so `launch_children` skips them.
  - **Force-restart a round**: delete the round's leaderboard rows and
    re-invoke with the same thread-id.
- **Convergence**: hashes the rounded (2 sig-fig) `(sob, calo)` tuples of
  the Pareto frontier each round; flags `converged=True` when the last
  `convergence_k` hashes (default 2) are identical. Sensitive to numerical
  jitter — rounding is required, see `_pareto_hash`.
- **q-pick spacing** (`[[closed-loop-bo-design]]` revision #7): even-spaced
  ranks along a short Pareto frontier yield near-degenerate picks.
  `gp_predict_helical.compute_explore_picks` enforces a normalized-L2 ≥
  `min_spacing` gate (default 0.05) and falls back to fewer than q picks if
  the frontier is too clustered. Future migration to skopt-native CL-min
  (`[[batch-bo]]`) is the cleaner long-term fix.
- **WAL gate** (`[[closed-loop-bo-design]]` revision #1, #6): the outer
  graph and q children all write to the same
  `graph_data/checkpoints.sqlite`. WAL is set explicitly in both
  `graph/run.py` and `graph/closed_loop.py` after every connect. Verified
  PASS on CephFS for realistic-rate workloads (5 writers × 5 inserts × 2s
  gap with 30s timeout, 0 errors); aggressive rates (4 writers × 50
  back-to-back inserts) did hit one timeout — that case is not expected in
  production but should be remembered.
- **Closed-loop logs**: per-child stdout/stderr lands at
  `graph_data/closed_loop_logs/<name>.log`. The outer parent's own stream
  goes to whatever stdout the operator gave it (typically `nohup … &` or a
  cron tail).

## Cross-links
- Related: [[graph-runner]], [[closed-loop-bo-design]], [[bo-helical]],
  [[batch-bo]], [[autoresearch-bo-michael]], [[scalarized-objective]]
- Source files: `graph/closed_loop.py`,
  `graph/config.py` (CLOSED_LOOP_* constants),
  `/exp/mu2e/data/users/oksuzian/autoresearch_grid/mmackenz_table_plots/gp_predict_helical.py`
  (`compute_explore_picks` library entry point)
- Operator stop file: `graph_data/STOP_CLOSED_LOOP`

## Open questions / TODO
- Barrier timeout default (240 min) may be tight if a grid stage hangs;
  configurable but should be revisited after the first multi-round real
  run.
- Convergence by Pareto-hash equality is sensitive to numerical jitter;
  may need to switch to a Hausdorff/L2 metric if it never triggers.
- michael-mode closed loop is out of scope for this phase. Same pattern
  applies once a `compute_explore_picks` equivalent exists for michael.
- Studio observability for the outer graph's checkpoints (Studio only
  attaches to the dev server's in-memory store, not headless SqliteSaver).
