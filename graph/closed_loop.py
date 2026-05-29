"""Multi-round closed-loop batch BO runner.

Each round:
  0. renew_token — `kinit -R` + sourced `setupmu2e-art.sh && getToken` to refresh krb5 +
                   bearer before launching children. Best-effort (errors
                   logged, not fatal). See wiki/incidents/kerberos-mid-run-expiry.
  1. predict_picks — refit GP on current leaderboard, return q Pareto picks.
  2. assign_names  — derive {prefix}R{NN}_{j} names; skip names already done.
  3. launch_children — Popen `graph.run --config-name … --x-point …` per pick,
                       staggered by CLOSED_LOOP_STAGGER_SEC. Children detach
                       (start_new_session=True) so killing this parent does
                       not propagate.
  4. barrier — poll each child's SqliteSaver checkpoint (NOT the leaderboard
               TSV, which is a derived end-of-harvest artifact) until terminal
               or timeout; cross-check leaderboard for sanity. If the round
               produced 0 new leaderboard rows, set zero_rows=True so
               decide_next can exit early (all children failed → continuing
               just wastes more rounds re-proposing on the same fit).
  5. decide_next — loop unless max_rounds / zero_rows / STOP_FLAG.

Convergence-by-Pareto-hash was deleted 2026-05-29 after 15 production runs
showed 0 true saves (FT05/FT06 r0→1 were both --max-rounds 2 and would have
exited anyway) and 1 false positive (foilsX04 zero-row case). Saturation is
now diagnosed post-hoc from the leaderboard. The zero-row break is the
orthogonal safety check (catches all-children-failed rounds early).

The outer graph is itself checkpointed in `checkpoints.sqlite`; killing this
parent and re-invoking with the same --thread-id resumes the current round.
assign_names treats names already present in the leaderboard (or with
state/broken.txt) as completed → barrier re-polls without re-launching.

See wiki/concepts/closed-loop-bo-design.md for the load-bearing constraints
(SqliteSaver WAL, TSV file locking, barrier source-of-truth, config-SHA
stamping, scan_logs gating, q-pick spacing).
"""
from __future__ import annotations

import argparse
import json
import os
import sqlite3
import subprocess
import sys
import time
import uuid
from pathlib import Path
from typing import Dict, List, Optional, Tuple

sys.path.insert(0, str(Path(__file__).parent))

from dotenv import load_dotenv  # noqa: E402
load_dotenv(Path(__file__).resolve().parent.parent / ".env")

from langgraph.checkpoint.sqlite import SqliteSaver  # noqa: E402
from langgraph.graph import END, StateGraph  # noqa: E402
from typing_extensions import TypedDict  # noqa: E402

from config import (  # noqa: E402
    CHECKPOINT_DB,
    CLOSED_LOOP_BARRIER_POLL_SEC,
    CLOSED_LOOP_BARRIER_TIMEOUT_MIN,
    CLOSED_LOOP_MAX_ROUNDS,
    CLOSED_LOOP_MIN_PICK_SPACING,
    CLOSED_LOOP_Q,
    CLOSED_LOOP_STAGGER_SEC,
    DEFAULT_ALPHA,
    DEFAULT_MODE,
    GRAPH_DATA,
    GRID_DATA_ROOT,
    NSTEPS_BUDGET,
    PROJECT_ROOT,
    SQLITE_TIMEOUT_S,
    STOP_FLAG,
)

# gp_predict_helical lives in the sub-repo (sister of leaderboard). Import
# lazily so the module imports cleanly even when sub-repo is absent (e.g.,
# unit tests on a thin checkout).
GP_SCRIPT_DIR = Path("/exp/mu2e/data/users/oksuzian/autoresearch_grid/mmackenz_table_plots")


# ============================================================================
# Outer state schema
# ============================================================================

class ChildRecord(TypedDict, total=False):
    pid: Optional[int]
    log: str
    x_point: List[float]
    started_at: float


