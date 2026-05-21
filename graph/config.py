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

# Stage chain (Phase 2b). Each entry is the stage name; per-stage `run_stage`
# calls submit → poll → list-outputs internally. Harvest runs once after the
# four stages complete.
GRID_STAGES = ["mubeam", "run1b_mubeam", "concat", "mustops_ce"]

# Per-stage njobs targets — used by read_stage_status to infer n_failed.
# Kept in sync with pipeline.py STAGES[*]["njobs"]; if those change, update here.
STAGE_TARGETS = {
    "mubeam":       200,
    "run1b_mubeam": 200,
    "concat":         1,
    "mustops_ce":   100,
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
