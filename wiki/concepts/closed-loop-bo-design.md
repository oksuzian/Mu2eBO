# Closed-loop BO design constraints

**Type:** concept
**Status:** active
**Updated:** 2026-05-21

## Summary
Load-bearing architectural constraints for `graph/closed_loop.py` (multi-round
batch BO runner that fans out q grid chains as subprocess children, waits at a
barrier, refits the GP, loops). These were surfaced by a 3-agent review of the
initial plan on 2026-05-21. Future sessions revising the closed-loop driver
must respect them; ignoring any one of them re-introduces a class of bug we
already paid to learn.

## Key facts

- **One SqliteSaver DB, q+1 writers.** `graph_data/checkpoints.sqlite` is
  opened by every `graph.run` invocation (each q child) AND by the outer
  closed-loop graph. SQLite's default journal mode locks the whole DB for
  writes, so concurrent checkpoint writes serialize and can time out. Fix:
  enable **WAL mode** on the connection (`PRAGMA journal_mode=WAL;`) once at
  startup. This is a per-DB persistent setting; safe to set in both
  `graph/run.py` and `graph/closed_loop.py`. Alternative (per-thread DBs)
  forfeits cross-thread checkpoint visibility we want for the barrier.

- **Leaderboard append (`autoresearch_bo_michael.py:150-156`) has no file
  lock.** Today it is safe only because `pipeline.py` submits are
  serialized by a coarse single-process pattern. Under closed-loop the q
  children all call `append_history` concurrently at harvest time. Fix:
  wrap the write in `fcntl.flock(LOCK_EX)` on a sibling `.lock` file
  (cross-platform-poor but adequate for Linux GPVM). Same fix applies to
  `append_pending` / `remove_pending` (`autoresearch_bo_michael.py:186-206`)
  — the latter does a read-write-truncate cycle that is *especially*
  unsafe across q writers.

- **Source of truth for the barrier is the SqliteSaver checkpoint, not the
  leaderboard TSV.** The leaderboard is a derived artifact written *at the
  end* of the inner graph's harvest node. Polling it for "is child N done?"
  introduces a window where the child has crashed mid-harvest (no row) vs
  is still running (no row) — indistinguishable. Polling the checkpoint
  (`SqliteSaver.list(config={"configurable":{"thread_id":<child>}})`) gives
  the actual node state and last-update timestamp. Fall back to TSV only
  as a sanity cross-check.

- **Config snapshot at submit-time generalizes the events-per-job stamp.**
  The same class of bug that produced [[events-per-job-mid-flight-edit]]
  applies to anything else the closed loop reads at multiple points in
  time. Recommended: at submit, hash the effective config dict
  (STAGES[stage] + relevant `graph/config.py` constants) and stamp the
  hash under `state/<stage>_config_sha.txt`. Harvest reads the stamp and
  warns if the *current* hash differs. Cheap insurance against future
  silent miscalculations of the same family.

- **Scan_logs gating must precede leaderboard inclusion.** Inner graph
  has a `scan_logs` node that detects `GeomSolids1001` /
  `tessellated-solid-facet-orientation` floods (see incident page). Today
  it logs and continues. For closed-loop, hits there mean the row is
  physics-broken (count saturated by stuck-track inflation) and must NOT
  feed the GP — else round N+1's picks chase a phantom Pareto frontier.
  Closed loop's `refit_and_check` should re-read the leaderboard with a
  scan_logs-clean filter, OR (better) the inner graph should refuse to
  append rows that failed the scan.

- **Deletion-test cost of the outer graph.** The outer round graph is a
  thin wrapper around a hand-coded for-loop. The depth-justifying
  benefit is **checkpoint-based resume across restarts** (kill parent →
  restart same `--thread-id` → barrier re-polls without re-launching
  children). Without that property, the LangGraph node structure is
  shallow and a plain `while round < max:` script is better. Implication:
  if WAL/locking issues force per-thread DBs, the outer graph loses its
  reason to exist and should collapse to a script.

- **q-parallel BO acquisition function quality.** With q=5 children all
  proposed from the same GP fit, the first-round picks share the same
  acquisition surface — they cluster unless the picker uses CL-mean / CL-min
  fantasy points (see [[batch-bo]]). The current
  `gp_predict_helical.compute_explore_picks` uses Pareto-evenly-spaced
  picks across sob-rank, which is a workable proxy but NOT a calibrated
  acquisition. Round 1 may produce 5 nearly-degenerate picks if the
  Pareto frontier is short. Mitigation: enforce a minimum L2 distance
  between picks in normalized space, OR migrate to skopt-native CL-min.

- **N_crit margin at HELICAL_NSTEPS=5000 was empirically too loose.**
  SR00_00 (`dx=0.011, dy=125, halflen=251, angle=167`, N_crit≈4144)
  reproduced the GeomSolids1001 + stuck-track flood the gate was
  supposed to prevent (90/100 mustops_ce jobs flagged; see
  [[bo-helical]] "N_crit margin too loose"). scan_logs gating worked
  end-to-end — broken.txt written, leaderboard append suppressed —
  but the closed loop wasted 6 h of grid CPU on a doomed pick because
  the propose-time guard accepted it. Lowered to **2000** in
  `HelicalMode.HELICAL_NSTEPS`; closed_loop must be invoked with
  matching `--nsteps-budget 2000` (the two are co-equal, drift re-opens
  the hole). Earlier framing of this incident as a separate "throughput
  gate" was a misread — at the broken corner, the per-job cost IS the
  brokenness, not a slow-but-correct simulation.

## Cross-links
- Related: [[batch-bo]], [[events-per-job-mid-flight-edit]],
  [[tessellated-solid-facet-orientation]],
  [[orchestrator-evaluation-2026-05]], [[bo-helical]]
- Source: `graph/run.py:51` (sqlite connect, no WAL today),
  `autoresearch_bo_michael.py:150-156` (append_history, no lock),
  `autoresearch_bo_michael.py:186-206` (pending TSV r-w-t cycle, no lock),
  `pipeline.py:325-333` (events-per-job stamp pattern to generalize)
- Plan: `~/.claude/plans/zazzy-booping-ladybug.md`

## Open questions / TODO
- Whether `compute_explore_picks` should grow a `--min-spacing` knob or
  the closed loop should post-filter picks. Choose before round 2.

## Resolved (2026-05-21)
- **WAL safety on the mount: OK.** `graph_data/` is on **CephFS**
  (`/exp/mu2e/app` resolves to ceph), not NFS — POSIX locking semantics
  apply. Smoke (5 concurrent writers × 5 inserts with 2s gap, 30s
  connection timeout): 25 writes, 0 lock errors, 11s wall. Aggressive
  test (4 writers × 50 inserts back-to-back, 5s timeout): one
  `OperationalError('database is locked')`. Closed-loop workload (q=5,
  ~10 checkpoints per child over 2h ≈ 0.01 writes/sec) is two orders
  below the failure regime. Adopt: explicit `PRAGMA journal_mode=WAL`
  + 30s SQLite timeout in `graph/run.py` and `graph/closed_loop.py`.
- **Driver shape: LangGraph outer graph (closed_loop.py) wins the
  deletion test.** WAL works → cross-thread checkpoint visibility
  preserved → barrier can re-poll via `SqliteSaver.list({thread_id})`
  after parent restart, justifying the LangGraph node structure.