class RoundState(TypedDict, total=False):
    mode: str
    alpha: float
    q: int
    nsteps_budget: int
    max_rounds: int
    round_idx: int
    name_prefix: str
    children: Dict[str, ChildRecord]
    completed_names: List[str]
    history_len_before: int
    zero_rows: bool
    errors: List[str]
    stagger_sec: int
    barrier_poll_sec: int
    barrier_timeout_min: int
    min_spacing: float
    pessimistic_calo: bool


# ============================================================================
# Helpers
# ============================================================================

def _import_gp(mode: str = "helical"):
    """Import the mode-specific GP picker from the sub-repo (path-injected).

    Both pickers expose compute_explore_picks(q, nsteps_budget, min_spacing,
    pessimistic_calo); foils ignores nsteps_budget/min_spacing/pessimistic_calo
    (skopt-EI shim, 5D Integer+Real space).
    """
    if str(GP_SCRIPT_DIR) not in sys.path:
        sys.path.insert(0, str(GP_SCRIPT_DIR))
    if mode == "helical":
        import gp_predict_helical as gp  # noqa: WPS433
    elif mode == "foils":
        import gp_predict_foils as gp  # noqa: WPS433
    else:
        raise ValueError(f"_import_gp: no GP picker registered for mode={mode!r}")
    return gp


def _stop_requested() -> bool:
    return STOP_FLAG.exists()


def _open_saver_conn() -> sqlite3.Connection:
    """Open the shared checkpoints.sqlite with WAL + bumped timeout."""
    conn = sqlite3.connect(
        str(CHECKPOINT_DB),
        check_same_thread=False,
        timeout=SQLITE_TIMEOUT_S,
    )
    conn.execute("PRAGMA journal_mode=WAL;")
    return conn


def _child_state_dir(name: str) -> Path:
    return GRID_DATA_ROOT / name / "state"


def _child_is_broken(name: str) -> bool:
    return (_child_state_dir(name) / "broken.txt").exists()


def _child_in_leaderboard(name: str, mode: str) -> bool:
    """Read leaderboard via the BO driver (which already flocks)."""
    sys.path.insert(0, str(PROJECT_ROOT))
    import autoresearch_bo_michael as bo  # noqa: WPS433
    m = bo.MODES[mode]
    return any(p.cfg == name for p in m.load_history())


def _child_terminal_via_checkpoint(name: str, child_graph) -> bool:
    """True if the child's compiled graph reports no remaining work.

    `CheckpointTuple` does not expose `next`; only `StateSnapshot` (returned
    by `compiled_graph.get_state(cfg)`) does. We compile the inner graph
    once in `node_barrier` against the shared SqliteSaver and pass it in.

    Empty `snap.next` is ambiguous: it means the graph is terminal OR the
    thread has no checkpoint at all (freshly-spawned subprocess that
    hasn't flushed its first state yet). Round-N children are launched
    in parallel and the barrier polls within seconds; without
    disambiguation, every fresh child is mis-resolved on the first
    barrier tick — closed-loop declares premature convergence and exits.
    See wiki/incidents/barrier-false-positive-round1.md.

    Disambiguation: a real terminal state has both populated `values` AND
    `metadata.step >= 1` (at least one super-step executed). Fresh threads
    return empty `values` and `step == -1` from LangGraph's SqliteSaver.
    """
    cfg = {"configurable": {"thread_id": name}}
    try:
        snap = child_graph.get_state(cfg)
    except Exception:
        return False
    if snap is None or snap.next:
        return False
    if not snap.values:
        return False
    meta = getattr(snap, "metadata", None) or {}
    if meta.get("step", -1) < 1:
        return False
    return True


def _leaderboard_len(mode: str) -> int:
    """Count leaderboard rows for the given mode (flock-aware via load_history)."""
    sys.path.insert(0, str(PROJECT_ROOT))
    import autoresearch_bo_michael as bo  # noqa: WPS433
    return len(bo.MODES[mode].load_history())


# ============================================================================
# Nodes
# ============================================================================

