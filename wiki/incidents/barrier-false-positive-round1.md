# Barrier false-positive on round >= 1 (closed-loop)

**Type:** incident
**Status:** resolved
**Updated:** 2026-05-24 (second false-positive root-caused: barrier count-comparison bug, fixed `closed_loop.py:390`)

## Summary
First `--max-rounds 2` real closed-loop run (`helicalFT05`, q=8) silently
declared convergence after only round 0 contributed real leaderboard
rows. Round-1 children were marked "resolved" by the barrier within
minutes of launch, refit hashed the unchanged leaderboard, hash matched
round 0 → converged → parent exited cleanly. The 8 round-1 children
continued running on the grid for >30 min after parent exit, eventually
writing rows that nobody refits on. Looks like a clean multi-round run
in logs; isn't.

## Key facts
- **Smoking gun in `closed_helicalFT05_r0.log`:**
  ```
  [closed_loop] launched helicalFT05R01_07 pid=1330575 ...
  [closed_loop] barrier: all 8 children resolved      ← within minutes
  [closed_loop] {"round_idx": 1, "completed": 9, ...}
  trained on 66 points (10 priors + 56 helical = 0 legacy + 56 v2)
  [closed_loop] refit: pareto_hash=9169827253d5fd2f
      (last 2: ['9169827253d5fd2f','9169827253d5fd2f']) converged=True
  [closed_loop] done.
  ```
  The two `9169827253d5fd2f` hashes are identical because round 1
  contributed ZERO new leaderboard rows when refit ran (round 0 only
  added 7 of 8 by then; round-1 children hadn't even hit mubeam harvest).
- **Children state at parent exit:** all 8 `helicalFT05R01_*` had
  `[run] {"config_name": ..., "preflight": "pass"|"pending",
  "objective": null}` and `ps` showed live python processes with 2–13 min
  ELAPSED — clearly mid-pipeline, not terminal.
- **Suspected mechanism:** `node_barrier` resolves a child if ANY of
  (a) leaderboard row, (b) `broken.txt`, (c)
  `saver.get_tuple(child_thread_id).next` is empty (per
  [[closed-loop-runner]]). For freshly-spawned round-1 children whose
  SqliteSaver checkpoint hasn't yet been written (or is read while a
  preflight-only checkpoint exists), `.next` likely evaluates to empty
  and the child is mis-classified as terminal.
- **`convergence_k=2` default makes the bug invisible:** two identical
  hashes in a row trigger convergence, so the spurious round-1 hash
  collapsing onto round-0's looks like the BO genuinely settled. With
  `convergence_k>=3` the parent would have looped one more round and
  exposed the issue. Don't trust `converged=True` from any 2-round run.
- **Workaround**: use `--max-rounds 1` and re-launch manually; or set
  `--convergence-k 99` and bound rounds. Skill
  `/closed-loop-launch` defaults to `--rounds 1` to avoid this.

## Cross-links
- Source files: `graph/closed_loop.py` (node_barrier + refit_and_check),
  `graph/config.py` (CLOSED_LOOP_BARRIER_* constants)
- Related: [[closed-loop-runner]], [[closed-loop-bo-design]]
- Log: `graph_data/closed_loop_logs/closed_helicalFT05_r0.log`
- Affected children: `helicalFT05R01_00` through `helicalFT05R01_07`

## Resolution (2026-05-24)
Fixed in `graph/closed_loop.py:_child_terminal_via_checkpoint`. Root
cause: LangGraph's SqliteSaver returns
`StateSnapshot(next=(), values={}, metadata={'step': -1})` for a
thread_id that has never written a checkpoint. This is INDISTINGUISHABLE
from a genuine terminal state by `snap.next` alone, so freshly-spawned
round-N children (whose subprocess hadn't yet flushed any state) were
mis-classified as terminal on the very first barrier tick.

**Fix:** require ALL THREE of (a) `snap.next` empty, (b) `snap.values`
non-empty, AND (c) `snap.metadata.step >= 1`. Verified by smoke test
against the FT05 checkpoint DB: ghost thread → `terminal=False`; R00_*
and R01_* (now legitimately complete) → `terminal=True`; preflight-fail
path preserved because even a 2-super-step run satisfies `step >= 1`.

**Why `step >= 1` and not `>= 2`:** a preflight-fail child runs
`propose → render_preflight → END` via `route_after_preflight`. That's
two super-steps; LangGraph's step counter is 0-indexed, so the END
checkpoint records `step=1`. The threshold is the floor for "at least
one super-step executed."

**Live validation (2026-05-24, `helicalFT06`, q=8, max-rounds=2):**
round 0 closed with 8/8 real leaderboard rows and a non-degenerate
pareto_hash (`39d6c72a54ce5f80`); round 1 then launched fresh children
without any spurious "all resolved" barrier tick. End-to-end confirms
the smoke-test fix holds against an actual multi-round closed loop.

## Second false-positive (2026-05-24, same FT06 run) — distinct bug, fixed

The snapshot-step fix above was correct but only one of TWO compounding
bugs. FT06 round 1 still mis-resolved immediately after launching all
8 children, even though every R01_* child was mid-pipeline.

**Root cause:** `node_barrier` exit condition was
`if len(completed) >= len(children)`. `completed` is initialized from
`state.get("completed_names", [])`, which is PRESERVED across rounds
(intentional: a crashed-and-resumed parent should not re-check
round-0 children). Entering round 1, `completed` already contained
the 8 round-0 names. `state["children"]` is the round-1 list (8
names). `len(completed) >= len(children)` evaluated `8 >= 8 = True`
on the FIRST barrier tick → break before checking any R01_* child.

**Fix (`graph/closed_loop.py:390`):** replace count comparison with
`if all(n in completed for n in children)`. Count-based exit
conflates cumulative completion across rounds with current-round
completion.

**Observable smoking gun in the parent log:** `completed` went from
8 → 9 across the (instant) barrier — one round-1 child got added
(probably via a leaderboard or broken-marker race during the tick),
but the loop exited on count before checking the remaining 7. A
clean barrier on q=8 would show `completed: 16` at minimum (round-0
+ round-1 union); FT06 showed `completed: 9` at refit time.

**Why this didn't surface in FT05:** FT05 had the snapshot-step bug
masking it — the snapshot path resolved children before the count
check mattered. Once snapshot was patched, the count bug surfaced
nakedly on the next multi-round run.

## Open questions / TODO
- After fix, replay FT05R01 children's pareto contribution by harvesting
  their rows and re-running the GP refit offline (the children DID
  complete normally — they just landed after parent had already exited).
- Consider `convergence_k` floor of 3 to require evidence of true plateau
  (defensive depth even though the underlying bug is now fixed).
