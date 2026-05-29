# closed-loop-runner — multi-round Pareto-pick BO driver

**Type:** driver
**Status:** active
**Updated:** 2026-05-25 (3rd PC02 bug — poll settled-counter — root-caused to pipeline.py:470 and fixed)

## Summary
Multi-round closed-loop runner that wraps q parallel
[[graph-runner]] children per round, refits the GP between rounds, and loops
until budget/convergence/operator stop. Replaces the prior operator-paced
loop (human computes 5 Pareto picks → launches 5 chains by hand → waits 2 h
→ refits → repeats) with a checkpointed LangGraph driver. Helical mode only
in this phase.

## Key facts
- **Code**: `graph/closed_loop.py` (one file, ~510 lines). Outer state:
  `RoundState` TypedDict (mode/alpha/q/round_idx/children/completed_names/
  pareto_hashes/converged/errors + knobs). Outer graph nodes:
  `renew_token → predict_picks → assign_names → launch_children → barrier →
  refit_and_check → decide_next`; `decide_next` either loops back to
  `renew_token` or ENDs. `renew_token` runs `kinit -R` + `source setupmu2e-art.sh && getToken`
  at the top of every round and **hard `sys.exit(2)` if `getToken` fails**
  (continuing past expiry just orphans clusters). Operator runs `kinit`,
  re-invokes with the same `--thread-id`; the outer checkpoint resumes
  from `renew_token`. See [[kerberos-mid-run-expiry]].
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
    [--alpha 1e5] [--nsteps-budget 2000] \
    [--stagger 90] [--barrier-poll-sec 300] [--barrier-timeout-min 240] \
    [--convergence-k 2] [--min-spacing 0.05] \
    [--pessimistic-calo] \
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
- **First-real-run (closed_helicalQ_r0, 2026-05-21) surfaced 3 bugs, all
  now patched in `graph/closed_loop.py`:**
  1. `CheckpointTuple` has no `.next` attribute (only `StateSnapshot`
     does). `node_barrier` now compiles `_build_graph()` against the
     shared SqliteSaver and calls `child_graph.get_state(cfg).next` per
     child thread_id.
  2. `main()` previously always passed `init` to `graph.stream()`, which
     re-seeded fresh state on restart and re-ran predict_picks →
     assign_names → launch_children, spawning duplicate `graph.run`
     children for the same configs. Fix: if a checkpoint exists for
     `thread_id`, pass `None` so LangGraph resumes from the last node.
  3. `node_launch_children` only skipped names whose record had a `pid`
     set. On crash-resume mid-launch this re-Popened siblings whose
     submission was already in flight (causing double cluster files /
     pending TSV pollution). Fix: skip names with any
     `<grid>/<name>/state/<stage>_cluster.txt`, a leaderboard row, or a
     `broken.txt`.
  These three failures all compound under the same pattern: **the inner
  child checkpoint and the outer parent checkpoint share the same
  sqlite DB but distinct thread_ids; the parent's "is this child done"
  signal must come from the child's StateSnapshot, not from the
  CheckpointTuple alone**.
- **2026-05-24: first `--max-rounds 2` real run** (`helicalFT05`) revealed
  a **barrier false-positive** in round 1, **now fixed**. Round 0 ran
  clean; round 1 children were declared "all 8 resolved" within ~minutes
  of launch because LangGraph's SqliteSaver returns an empty
  `StateSnapshot(next=(), values={}, step=-1)` for a thread_id with no
  checkpoint yet — indistinguishable from a terminal state by `.next`
  alone. Fix in `_child_terminal_via_checkpoint`: require
  `snap.next` empty AND `snap.values` non-empty AND `metadata.step >= 1`.
  See [[barrier-false-positive-round1]] for the resolution. The
  `--max-rounds 1` workaround in `/closed-loop-launch` is no longer
  strictly required but kept as a conservative default.
