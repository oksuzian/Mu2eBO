#!/usr/bin/env python3
"""Analyze leaderboard_bo_helical.tsv: convergence + per-knob projections."""

import csv
from pathlib import Path
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt

LEADERBOARD = Path("/exp/mu2e/app/users/oksuzian/autoresearch/leaderboard_bo_helical.tsv")
OUT_DIR = Path("/exp/mu2e/app/users/oksuzian/autoresearch/slides")

KNOBS = ["dx", "dy", "halflength", "z0", "angle"]
KNOB_LABELS = {
    "dx":         "dx (mm)",
    "dy":         "dy (mm)",
    "halflength": "halflength (mm)",
    "z0":         "z0 (mm)",
    "angle":      "angle (deg)",
}
KNOB_BOUNDS = {
    "dx":         (0.5, 5.0),
    "dy":         (40.0, 110.0),
    "halflength": (25.0, 300.0),
    "z0":         (4250.0, 4500.0),
    "angle":      (60.0, 540.0),
}
V111 = {"dx": 2.0, "dy": 85.0, "halflength": 150.0, "z0": 4345.0,
        "angle": 360.0, "obj": 1.958}


def load():
    rows = []
    with LEADERBOARD.open() as fh:
        reader = csv.DictReader(fh, delimiter="\t")
        for r in reader:
            rows.append({
                "config": r["config"],
                "dx":         float(r["dx"]),
                "dy":         float(r["dy"]),
                "halflength": float(r["halflength"]),
                "z0":         float(r["z0"]),
                "angle":      float(r["angle"]),
                "sob":        float(r["sob"]),
                "calo":       float(r["calo"]),
                "obj":        float(r["obj"]),
            })
    return rows


def plot_convergence(rows):
    fig, ax = plt.subplots(figsize=(8, 5))
    iters = list(range(1, len(rows) + 1))
    obj = [r["obj"] for r in rows]
    best, cur = [], -1e9
    for o in obj:
        cur = max(cur, o)
        best.append(cur)
    ax.scatter(iters, obj, s=50, c="#888", alpha=0.75, label="per-iter obj")
    ax.plot(iters, best, "o-", c="#1f77b4", lw=2, ms=6, label="best so far")
    ax.axhline(V111["obj"], ls="--", c="#d62728",
               label=f"v111 prior ({V111['obj']:.3f})")
    for i, r in enumerate(rows):
        ax.annotate(r["config"].replace("helical", ""), (iters[i], obj[i]),
                    fontsize=7, alpha=0.6, xytext=(3, 3),
                    textcoords="offset points")
    ax.set_xlabel("BO iteration")
    ax.set_ylabel(r"obj = S/$\sqrt{B}$ - $\alpha$ * calo/POT")
    ax.set_title(f"helical 5D BO convergence ({len(rows)} evals)")
    ax.grid(alpha=0.3)
    ax.legend(loc="lower right", fontsize=10)
    out = OUT_DIR / "bo_helical_convergence.png"
    fig.tight_layout()
    fig.savefig(out, dpi=120)
    print(f"wrote {out}")


def plot_projections(rows):
    fig, axes = plt.subplots(2, 3, figsize=(14, 8))
    axes = axes.flat
    i_best = max(range(len(rows)), key=lambda j: rows[j]["obj"])
    best = rows[i_best]
    for i, knob in enumerate(KNOBS):
        ax = axes[i]
        xs = [r[knob] for r in rows]
        ys = [r["obj"] for r in rows]
        c = list(range(len(rows)))
        ax.scatter(xs, ys, c=c, cmap="viridis", s=60, alpha=0.85,
                   edgecolors="white", linewidths=0.5)
        lo, hi = KNOB_BOUNDS[knob]
        ax.axvline(lo, ls=":", c="#888", lw=1)
        ax.axvline(hi, ls=":", c="#888", lw=1)
        ax.axvline(V111[knob], ls="--", c="#d62728", lw=1,
                   label=f"v111 ({V111[knob]:g})")
        ax.axhline(V111["obj"], ls=":", c="#d62728", lw=1)
        ax.scatter([best[knob]], [best["obj"]],
                   marker="*", s=320, c="gold",
                   edgecolors="black", linewidths=1, zorder=10,
                   label=f"best {best['config']} ({best['obj']:.3f})")
        ax.set_xlabel(KNOB_LABELS[knob])
        ax.set_ylabel("obj")
        ax.set_xlim(lo - 0.02 * (hi - lo), hi + 0.02 * (hi - lo))
        ax.grid(alpha=0.3)
        ax.legend(loc="lower right", fontsize=8)
    # 6th panel: sob vs calo Pareto-ish view
    ax = axes[5]
    sb = [r["sob"] for r in rows]
    ca = [r["calo"] * 1e6 for r in rows]
    c = list(range(len(rows)))
    ax.scatter(ca, sb, c=c, cmap="viridis", s=60, alpha=0.85,
               edgecolors="white", linewidths=0.5)
    ax.scatter([best["calo"] * 1e6], [best["sob"]],
               marker="*", s=320, c="gold",
               edgecolors="black", linewidths=1, zorder=10)
    ax.scatter([V111["dx"] * 0 + 1.62], [2.12], marker="D", s=80,
               c="#d62728", label="v111 prior")
    for i, r in enumerate(rows):
        ax.annotate(r["config"].replace("helical", ""),
                    (r["calo"] * 1e6, r["sob"]),
                    fontsize=7, alpha=0.6, xytext=(3, 3),
                    textcoords="offset points")
    ax.set_xlabel("calo/POT  (1e-6)")
    ax.set_ylabel(r"S/$\sqrt{B}$")
    ax.set_title("objective decomposition")
    ax.grid(alpha=0.3)
    ax.legend(loc="lower right", fontsize=8)
    fig.suptitle(f"helical 5D BO projections ({len(rows)} configs, "
                 f"best={best['config']} obj={best['obj']:.3f})",
                 fontsize=12)
    out = OUT_DIR / "bo_helical_projections.png"
    fig.tight_layout()
    fig.savefig(out, dpi=120)
    print(f"wrote {out}")


def main():
    rows = load()
    print(f"loaded {len(rows)} rows from {LEADERBOARD.name}")
    plot_convergence(rows)
    plot_projections(rows)


if __name__ == "__main__":
    main()