def node_renew_token(state: RoundState) -> dict:
    """Refresh krb5 ticket + bearer token at top of each round.

    Closed-loop rounds run 6-8 h wall; default krb5 lifetime is ~25 h, so
    one or two rounds easily outlive the ticket. First post-expiry
    subprocess.run raises Errno 127 (ENOKEY) and the inner graph
    terminates before harvest. See wiki/incidents/kerberos-mid-run-expiry.md.

    Hard gate: if `getToken` fails (proxy for "can we actually submit?"),
    `sys.exit(2)` with an actionable message. Continuing past expiry just
    guarantees every child dies later with the same Errno 127, leaving
    orphan grid clusters and no leaderboard rows. The outer graph is
    checkpointed — operator runs `kinit` then re-invokes with the same
    `--thread-id` to resume from this node.

    `kinit -R` is best-effort (it's normal for it to fail if the ticket
    is past its renewable lifetime); the load-bearing check is `getToken`.
    """
    errors = list(state.get("errors", []))
    try:
        r = subprocess.run(["kinit", "-R"], capture_output=True, text=True, timeout=30)
        if r.returncode != 0:
            errors.append(f"renew_token[r{state['round_idx']}]: kinit -R rc={r.returncode}: "
                          f"{r.stderr.strip()[:200]}")
    except Exception as exc:  # noqa: BLE001
        errors.append(f"renew_token[r{state['round_idx']}]: kinit -R failed: {exc}")
    cmd = "source /cvmfs/mu2e.opensciencegrid.org/setupmu2e-art.sh && getToken"
    try:
        r = subprocess.run(["bash", "-lc", cmd], capture_output=True, text=True, timeout=120)
    except Exception as exc:  # noqa: BLE001
        msg = (f"[closed_loop] FATAL renew_token[r{state['round_idx']}]: "
               f"getToken raised: {exc}. "
               f"Run `kinit` then re-invoke with same --thread-id to resume.")
        print(msg, flush=True)
        sys.exit(2)
    if r.returncode != 0:
        msg = (f"[closed_loop] FATAL renew_token[r{state['round_idx']}]: "
               f"getToken rc={r.returncode}: {r.stderr.strip()[:400]}. "
               f"Run `kinit` (krb5 likely past renewable lifetime) then "
               f"re-invoke with same --thread-id to resume.")
        print(msg, flush=True)
        sys.exit(2)
    print(f"[closed_loop] renew_token[r{state['round_idx']}]: krb5 + bearer refreshed", flush=True)
    return {"errors": errors}


def node_predict_picks(state: RoundState) -> dict:
    """Refit GP in-process, return q picks (helical 4D or foils 5D, mode-keyed)."""
    q = state["q"]
    gp = _import_gp(state["mode"])
    picks = gp.compute_explore_picks(
        q=q,
        nsteps_budget=state.get("nsteps_budget", NSTEPS_BUDGET),
        min_spacing=state.get("min_spacing", CLOSED_LOOP_MIN_PICK_SPACING),
        pessimistic_calo=state.get("pessimistic_calo", False),
    )
    print(f"[closed_loop] predict_picks[r{state['round_idx']}]: "
          f"pessimistic_calo={state.get('pessimistic_calo', False)} q={q} "
          f"got={len(picks)}", flush=True)
    errors = list(state.get("errors", []))
    if len(picks) < q:
        errors.append(
            f"predict_picks[r{state['round_idx']}]: only got {len(picks)}/{q} "
            f"picks (Pareto frontier too short or too clustered)"
        )
    # Store picks transiently in children dict keyed by *placeholder* name;
    # real names land in assign_names. Also snapshot leaderboard length so
    # decide_next can detect "round produced 0 new rows" (all children
    # failed → exit early instead of refitting on identical data).
    transient = {f"_pick_{j:02d}": {"x_point": list(p)} for j, p in enumerate(picks)}
    return {
        "children": transient,
        "errors": errors,
        "history_len_before": _leaderboard_len(state["mode"]),
    }


def node_assign_names(state: RoundState) -> dict:
    """Derive {prefix}R{NN}_{j} names; skip names already complete."""
    prefix = state["name_prefix"]
    r = state["round_idx"]
    mode = state["mode"]
    transient = state.get("children", {})
    children: Dict[str, ChildRecord] = {}
    completed: List[str] = list(state.get("completed_names", []))
    for j_str, rec in sorted(transient.items()):
        if not j_str.startswith("_pick_"):
            # Already a real name (resume path) — keep as-is.
            children[j_str] = rec
            continue
        j = int(j_str.split("_")[-1])
        name = f"{prefix}R{r:02d}_{j:02d}"
        if _child_in_leaderboard(name, mode) or _child_is_broken(name):
            completed.append(name)
            continue
        children[name] = {
            "x_point": rec["x_point"],
            "log": str(GRAPH_DATA / "closed_loop_logs" / f"{name}.log"),
            "pid": None,
            "started_at": 0.0,
        }
    return {"children": children, "completed_names": completed}


