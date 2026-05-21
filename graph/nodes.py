"""Graph nodes for the BO iteration (Phase 1: mock grid).

Each node is a pure function: state in → partial state out. LangGraph merges
the returned dict into the running state and checkpoints it.
"""
from __future__ import annotations

import time
from typing import Literal

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from langgraph.graph import END  # noqa: E402

import pipeline_io as pio  # noqa: E402
from config import DEFAULT_ALPHA, DEFAULT_MODE, MAX_PROPOSE_RETRIES  # noqa: E402
from state import BOIterationState  # noqa: E402


def node_propose(state: BOIterationState) -> dict:
    """Ask the BO model for the next x; materialize the geom file.

    If state["x_point"] is already populated, skip the BO ask and force that
    point (used to evaluate GP-Pareto picks).
    """
    mode = state.get("mode", DEFAULT_MODE)
    alpha = state.get("alpha", DEFAULT_ALPHA)
    name = state.get("config_name") or pio.next_config_name(mode)
    forced = state.get("x_point") or None

    try:
        x, geom = pio.propose_one(mode, name, alpha=alpha, x_override=forced)
    except ValueError as exc:
        # Name collision — pick a fresh one and retry once.
        retry_name = pio.next_config_name(mode)
        x, geom = pio.propose_one(mode, retry_name, alpha=alpha, x_override=forced)
        name = retry_name

    return {
        "config_name": name,
        "mode": mode,
        "alpha": alpha,
        "x_point": x,
        "geom_path": geom,
        "preflight": "pending",
        "stages": {},
        "metrics": None,
        "objective": None,
        "attempts": {**state.get("attempts", {}), "propose": state.get("attempts", {}).get("propose", 0) + 1},
        "errors": state.get("errors", []),
        "mock": state.get("mock", True),
    }


def node_render_preflight(state: BOIterationState) -> dict:
    """Run mu2e -n 1 + surface-check on the proposal.

    Outcomes (managed-volume overlap → fail_managed → retry propose;
    init failure or ambiguous → terminal error).
    """
    mode = state["mode"]
    name = state["config_name"]
    status, tail = pio.run_preflight(mode, name)
    errors = list(state.get("errors", []))
    if status not in ("pass",):
        errors.append(f"preflight[{status}] {name}: {tail.splitlines()[-1] if tail else ''}")
    return {"preflight": status, "errors": errors}


def make_stage_node(stage: str):
    """Build a graph node that runs one stage (submit→poll→list-outputs).

    Real-grid path only — the mock path is handled by `node_mock_grid`,
    which bypasses the entire stage chain (preflight routes to it directly).
    Per-stage idempotency lives in pipeline.py guards, so re-entry after a
    checkpoint kill is safe.
    """
    def _node(state: BOIterationState) -> dict:
        name = state["config_name"]
        errors = list(state.get("errors", []))
        stages = dict(state.get("stages", {}))
        try:
            stages[stage] = pio.run_stage(name, stage)
        except Exception as exc:  # noqa: BLE001
            errors.append(f"stage[{stage}/{name}]: {exc}")
            stages[stage] = {
                "cluster_id": None, "status": "failed",
                "n_done": 0, "n_failed": 0, "last_poll_ts": time.time(),
            }
        return {"stages": stages, "errors": errors}
    _node.__name__ = f"node_stage_{stage}"
    return _node


def node_harvest(state: BOIterationState) -> dict:
    """Run pipeline.py harvest; populate metrics from summary.json."""
    name = state["config_name"]
    errors = list(state.get("errors", []))
    try:
        metrics = pio.run_harvest(name)
    except Exception as exc:  # noqa: BLE001
        errors.append(f"harvest[{name}]: {exc}")
        return {"metrics": None, "errors": errors}
    return {"metrics": metrics, "errors": errors}


def node_mock_grid(state: BOIterationState) -> dict:
    """Mock substitute for the real grid chain: synthesizes metrics from x."""
    return {"metrics": pio.mock_metrics(state["x_point"])}


def node_scan_logs(state: BOIterationState) -> dict:
    """End-of-workflow log scan. Report-only — never fails the iteration.

    Walks every worker .log under the four stage outstage dirs and counts
    G4Exception / Stuck Track / Warning / FATAL / SEGV hits. Writes a TSV +
    JSON report under <grid_root>/<config_name>/scan_logs/ and populates
    state.scan_report for checkpoint visibility. Iteration continues to
    evaluate regardless of findings.
    """
    name = state["config_name"]
    errors = list(state.get("errors", []))
    try:
        report, report_path = pio.scan_worker_logs(name)
    except Exception as exc:  # noqa: BLE001
        errors.append(f"scan_logs[{name}]: {exc}")
        return {"scan_report": None, "scan_report_path": None, "errors": errors}
    return {
        "scan_report": report,
        "scan_report_path": str(report_path),
        "errors": errors,
    }


def node_evaluate(state: BOIterationState) -> dict:
    """Append the (x, metrics) point to the leaderboard."""
    mode = state["mode"]
    name = state["config_name"]
    alpha = state.get("alpha", DEFAULT_ALPHA)
    metrics = state["metrics"]
    obj, tail = pio.run_evaluate(mode, name, metrics, alpha=alpha)
    errors = list(state.get("errors", []))
    if obj is None:
        errors.append(f"evaluate[{name}]: could not parse objective; tail={tail}")
    return {"objective": obj, "errors": errors}


def node_decide_next(state: BOIterationState) -> dict:
    """Bump iteration counter; if auto_continue and iter+1<max_iter, prep next.

    When looping, we clear `config_name` so `propose` auto-generates a fresh
    name from the leaderboard, and reset per-iter scratch (attempts, errors,
    preflight, metrics, objective).
    """
    cur_iter = state.get("iter", 0)
    next_iter = cur_iter + 1
    auto = state.get("auto_continue", False)
    max_iter = state.get("max_iter", 1)
    if auto and next_iter < max_iter:
        return {
            "iter": next_iter,
            "config_name": None,
            "attempts": {},
            "preflight": "pending",
            "metrics": None,
            "objective": None,
        }
    return {"iter": next_iter}


# --- conditional edges ---


def route_after_preflight(state: BOIterationState) -> Literal["real", "mock", "propose", "__end__"]:
    """Branch after preflight."""
    status = state.get("preflight", "pending")
    attempts = state.get("attempts", {}).get("propose", 0)
    if status == "pass":
        return "mock" if state.get("mock", True) else "real"
    if status == "fail_managed" and attempts < MAX_PROPOSE_RETRIES:
        return "propose"
    return END


def route_after_stage(state: BOIterationState) -> Literal["next", "__end__"]:
    """Continue down the stage chain unless any stage is marked failed.

    Walks state["stages"] for any failure; conservative — one bad stage
    terminates the iteration so evaluate doesn't run with partial metrics.
    """
    stages = state.get("stages", {}) or {}
    if any((s or {}).get("status") == "failed" for s in stages.values()):
        return END
    return "next"


def route_after_decide(state: BOIterationState) -> Literal["propose", "__end__"]:
    """Loop back to propose when auto_continue is on and we haven't hit max_iter."""
    if state.get("auto_continue") and state.get("iter", 0) < state.get("max_iter", 1):
        return "propose"
    return END
