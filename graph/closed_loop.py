"""Multi-round closed-loop batch BO runner.

Each round:
  1. predict_picks — refit GP on current leaderboard, return q Pareto picks.
  2. assign_names  — derive {prefix}R{NN}_{j} names; skip names already done.
  3. launch_children — Popen `graph.run --config-name … --x-point …` per pick,
                       staggered by CLOSED_LOOP_STAGGER_SEC. Children detach
                       (start_new_session=True) so killing this parent does
                       not propagate.
  4. barrier — poll each child's SqliteSaver checkpoint (NOT the leaderboard
               TSV, which is a derived end-of-harvest artifact) until terminal
               or timeout; cross-check leaderboard for sanity.
  5. refit_and_check — refit GP, hash the Pareto frontier, check convergence.
  6. decide_next — loop unless max_rounds / converged / STOP_FLAG.

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
import hashlib
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
    pareto_hashes: List[str]
    converged: bool
    errors: List[str]
    convergence_k: int
    stagger_sec: int
    barrier_poll_sec: int
    barrier_timeout_min: int
    min_spacing: float


# ============================================================================
# Helpers
# ============================================================================

def _import_gp():
    """Import gp_predict_helical from the sub-repo (path-injected)."""
    if str(GP_SCRIPT_DIR) not in sys.path:
        sys.path.insert(0, str(GP_SCRIPT_DIR))
    import gp_predict_helical  # noqa: WPS433
    return gp_predict_helical


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


def _child_terminal_via_checkpoint(name: str, saver: SqliteSaver) -> bool:
    """True if SqliteSaver shows the child's graph has no remaining work.

    LangGraph stores `next` (tuple of next node names) in checkpoint metadata.
    When the latest tuple has empty `next`, the run has terminated — either
    via END or because all branches resolved.
    """
    cfg = {"configurable": {"thread_id": name}}
    try:
        snapshot = saver.get_tuple(cfg)
    except Exception:
        return False
    if snapshot is None:
        return False
    nxt = snapshot.metadata.get("writes") if snapshot.metadata else None
    # The cleanest signal: snapshot.next is empty.
    return not snapshot.next


def _pareto_hash(picks: List[Tuple[float, ...]]) -> str:
    """Round to 2 sig-figs then hash the sorted tuple set.

    Mirrors revision #3 (closed-loop-bo-design.md): full-precision Pareto
    coords jitter from re-fit randomness, so rounding is required to detect
    "the GP keeps proposing the same frontier."
    """
    def _round(v):
        if v == 0:
            return 0.0
        from math import floor, log10
        exp = floor(log10(abs(v)))
        mult = 10 ** (exp - 1)
        return round(v / mult) * mult
    rounded = sorted(tuple(_round(v) for v in p) for p in picks)
    return hashlib.sha256(json.dumps(rounded).encode()).hexdigest()[:16]


# ============================================================================
# Nodes
# ============================================================================

def node_predict_picks(state: RoundState) -> dict:
    """Refit GP in-process, return q (dx,dy,hl,angle) tuples."""
    q = state["q"]
    gp = _import_gp()
    picks = gp.compute_explore_picks(
        q=q,
        nsteps_budget=state.get("nsteps_budget", NSTEPS_BUDGET),
        min_spacing=state.get("min_spacing", CLOSED_LOOP_MIN_PICK_SPACING),
    )
    errors = list(state.get("errors", []))
    if len(picks) < q:
        errors.append(
            f"predict_picks[r{state['round_idx']}]: only got {len(picks)}/{q} "
            f"picks (Pareto frontier too short or too clustered)"
        )
    # Store picks transiently in children dict keyed by *placeholder* name;
    # real names land in assign_names.
    transient = {f"_pick_{j:02d}": {"x_point": list(p)} for j, p in enumerate(picks)}
    return {"children": transient, "errors": errors}


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
    pending = [(n, rec) for n, rec in children.items() if not rec.get("pid")]
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
    try:
        while True:
            pending = [n for n in children if n not in completed]
            for name in list(pending):
                if _child_in_leaderboard(name, mode) or _child_is_broken(name):
                    completed.add(name)
                elif _child_terminal_via_checkpoint(name, saver):
                    # Terminal checkpoint but no leaderboard row + no broken.txt
                    # → graph ended via preflight-fail / stage-fail. Count as done.
                    completed.add(name)
                    errors.append(
                        f"barrier[{name}]: terminal checkpoint but no leaderboard "
                        f"row (likely preflight/stage failure)"
                    )
            if len(completed) >= len(children):
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


def node_refit_and_check(state: RoundState) -> dict:
    """Refit GP, hash Pareto frontier, mark converged if last K hashes match."""
    gp = _import_gp()
    picks = gp.compute_explore_picks(
        q=state["q"],
        nsteps_budget=state.get("nsteps_budget", NSTEPS_BUDGET),
        min_spacing=state.get("min_spacing", CLOSED_LOOP_MIN_PICK_SPACING),
    )
    h = _pareto_hash(picks)
    hashes = list(state.get("pareto_hashes", [])) + [h]
    k = state.get("convergence_k", 2)
    converged = len(hashes) >= k and len(set(hashes[-k:])) == 1
    print(f"[closed_loop] refit: pareto_hash={h} (last {min(k,len(hashes))}: "
          f"{hashes[-k:]}) converged={converged}", flush=True)
    return {"pareto_hashes": hashes, "converged": converged}


def node_decide_next(state: RoundState) -> dict:
    """Bump round_idx; clear children for next round (or signal terminate)."""
    return {
        "round_idx": state["round_idx"] + 1,
        "children": {},
        # completed_names and pareto_hashes intentionally persist across rounds.
    }


def route_after_decide(state: RoundState):
    if state.get("converged"):
        return END
    if state["round_idx"] >= state["max_rounds"]:
        return END
    if _stop_requested():
        return END
    return "predict_picks"


# ============================================================================
# Graph wiring
# ============================================================================

def _build_outer_graph():
    g = StateGraph(RoundState)
    g.add_node("predict_picks", node_predict_picks)
    g.add_node("assign_names", node_assign_names)
    g.add_node("launch_children", node_launch_children)
    g.add_node("barrier", node_barrier)
    g.add_node("refit_and_check", node_refit_and_check)
    g.add_node("decide_next", node_decide_next)

    g.set_entry_point("predict_picks")
    g.add_edge("predict_picks", "assign_names")
    g.add_edge("assign_names", "launch_children")
    g.add_edge("launch_children", "barrier")
    g.add_edge("barrier", "refit_and_check")
    g.add_edge("refit_and_check", "decide_next")
    g.add_conditional_edges("decide_next", route_after_decide,
                            {"predict_picks": "predict_picks", END: END})
    return g


# ============================================================================
# CLI
# ============================================================================

def _dry_run(args: argparse.Namespace) -> int:
    gp = _import_gp()
    picks = gp.compute_explore_picks(
        q=args.q, nsteps_budget=args.nsteps_budget, min_spacing=args.min_spacing,
    )
    print(f"[dry-run] round 0: {len(picks)} picks")
    for j, p in enumerate(picks):
        name = f"{args.name_prefix}R00_{j:02d}"
        print(f"  {name}: dx={p[0]:.3f} dy={p[1]:.2f} halflen={p[2]:.2f} angle={p[3]:.2f}")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", default=DEFAULT_MODE)
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
    ap.add_argument("--convergence-k", type=int, default=2,
                    help="number of identical Pareto hashes in a row → converged")
    ap.add_argument("--min-spacing", type=float, default=CLOSED_LOOP_MIN_PICK_SPACING,
                    help="normalized-L2 minimum distance between picks")
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
        "pareto_hashes": [],
        "converged": False,
        "errors": [],
        "convergence_k": args.convergence_k,
        "stagger_sec": args.stagger,
        "barrier_poll_sec": args.barrier_poll_sec,
        "barrier_timeout_min": args.barrier_timeout_min,
        "min_spacing": args.min_spacing,
    }

    print(f"[closed_loop] thread_id={thread_id} q={args.q} max_rounds={args.max_rounds} "
          f"prefix={args.name_prefix}", flush=True)
    final = None
    for ev in graph.stream(init, cfg, stream_mode="values"):
        final = ev
        snap = {
            "round_idx": ev.get("round_idx"),
            "completed": len(ev.get("completed_names", [])),
            "hashes": ev.get("pareto_hashes", []),
            "converged": ev.get("converged"),
        }
        print(f"[closed_loop] {json.dumps(snap)}", flush=True)
    print(f"[closed_loop] done. final keys: {sorted((final or {}).keys())}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