def node_launch_children(state: RoundState) -> dict:
    """Popen one `graph.run` per pending child; stagger between launches."""
    stagger = state.get("stagger_sec", CLOSED_LOOP_STAGGER_SEC)
    mode = state["mode"]
    alpha = state["alpha"]
    children = dict(state["children"])
    errors = list(state.get("errors", []))
    # Idempotency: skip names whose inner graph has already started a stage
    # (per-stage cluster.txt exists) OR landed in the leaderboard OR have
    # broken.txt. A crashed parent re-entering launch_children must not
    # re-Popen `graph.run` for a config whose grid submission is in flight,
    # otherwise we double-submit (and pollute pending TSV / cluster files).
    def _already_running(name: str) -> bool:
        state_dir = _child_state_dir(name)
        if any(state_dir.glob("*_cluster.txt")):
            return True
        return _child_in_leaderboard(name, mode) or _child_is_broken(name)

    pending = [
        (n, rec) for n, rec in children.items()
        if not rec.get("pid") and not _already_running(n)
    ]
    (GRAPH_DATA / "closed_loop_logs").mkdir(parents=True, exist_ok=True)
    for idx, (name, rec) in enumerate(pending):
        x = rec["x_point"]
        log_path = Path(rec["log"])
        log_path.parent.mkdir(parents=True, exist_ok=True)
        log_fh = open(log_path, "w")
        cmd = [
            sys.executable, "-m", "graph.run",
            "--thread-id", name,
            "--config-name", name,
            "--mode", mode,
            "--alpha", str(alpha),
            "--no-mock",
            "--x-point", ",".join(f"{v:.6f}" for v in x),
        ]
        try:
            proc = subprocess.Popen(
                cmd,
                stdin=subprocess.DEVNULL,
                stdout=log_fh,
                stderr=subprocess.STDOUT,
                start_new_session=True,
                cwd=str(PROJECT_ROOT),
            )
            rec["pid"] = proc.pid
            rec["started_at"] = time.time()
            print(f"[closed_loop] launched {name} pid={proc.pid} log={log_path}", flush=True)
        except Exception as exc:  # noqa: BLE001
            errors.append(f"launch[{name}]: {exc}")
        children[name] = rec
        if idx < len(pending) - 1:
            time.sleep(stagger)
    return {"children": children, "errors": errors}


def node_barrier(state: RoundState) -> dict:
    """Block until every child resolves (terminal checkpoint, leaderboard row,
    or broken.txt) or barrier_timeout_min elapses, or STOP_FLAG appears."""
    poll = state.get("barrier_poll_sec", CLOSED_LOOP_BARRIER_POLL_SEC)
    deadline = time.time() + state.get(
        "barrier_timeout_min", CLOSED_LOOP_BARRIER_TIMEOUT_MIN
    ) * 60
    mode = state["mode"]
    children = state["children"]
    completed = set(state.get("completed_names", []))
    errors = list(state.get("errors", []))
    conn = _open_saver_conn()
    saver = SqliteSaver(conn)
    # Compile the inner child graph once so we can call get_state(cfg).next
    # against each child's thread_id. CheckpointTuple has no .next field;
    # only StateSnapshot does, and StateSnapshot only comes from a compiled
    # graph attached to the saver.
    sys.path.insert(0, str(PROJECT_ROOT))
    from graph.build import _build_graph  # noqa: WPS433
    child_graph = _build_graph().compile(checkpointer=saver)
    try:
        while True:
            pending = [n for n in children if n not in completed]
            for name in list(pending):
                if _child_in_leaderboard(name, mode) or _child_is_broken(name):
                    completed.add(name)
                elif _child_terminal_via_checkpoint(name, child_graph):
                    # Terminal checkpoint but no leaderboard row + no broken.txt
                    # → graph ended via preflight-fail / stage-fail. Count as done.
                    completed.add(name)
                    errors.append(
                        f"barrier[{name}]: terminal checkpoint but no leaderboard "
                        f"row (likely preflight/stage failure)"
                    )
            if all(n in completed for n in children):
                print(f"[closed_loop] barrier: all {len(children)} children resolved", flush=True)
                break
            if _stop_requested():
                errors.append(f"barrier[r{state['round_idx']}]: STOP_FLAG seen, exiting")
                break
            if time.time() > deadline:
                errors.append(
                    f"barrier[r{state['round_idx']}]: timeout after "
                    f"{state.get('barrier_timeout_min', CLOSED_LOOP_BARRIER_TIMEOUT_MIN)}min; "
                    f"{len(children) - len(completed)} children still pending"
                )
                break
            time.sleep(poll)
    finally:
        conn.close()
    return {"completed_names": sorted(completed), "errors": errors}


