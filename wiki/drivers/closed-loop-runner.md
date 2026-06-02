# closed-loop-runner — multi-round Pareto-pick BO driver

**Type:** driver
**Status:** active
**Updated:** 2026-06-01 (extending a completed campaign needs a fresh --name-prefix: resume ignores new --max-rounds, prefix reuse trips the zero-row gate)

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
  decide_next`; `decide_next` either loops back to `renew_token` or ENDs.
  (`refit_and_check` was deleted 2026-05-29 along with convergence-by-hash;
  `predict_picks` snapshots `history_len_before` and `decide_next` checks
  for zero new rows.) `renew_token` runs `kinit -R` + `source setupmu2e-art.sh && getToken`
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
- **Extending a COMPLETED campaign needs a FRESH `--name-prefix`, not a
  resume (2026-06-01, foilsY01→foilsY02).** A run that exited via
  `max_rounds` is a closed thread and CANNOT be given more rounds two ways
  that both look plausible and both fail:
  1. **Reuse the same `--thread-id` with a higher `--max-rounds`** → no-op.
     `main()` resume path passes `None` (not init state) when a checkpoint
     exists, so the new `--max-rounds` never enters state — the graph reloads
     its terminal checkpoint (already routed to END at `round_idx>=max_rounds`)
     and does nothing.
  2. **Reuse the same `--name-prefix` with a fresh `--thread-id`** → SILENT
     dead-on-arrival. A fresh thread restarts at `round_idx=0`, regenerating
     `{prefix}R00_{j}` names that are already in the leaderboard;
     `assign_names` marks them completed, `launch_children` skips all q, the
     barrier resolves with 0 children, and the zero-row safety gate ENDs
     immediately (same shape as [[foilsx04-all-preflight-ambiguous]]).
  **Correct continuation:** a new prefix (e.g. `foilsY01`→`foilsY02`). The new
  campaign seeds from prior rows via `load_history` (+ `load_priors`), so the
  GP starts informed — verified by `history_len_before=3` picking up
  foilsY01's 3 rows at foilsY02 round 0. New rows still append to the same
  per-mode leaderboard.
- **Convergence (deleted 2026-05-29)**: previously hashed the rounded
  (2 sig-fig) `q` GP picks and called the run converged when the last
  k hashes were identical. **Deleted entirely** after 15-run production
  audit: 0 demonstrated true saves (FT05/FT06 r0→1 collisions were both
  `--max-rounds 2` runs that would have exited at the same point), and
  1 documented false-positive (foilsX04 zero-row case — identical data
  → byte-identical fit → guaranteed collision). Replaced with a
  zero-row safety break in `node_decide_next`: `predict_picks` snapshots
  `len(load_history())` into state; `decide_next` compares against
  post-barrier length and ENDs if `new_rows <= 0`. `--max-rounds` is the
  budget cap; saturation is now diagnosed post-hoc from the leaderboard
  (Pareto-front movement plots, not a runtime flag).
  Historical notes on the old machinery (kept for context if it's ever
  reconsidered):
  - **2-sig vs 3-sig empirics (2026-05-29 agentic investigation)**: only
    3 hash collisions exist across 15 production parent logs ever —
    foilsX04 r0→1 (spurious, zero rows), helicalFT05 r0→1, helicalFT06
    r0→1 (both real saturation with +8 rows). On real FoilsMode
    progressions (X02/X03), 55–70% of q×D acquisition-argmax coords
    jitter *beyond even the 2-sig bin* between consecutive rounds with
    +6 to +10 new leaderboard rows; the 3rd-sig-fig coord-jitter rate
    is nearly identical (99/160 vs 101/160). Picks come from a fixed
    seed=42 Sobol pool of 2^20 points; the GP refit is the only
    round-to-round mover, and one new row routinely shifts the
    Pareto-knee argmax by several grid cells (cf. bo-helical n=86→87
    10× calo-cloud collapse). **Switching to 3-sig-fig** (one-line
    change at `closed_loop.py:206`: `mult = 10**(exp-1)` →
    `10**(exp-2)`) **would convert FT05/FT06-style real saturations
    into non-events** — organic 3-sig collision is ~10^(q·D)
    suppressed vs 2-sig. Correct fix for the foilsX04 false-positive
    is the orthogonal zero-new-rows gate in `node_refit_and_check`,
    not tightening the bin.
  - **Wide-range pathology** (the failure mode that *is* sig-fig
    relevant): `_pareto_hash` rounding is scale-relative to the VALUE,
    not to the search range — `rOut=184` has bin width 10 whether the
    BO range is `[80, 250]` or `[180, 200]`. So a too-wide range
    doesn't coarsen the hash at the optimum; instead it keeps the GP
    exploring across the full envelope so consecutive-round picks
    jitter in absolute terms big enough to cross 2-sig bins → hash
    never collides → real local saturation looks "still moving."
    Tightening sig-fig makes this worse. Principled fix is to replace
    hash-equality with **per-knob normalized-L2 distance** between
    consecutive pick-sets (e.g., all q picks within 5% of normalized
    range), which decouples from both knob magnitude and search-range
    width.
  - **Mechanism may not be earning its keep at all (2026-05-29)**:
    the 2 "legitimate" 2-sig convergence events (FT05, FT06) were both
    `--max-rounds 2` runs that would have exited at the same point
    regardless of the flag. **No production run has ever exited via
    convergence at round ≥ 2.** So the demonstrated record is: 0 true
    saves, 1 false positive (foilsX04), and no evidence the hash
    correlates with real saturation vs. "GP happened to re-propose
    adjacent Sobol cells." Strong case for either deleting the
    convergence machinery and relying on `--max-rounds`, or replacing
    with normalized-L2-distance gate. The foilsX04 zero-row fix is
    still required either way — it's about not advancing a counter on
    a degenerate round, independent of what the counter means.
- **q-pick spacing** (`[[closed-loop-bo-design]]` revision #7): even-spaced
  ranks along a short Pareto frontier yield near-degenerate picks.
  `gp_predict_helical.compute_explore_picks` is *supposed* to enforce a
  normalized-L2 ≥ `min_spacing` gate (default 0.05) and fall back to fewer
  than q picks if the frontier is too clustered. Future migration to
  skopt-native CL-min (`[[batch-bo]]`) is the cleaner long-term fix.
  - **2026-05-29 simplify-audit fixed**: `compute_explore_picks`
    (gp_predict_helical.py:347) had `min_spacing` declared in the
    signature but the call to `_select_picks(par_idx, s['Xd_all'], q,
    0.02)` hardcoded 0.02 — every closed-loop round prior to this fix
    used 0.02 regardless of `--min-spacing` or
    `CLOSED_LOOP_MIN_PICK_SPACING`. Fix: pass `min_spacing` through.
    Past leaderboard rounds are tighter-clustered than their
    `--min-spacing` setting suggests.
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

- **2026-05-31 foilsX08 (`--picker qnehvi --max-rounds 5`) first-launch
  crashed on `subprocess.TimeoutExpired` at `closed_loop.py:293`
  `_qnehvi_picks_subprocess`.** The hard-coded 600s timeout is too tight
  for the BoTorch qNEHVI subprocess pick-time at large n. n=204 foils
  leaderboard exceeded 600s; the overlay benchmark at the same n took
  ~90 min for q=10 picks. Bumped to **3600s** (1 h). qNEHVI runtime is
  super-linear in n; expect further bumps as the leaderboard grows past
  ~300. The `picks subprocess timed out` error surfaces as a Python
  Traceback in the parent log (NOT a LangGraph node error) and the
  parent dies before any child launches → no leaderboard rows added
  for the round, no barrier reached. Validate any future qnehvi launch
  by tail-watching for `launched <prefix>R00_00` rather than absence
  of error within 5 min.

## Cross-links
- Related: [[graph-runner]], [[closed-loop-bo-design]], [[bo-helical]],
  [[batch-bo]], [[autoresearch-bo-michael]], [[scalarized-objective]],
  [[kerberos-mid-run-expiry]]
- Regression tests: [[tests]]
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

## Saturation FoM (post-hoc, not runtime — 2026-05-29)
- Because `obj = sob - α·calo` is already scalarized, full MOBO HV/EHVI
  machinery is overkill. Recommended post-hoc FoM: **best-scalar regret
  plateau** — per round compute `Δbest = max(obj_round) -
  max(obj_all_prior)`; declare saturated when `Δbest ≤ ε ·
  (max(obj_round1) - max(obj_round0))` for the last k=2 rounds (ε=0.05).
  Pair with **Pareto-set Jaccard turnover** as a secondary check to
  catch "stuck in one Pareto region" that pure best-obj misses.
- This is what convergence-by-pareto-hash was trying to be, but
  anchored on **leaderboard outcomes** (rows that actually landed)
  not GP-proposed coords (which jitter across Sobol cells even at
  saturation — see the 2026-05-29 audit above).
- Numbers in `[[bo-helical]]` ("HV +1.6% / hit-rate 62%→38%") come from
  one-off `/tmp/pareto_saturation.py` (W=20 window, 2D HV via
  axis-aligned rectangle stacking). Promoted 2026-05-29 to
  `autoresearch_grid/mmackenz_table_plots/saturation_report.py`
  (~220 LOC); reads any leaderboard, parses `<prefix>R##_##` to derive
  rounds (rows without that pattern lumped as "seed"), emits 4-panel
  PNG (HV / PF-size / rolling hit-rate / per-round Δbest bars +
  ε·anchor threshold line) + console verdict.
  **Run with `.venv-botorch/bin/python`** (matplotlib); `.venv-graph`
  has no matplotlib. Optional `--prefix foilsX05` to isolate one BO
  campaign from prior history in the same leaderboard. Validated
  2026-05-29: bo-helical-v2 fires SATURATED at R02 (hit-rate 70%→15%,
  Δbest=-1.02 vs ε·anchor=0.0042); bo-foils-v1 stays not-saturated
  through R04 (hit-rate 55%→50%, Δbest monotone +0.058 to +0.161).
  Closed-loop runtime auto-stop NOT recommended — that's what the
  deleted machinery already attempted and the 15-run audit showed
  wasn't earning its keep.
- **Rolling hit-rate is non-monotone — Δbest is the real verdict
  (2026-05-31, foilsX08).** The W=20 hit-rate (fraction of new evals
  that extend HV in the last 20) can REBOUND late in a saturated run
  if a diverse-picker batch lands and most of its q points scatter to
  fresh corners of the (sob, -calo) frontier without exceeding the
  obj-best ceiling. Concrete: foilsX08 R00 (qNEHVI, q=10) flipped tail
  hit-rate 55%→0% (post-X07 R06, slide 14 hand-authored) back up to
  **65%** while Δbest stayed negative for 8 consecutive rounds (R02–R09)
  and VERDICT remained SATURATED. The diversity-overlay finding (qNEHVI
  scatters into corners, [[batch-bo]]) is the *cause*, not a
  contradiction. **Trust per-round Δbest plateau for the SAT verdict;
  treat the rolling hit-rate as a diversity indicator, not a saturation
  indicator.** Hand-authored hit-rate numbers in slide decks decay
  invisibly — auto-stamp them or drop them.

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
