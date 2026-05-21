"""Read-only Streamlit overlay for the LangGraph BO runner (Phase 1).

Three tabs:
  1. Leaderboard — current `leaderboard_bo_helical.tsv` rows.
  2. Iterations — threads from the langgraph dev server (REST API).
  3. BO surface — 2D contour of the GP over (dy, halflength) with samples.

Run with:
  source .venv-graph/bin/activate
  streamlit run graph_app/streamlit_app.py
"""
from __future__ import annotations

import json
import os
from pathlib import Path

import pandas as pd
import requests
import streamlit as st


PROJECT_ROOT = Path("/exp/mu2e/app/users/oksuzian/autoresearch")
LEADERBOARD = PROJECT_ROOT / "leaderboard_bo_helical_v2.tsv"
LEADERBOARD_V1 = PROJECT_ROOT / "leaderboard_bo_helical.tsv"  # 47 real configs (5D, has z0)
PENDING = PROJECT_ROOT / "pending_bo_helical.tsv"
LANGGRAPH_API = os.environ.get("LANGGRAPH_API", "http://127.0.0.1:2024")


st.set_page_config(page_title="BO Helical — LangGraph Runner", layout="wide")
st.title("BO Helical — LangGraph Runner (Phase 1)")
st.caption(f"API: {LANGGRAPH_API}  ·  leaderboard: {LEADERBOARD.name}")

tab_lb, tab_iter, tab_surf = st.tabs(["Leaderboard", "Iterations", "BO surface"])


with tab_lb:
    st.subheader("Leaderboard")
    if LEADERBOARD.exists():
        df = pd.read_csv(LEADERBOARD, sep="\t")
        if "obj" in df.columns:
            df = df.sort_values("obj", ascending=False)
        st.dataframe(df, use_container_width=True, hide_index=True)
        st.caption(f"{len(df)} configs · top obj = {df['obj'].max():.4f}"
                   if "obj" in df.columns and len(df) else "(empty)")
    else:
        st.warning(f"leaderboard not found at {LEADERBOARD}")

    st.subheader("Pending (in-flight proposals)")
    if PENDING.exists():
        try:
            pdf = pd.read_csv(PENDING, sep="\t")
            st.dataframe(pdf, use_container_width=True, hide_index=True)
        except Exception as exc:
            st.error(f"could not parse pending: {exc}")
    else:
        st.info("no pending file yet")


with tab_iter:
    st.subheader("Threads (langgraph dev)")
    st.caption("Live state of every iteration. Refresh the page to update.")
    try:
        r = requests.post(
            f"{LANGGRAPH_API}/threads/search",
            json={"limit": 50}, timeout=5,
        )
        r.raise_for_status()
        threads = r.json()
    except Exception as exc:
        st.error(f"could not reach langgraph dev at {LANGGRAPH_API}: {exc}")
        threads = []

    if not threads:
        st.info("no threads yet — invoke one via Studio or the REST API")
    for t in threads:
        tid = t.get("thread_id", "?")
        status = t.get("status", "?")
        created = t.get("created_at", "")
        with st.expander(f"{tid}  ·  {status}  ·  {created}"):
            vals = t.get("values") or {}
            cols = st.columns(4)
            cols[0].metric("config", vals.get("config_name", "—"))
            cols[1].metric("preflight", vals.get("preflight", "—"))
            obj = vals.get("objective")
            cols[2].metric("objective", f"{obj:.4f}" if isinstance(obj, (int, float)) else "—")
            cols[3].metric("errors", len(vals.get("errors", []) or []))
            st.json(vals)


with tab_surf:
    st.subheader("BO surface (dy × halflength)")
    st.caption("Re-fits the GP from v1+v2 leaderboard rows (z0 dropped); "
               "slices fix dx=dx_mean, angle=angle_mean.")
    needed = {"dx", "dy", "halflength", "angle", "obj"}
    frames = []
    for path, tag in [(LEADERBOARD_V1, "v1"), (LEADERBOARD, "v2")]:
        if path.exists():
            d = pd.read_csv(path, sep="\t")
            if needed.issubset(d.columns):
                d = d[list(needed) + (["config"] if "config" in d.columns else [])].copy()
                d["source"] = tag
                frames.append(d)
    if not frames:
        st.warning("no leaderboards found with required columns")
        df = pd.DataFrame()
    else:
        df = pd.concat(frames, ignore_index=True)
        parts = " + ".join(f"{f['source'].iloc[0]}={len(f)}" for f in frames)
        st.caption(f"loaded {len(df)} rows ({parts})")
    if df.empty:
        pass
    else:
        if len(df) < 5:
            st.info("need ≥5 leaderboard points to fit a GP")
        else:
            try:
                import numpy as np
                import plotly.graph_objects as go
                from skopt import Optimizer
                from skopt.space import Real

                KNOBS = ["dx", "dy", "halflength", "angle"]
                BOUNDS = {"dx": (0.01, 5.0), "dy": (40.0, 400.0),
                          "halflength": (25.0, 500.0), "angle": (60.0, 540.0)}
                space = [Real(*BOUNDS[k], name=k) for k in KNOBS]
                opt = Optimizer(space, base_estimator="GP", random_state=0,
                                n_initial_points=1)
                n_told = 0
                for _, row in df.iterrows():
                    x = [float(row[k]) for k in KNOBS]
                    try:
                        opt.tell(x, -float(row["obj"]))
                        n_told += 1
                    except ValueError:
                        continue
                if n_told < 2:
                    st.info(f"only {n_told} in-bounds points; need ≥2 to fit")
                    st.stop()
                opt.ask()  # force GP build (skopt fits lazily on ask())

                c1, c2 = st.columns(2)
                x_axis = c1.selectbox("x axis", KNOBS, index=1)
                y_axis = c2.selectbox("y axis", KNOBS, index=2)
                if x_axis == y_axis:
                    st.warning("pick two different knobs")
                    st.stop()
                fixed = [k for k in KNOBS if k not in (x_axis, y_axis)]
                fix_vals = {k: float(df[k].mean()) for k in fixed}
                st.caption("fixed at mean: " + ", ".join(f"{k}={v:.3g}" for k,v in fix_vals.items()))

                x_lo, x_hi = BOUNDS[x_axis]
                y_lo, y_hi = BOUNDS[y_axis]
                xs = np.linspace(x_lo, x_hi, 40)
                ys = np.linspace(y_lo, y_hi, 40)
                X, Y = np.meshgrid(xs, ys)
                pts = []
                for xv, yv in zip(X.ravel(), Y.ravel()):
                    row = {x_axis: float(xv), y_axis: float(yv), **fix_vals}
                    pts.append([row[k] for k in KNOBS])
                mu = opt.models[-1].predict(opt.space.transform(pts))
                Z = (-mu).reshape(X.shape)
                fig = go.Figure(data=go.Contour(z=Z, x=xs, y=ys, colorscale="Viridis",
                                                colorbar=dict(title="obj")))
                fig.add_trace(go.Scatter(
                    x=df[x_axis], y=df[y_axis], mode="markers",
                    marker=dict(color=df["obj"], colorscale="Viridis",
                                size=10, line=dict(color="white", width=1)),
                    text=df["config"], name="samples"))
                fig.update_layout(xaxis_title=x_axis, yaxis_title=y_axis,
                                  title=f"obj surface ({x_axis} × {y_axis})",
                                  height=600)
                st.plotly_chart(fig, use_container_width=True)
            except Exception as exc:
                st.error(f"GP fit failed: {exc}")