def node_decide_next(state: RoundState) -> dict:
    """Bump round_idx; check zero-row safety break; clear children for next round.

    Zero-row break: if the round's barrier added 0 new leaderboard rows
    compared to predict_picks's snapshot, all children failed
    (preflight-fail, scan_logs-broken, harvest crash). Continuing would
    refit on identical data and re-propose the same picks (foilsX04
    failure mode, 2026-05-29) — exit instead.
    """
    mode = state["mode"]
    before = state.get("history_len_before", 0)
    after = _leaderboard_len(mode)
    new_rows = after - before
    zero_rows = new_rows <= 0
    if zero_rows:
        print(f"[closed_loop] decide_next[r{state['round_idx']}]: "
              f"0 new leaderboard rows this round (before={before} after={after}) "
              f"— all children failed; exiting early", flush=True)
    else:
        print(f"[closed_loop] decide_next[r{state['round_idx']}]: "
              f"+{new_rows} new rows (before={before} after={after})", flush=True)
    return {
        "round_idx": state["round_idx"] + 1,
        "zero_rows": zero_rows,
        "children": {},
        # completed_names intentionally persists across rounds.
    }


def route_after_decide(state: RoundState):
    if state.get("zero_rows"):
        return END
    if state["round_idx"] >= state["max_rounds"]:
        return END
    if _stop_requested():
        return END
    return "renew_token"


# ============================================================================
# Graph wiring
# ============================================================================

def _build_outer_graph():
    g = StateGraph(RoundState)
    g.add_node("renew_token", node_renew_token)
    g.add_node("predict_picks", node_predict_picks)
    g.add_node("assign_names", node_assign_names)
    g.add_node("launch_children", node_launch_children)
    g.add_node("barrier", node_barrier)
    g.add_node("decide_next", node_decide_next)

    g.set_entry_point("renew_token")
    g.add_edge("renew_token", "predict_picks")
    g.add_edge("predict_picks", "assign_names")
    g.add_edge("assign_names", "launch_children")
    g.add_edge("launch_children", "barrier")
    g.add_edge("barrier", "decide_next")
    g.add_conditional_edges("decide_next", route_after_decide,
                            {"renew_token": "renew_token", END: END})
    return g


# ============================================================================
# CLI
# ============================================================================

_DRY_RUN_KNOB_LABELS = {
    "helical": ("dx", "dy", "halflen", "angle"),
    "foils":   ("n_up", "n_down", "extra_rOut", "extra_halfThickness", "extra_rIn"),
}


