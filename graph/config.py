"""Paths and tunables for the LangGraph runner."""
from __future__ import annotations

from pathlib import Path

PROJECT_ROOT = Path("/exp/mu2e/app/users/oksuzian/autoresearch")
GRAPH_DATA = PROJECT_ROOT / "graph_data"
CHECKPOINT_DB = GRAPH_DATA / "checkpoints.sqlite"

BO_DRIVER = PROJECT_ROOT / "autoresearch_bo_michael.py"
PIPELINE_DRIVER = PROJECT_ROOT / "pipeline.py"

# Per-config grid work tree lives under here; harvest/summary.json gets written here.
GRID_DATA_ROOT = Path("/exp/mu2e/data/users/oksuzian/autoresearch_grid")

# Mu2e environment sources. Sourced by every preflight/grid invocation.
SETUPMU2E = "/cvmfs/mu2e.opensciencegrid.org/setupmu2e-art.sh"
MUSING = "/cvmfs/mu2e.opensciencegrid.org/Musings/SimJob/Run1Bak/setup.sh"

# Stage chain (Phase 2b). Each entry is the stage name; per-stage `run_stage`
# calls submit → poll → list-outputs internally. Harvest runs once after the
# four stages complete.
GRID_STAGES = ["mubeam", "run1b_mubeam", "concat", "mustops_ce"]

# Per-stage njobs targets — canonical source of truth for both
# pipeline.STAGES (consumed as njobs at submit) and read_stage_status
# (consumed to infer n_failed). Changing these here changes both.
STAGE_TARGETS = {
    "mubeam":       200,
    "run1b_mubeam": 200,
    "concat":         1,
    "mustops_ce":   200,
}

# Phase 1: helical only. michael wiring follows in Phase 2.
DEFAULT_MODE = "helical"
DEFAULT_ALPHA = 1.0e5

# Retry policy for preflight-failed proposals (managed-volume overlap).
MAX_PROPOSE_RETRIES = 3

# Wall-clock cap on a local `mu2e -n 1` preflight (G4 init + surface check).
# Single source of truth; both the BO driver and the graph runner import this.
# Was previously split as 600s (autoresearch_bo_michael.py) vs 1200s
# (graph/pipeline_io.py:run_preflight) — the lower value caused silent
# preflight timeouts on cold-cache CVMFS hits.
PREFLIGHT_TIMEOUT_S = 1200

# Mock metrics knobs (Phase 1 only) — smooth analytic surface over the
# 4D helical search space so the graph has something to optimize.
MOCK_SOB_PEAK = 1.0
MOCK_CALO_FLOOR = 1.0e-7

# ============================================================================
# Closed-loop (graph/closed_loop.py) constants
# ============================================================================
# Number of parallel chains per round.
CLOSED_LOOP_Q = 5
# Cap on rounds in one closed-loop invocation; --max-rounds overrides per call.
CLOSED_LOOP_MAX_ROUNDS = 10
# Delay between consecutive child launches (mitigates concurrent-token-contention;
# see wiki/incidents/concurrent-token-contention.md). 90s matches the value
# proven safe in helicalP01-P05.
CLOSED_LOOP_STAGGER_SEC = 90
# Barrier polling cadence — how often the parent re-reads child checkpoints.
# Closed-loop write rate is ~0.01 writes/sec, so polling every 5min is plenty
# without flooding the SqliteSaver.
CLOSED_LOOP_BARRIER_POLL_SEC = 300
# Wall-clock cap on a single round; tripping this returns control to
# decide_next which will normally end the loop.
CLOSED_LOOP_BARRIER_TIMEOUT_MIN = 240
# Budget knob passed to gp_predict_helical.compute_explore_picks — the
# N_crit Sobol gate for the GP-pick acquisition search. 2000 matches the
# empirically-validated value used by gp_predict_helical.DEFAULT_NSTEPS_BUDGET
# and botorch_predict_helical.NSTEPS_BUDGET; decoupled from HELICAL_NSTEPS
# (FCL render resolution) 2026-05-27 — see wiki/projects/bo-helical.md
# "Update 2026-05-27".
NSTEPS_BUDGET = 2000
# Operator stop file. `touch graph_data/STOP_CLOSED_LOOP` and the next
# barrier-poll iteration or decide_next will exit cleanly without affecting
# in-flight children.
STOP_FLAG = GRAPH_DATA / "STOP_CLOSED_LOOP"
# Minimum normalized-L2 distance between picks returned by
# compute_explore_picks (revision #7). Guards against the degenerate case
# where a short Pareto frontier yields near-duplicate q-picks.
CLOSED_LOOP_MIN_PICK_SPACING = 0.05

# SqliteSaver connection timeout — closed-loop adds outer parent + q children
# all writing to checkpoints.sqlite. WAL is on by default (see
# wiki/concepts/closed-loop-bo-design.md) but bumping the connect timeout
# from the SQLite default 5s to 30s absorbs CephFS lock-acquire jitter
# under bursty multi-writer load.
SQLITE_TIMEOUT_S = 30.0

# Disjoint-venv plumbing: closed_loop.py runs under .venv-graph (langgraph,
# sklearn, skopt) but the botorch_predict.py qNEHVI picker needs .venv-botorch
# (gpytorch + botorch). When --picker qnehvi is requested, node_predict_picks
# subprocess-shells into this interpreter, dumps picks to a tmp JSON, and
# loads them back into the langgraph state.
BOTORCH_VENV_PY = PROJECT_ROOT / ".venv-botorch" / "bin" / "python"
BOTORCH_PREDICT = PROJECT_ROOT / "botorch_predict.py"