- **2026-05-24 (same day): second barrier false-positive on FT06**, also
  fixed. The snapshot-step gate was correct but masked a second compounding
  bug at `node_barrier` line 390: exit condition was
  `if len(completed) >= len(children)`. `completed` is preserved across
  rounds (intentional, so resumed runs don't re-check round-0 children),
  so on entry to round-1 barrier `completed` already had 8 round-0 names
  and `children` had 8 round-1 names → `8 >= 8` True on first tick →
  break before checking any round-1 child. Fix: replace count comparison
  with `if all(n in completed for n in children)`. See
  [[barrier-false-positive-round1]] for both bugs. **Until a clean
  `--max-rounds 2` real-run validates the combined fix, keep
  `/closed-loop-launch`'s `--rounds 1` default in place.**
- **2026-05-25 helicalPC02 (`--pessimistic-calo --max-rounds 2`) surfaced
  TWO new failures, both unfixed:**
  1. **Silent barrier timeout.** Round-0 barrier exited via
     "barrier: all 8 children resolved" log msg (good). Round-1 barrier
     exited at completed=9/16 (8 R00 carried over + 1 R01 leaderboard
     row) with NO log message. The `barrier_timeout_min` path in
     `node_barrier` returns silently — operator-visible state is
     indistinguishable from "all resolved" except by counting completed
     vs len(children). Add a "barrier: TIMEOUT at completed=X/Y" log
     before that return.
  2. **Orphan inner-runner hang between `run1b_mubeam` and `concat`.**
     `start_new_session=True` (Popen kwarg) means inner `graph.run`
     children survive parent death — adopted by init (PPID=1). After
     the silent timeout, 7/8 round-1 inner runners kept running for
     6+ hours, all stuck at the SAME inter-stage point:
     `run1b_mubeam_outputs.txt` present (timestamps 03:59–04:17), but
     `concat_cluster.txt` never appeared. Grid queue was empty, so
     they were not waiting on grid — they were spinning in the inner
     runner's polling loop. `R01_06` was the one that escaped and
     reached leaderboard. Root cause not yet known; needs a `py-spy
     dump` on a stuck pid. Practical effect: silently-orphaned children
     consume RAM/file-handles indefinitely and pollute the leaderboard
     with partial-round data (PC02 round-1 has 1 row, not 0 and not 8).
  **Operator implication:** treat `barrier_timeout_min` as a likely-hit
  bound, not a never-hit safety net. After a closed-loop "done", check
  `ps -ef | grep "graph.run.*<prefix>"` for orphans before declaring
  the run complete. Until #1 is fixed, the only way to tell timeout
  from clean exit is `completed` field in the final state.
- **2026-05-25 PC02 follow-up inspect: 3rd unfixed bug — concat
  convergence-poll never converges.** The "orphan runners hung 6+ h"
  were misdiagnosed: they are NOT hung waiting on grid. Per /proc
  forensics on a stuck PC02R01_00 inner runner:
  - Parent `graph.run` PID 2302141 was blocked in `wait4` on its
    child PID 2363885 = `pipeline.py --config <name> poll concat`.
  - Child sat in `hrtimer_nanosleep` (normal 2-min poll cycle).
  - `poll_concat_*.log` printed `queue:1/1 settled:0/1 (target=1)`
    every 2 min for 6+ hours unchanged.
  - But `jobsub_q` showed 0 jobs total AND `/pnfs/.../staged/concat/`
    contained 200 staged .art files.
  So the concat grid job(s) finished, outputs landed on /pnfs, queue
  drained — but the convergence-poll's "settled" counter never
  recognized them. The poll's settled-side reachability check
  (filename glob or jobsub-history query) is out of sync with what
  actually lands on /pnfs for the concat stage. This is the actual
  reason the parent saw `completed=9/16` at the barrier_timeout — 7
  of 8 round-1 children were spinning in this false-negative poll
  loop, not in a real grid wait. **Operator practical:** after a
  multi-hour `queue:N/N settled:0/M` pattern, cross-check
  `/pnfs/.../staged/<stage>/` directly; data may already be on disk.
  **Root cause + fix (2026-05-25):** `pipeline.py:470`
  `poll_cluster` settled = bare-form (`00000`) only; for this concat
  run the outstage held exactly one dir `00000.6d475c59` (hash-suffix)
  that never got renamed because the underlying art job died with the
  known xrootd `[3012] Pool unavailable` `FileOpenError` in PostEndJob
  (see [[concat-xrootd-fileopen-postendjob]]). **Key insight:**
  jobsub_lite only renames hash→bare on **zero-exit** jobs. A
  perma-hash dir means EITHER rename-in-flight OR FAILED-and-rename-
  skipped — counting hash as settled risks declaring success on a
  cluster where every job actually crashed. Fix in `poll_cluster`
  keeps `settled` = bare-form only (success-only semantics) but adds a
  failure-aware exit: when `in_queue == 0` AND all `njobs` dirs are
  present in either form AND `settled < target`, break with a WARN so
  `list_outputs` + harvest surface the failure loudly instead of the
  poll hanging forever. `list_outputs` (lines 502–513) already drains
  the genuine rename-in-flight tail (10-min cap), then globs bare-form
  — perma-hash dirs (failed jobs) end up missing from `*_outputs.txt`
  and harvest errors out on missing .art.

## Cross-links
- Related: [[graph-runner]], [[closed-loop-bo-design]], [[bo-helical]],
  [[batch-bo]], [[autoresearch-bo-michael]], [[scalarized-objective]],
  [[kerberos-mid-run-expiry]]
- Source files: `graph/closed_loop.py`,
  `graph/config.py` (CLOSED_LOOP_* constants),
  `/exp/mu2e/data/users/oksuzian/autoresearch_grid/mmackenz_table_plots/gp_predict_helical.py`
  (`compute_explore_picks` library entry point)
- Operator stop file: `graph_data/STOP_CLOSED_LOOP`
- Skills: `/closed-loop-launch [prefix] [--rounds N] [--q Q]` wraps the
  `nohup .venv-graph/bin/python -m graph.closed_loop …` recipe (auto-picks
  next free `helicalFT##` suffix); `/closed-loop-status [prefix]` reports
  parents alive + jobsub queue + parent-log tail + leaderboard top-5.
  Sources: `.claude/commands/closed-loop-launch.md`,
  `.claude/commands/closed-loop-status.md`.

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
- `renew_token` only fires at round boundaries (every 6-8 h). A single
  round's grid stages can still outlive the renewed ticket if a stage
  hangs near the 25 h krb5 limit; consider a sibling watchdog cron that
  `kinit -R`s every ~12 h independent of the closed loop. See
  [[kerberos-mid-run-expiry]].