def _dry_run(args: argparse.Namespace) -> int:
    gp = _import_gp(args.mode)
    picks = gp.compute_explore_picks(
        q=args.q, nsteps_budget=args.nsteps_budget, min_spacing=args.min_spacing,
        pessimistic_calo=args.pessimistic_calo,
    )
    print(f"[dry-run] round 0: {len(picks)} picks (mode={args.mode})")
    labels = _DRY_RUN_KNOB_LABELS.get(args.mode, tuple(f"x{i}" for i in range(len(picks[0]) if picks else 0)))
    for j, p in enumerate(picks):
        name = f"{args.name_prefix}R00_{j:02d}"
        kv = " ".join(f"{labels[i]}={p[i]:.4g}" for i in range(len(p)))
        print(f"  {name}: {kv}")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", default=DEFAULT_MODE,
                    choices=["helical", "michael", "foils"])
    ap.add_argument("--alpha", type=float, default=DEFAULT_ALPHA)
    ap.add_argument("--q", type=int, default=CLOSED_LOOP_Q)
    ap.add_argument("--max-rounds", type=int, default=CLOSED_LOOP_MAX_ROUNDS)
    ap.add_argument("--name-prefix", default="helical",
                    help="child names will be {prefix}R{round:02d}_{j:02d} "
                         "(R is the round marker, not part of the prefix)")
    ap.add_argument("--nsteps-budget", type=int, default=NSTEPS_BUDGET)
    ap.add_argument("--stagger", type=int, default=CLOSED_LOOP_STAGGER_SEC,
                    help="seconds between successive child launches")
    ap.add_argument("--barrier-poll-sec", type=int, default=CLOSED_LOOP_BARRIER_POLL_SEC)
    ap.add_argument("--barrier-timeout-min", type=int, default=CLOSED_LOOP_BARRIER_TIMEOUT_MIN)
    ap.add_argument("--min-spacing", type=float, default=CLOSED_LOOP_MIN_PICK_SPACING,
                    help="normalized-L2 minimum distance between picks")
    ap.add_argument("--pessimistic-calo", action="store_true", default=False,
                    help="shift log-calo GP fallback to log(max y_calo); "
                         "biases picks away from ~3.82e-6 ridge regime "
                         "(see wiki bo-helical pessimistic-prior bullet)")
    ap.add_argument("--thread-id", default=None,
                    help="if omitted, a fresh uuid is used; reuse to resume")
    ap.add_argument("--dry-run", action="store_true",
                    help="print round-0 picks + names without launching")
    args = ap.parse_args()

    if args.dry_run:
        return _dry_run(args)

    GRAPH_DATA.mkdir(parents=True, exist_ok=True)
    conn = _open_saver_conn()
    saver = SqliteSaver(conn)
    graph = _build_outer_graph().compile(checkpointer=saver)

    thread_id = args.thread_id or f"closed-{uuid.uuid4().hex[:8]}"
    cfg = {"configurable": {"thread_id": thread_id}}
    init: RoundState = {
        "mode": args.mode,
        "alpha": args.alpha,
        "q": args.q,
        "nsteps_budget": args.nsteps_budget,
        "max_rounds": args.max_rounds,
        "round_idx": 0,
        "name_prefix": args.name_prefix,
        "children": {},
        "completed_names": [],
        "errors": [],
        "stagger_sec": args.stagger,
        "barrier_poll_sec": args.barrier_poll_sec,
        "barrier_timeout_min": args.barrier_timeout_min,
        "min_spacing": args.min_spacing,
        "pessimistic_calo": args.pessimistic_calo,
    }

    print(f"[closed_loop] thread_id={thread_id} q={args.q} max_rounds={args.max_rounds} "
          f"prefix={args.name_prefix}", flush=True)
    # Resume vs fresh: if a checkpoint exists for this thread_id, pass None
    # so LangGraph picks up from the last node instead of re-seeding state
    # (which would re-run predict_picks → assign_names → launch_children
    # and spawn duplicate grid children for the same configs).
    existing = graph.get_state(cfg) if thread_id else None
    if existing and existing.values:
        print(f"[closed_loop] resuming thread_id={thread_id} from next={existing.next}", flush=True)
        stream_input = None
    else:
        stream_input = init
    final = None
    for ev in graph.stream(stream_input, cfg, stream_mode="values"):
        final = ev
        snap = {
            "round_idx": ev.get("round_idx"),
            "completed": len(ev.get("completed_names", [])),
            "history_len_before": ev.get("history_len_before"),
            "zero_rows": ev.get("zero_rows"),
        }
        print(f"[closed_loop] {json.dumps(snap)}", flush=True)
    print(f"[closed_loop] done. final keys: {sorted((final or {}).keys())}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
