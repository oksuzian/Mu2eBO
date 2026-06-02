#!/usr/bin/env python3
"""Rewrite the <!-- highlights:start --> ... <!-- highlights:end --> block in
docs/foils_talk.md from the current leaderboard_bo_foils_v1.tsv.

Numbers stamped:
  - n_evals (data row count)
  - best obj + (sob, calo) at that row
  - calo floor (min calo across all rows)
  - winning region: modal n_down + rOut mean over top-5 by obj

Called by tools/refresh_foils_slides.sh before marp re-render. Idempotent.
"""
from __future__ import annotations
import csv
import re
import subprocess
import sys
from pathlib import Path
from statistics import mean
from collections import Counter

ROOT = Path("/exp/mu2e/app/users/oksuzian/autoresearch")
LB = ROOT / "leaderboard_bo_foils_v1.tsv"
MD = ROOT / "docs" / "foils_talk.md"
SAT_REPORT = Path("/exp/mu2e/data/users/oksuzian/autoresearch_grid/"
                  "mmackenz_table_plots/saturation_report.py")
VENV = ROOT / ".venv-botorch" / "bin" / "python"

START = "<!-- highlights:start -->"
END = "<!-- highlights:end -->"


def saturation_phrase() -> str:
    """Shell out to saturation_report.py and parse its VERDICT line.

    Returns 'frontier saturated', 'frontier still expanding', or
    'frontier status unknown' if the script can't be invoked.
    """
    if not (SAT_REPORT.exists() and VENV.exists() and LB.exists()):
        return "frontier status unknown"
    try:
        out = subprocess.run(
            [str(VENV), str(SAT_REPORT), str(LB), "--prefix", "foilsX"],
            capture_output=True, text=True, timeout=60,
        )
    except (subprocess.TimeoutExpired, OSError):
        return "frontier status unknown"
    text = (out.stdout or "") + (out.stderr or "")
    for line in text.splitlines():
        if "VERDICT" in line.upper():
            up = line.upper()
            if "SATURATED" in up and "NOT SATURATED" not in up:
                return "frontier saturated"
            return "frontier still expanding"
    return "frontier status unknown"


def main() -> int:
    if not LB.exists() or not MD.exists():
        print(f"[stamp] missing {LB} or {MD}", file=sys.stderr)
        return 1
    with LB.open() as fh:
        rows = list(csv.DictReader(fh, delimiter="\t"))
    rows = [r for r in rows if r.get("obj") not in (None, "", "None")]
    if not rows:
        print("[stamp] no usable rows", file=sys.stderr)
        return 1
    for r in rows:
        for k in ("sob", "calo", "obj", "n_down", "extra_rOut"):
            try:
                r[k] = float(r[k])
            except (TypeError, ValueError):
                r[k] = None

    n_evals = len(rows)
    best = max(rows, key=lambda r: r["obj"])
    calo_floor = min(r["calo"] for r in rows if r["calo"] is not None)
    top5 = sorted(rows, key=lambda r: r["obj"], reverse=True)[:5]
    nd_mode = Counter(int(r["n_down"]) for r in top5 if r["n_down"] is not None).most_common(1)[0][0]
    rout_mean = mean(r["extra_rOut"] for r in top5 if r["extra_rOut"] is not None)

    sat = saturation_phrase()
    block = (
        f"{START}\n"
        f"- **{n_evals} evals**, {sat}\n"
        f"- Best **obj = {best['obj']:.2f}** "
        f"(sob {best['sob']:.2f}, calo {best['calo']*1e5:.2f} × 10⁻⁵); "
        f"calo floor **{calo_floor:.1e}**\n"
        f"- Winning region: `n_down = {nd_mode}`, "
        f"`rOut ≈ {rout_mean:.0f} mm`, thin `hT`\n"
        f"{END}"
    )
    text = MD.read_text()
    pattern = re.compile(re.escape(START) + r".*?" + re.escape(END), re.DOTALL)
    if not pattern.search(text):
        print(f"[stamp] highlights markers not found in {MD}", file=sys.stderr)
        return 1
    new = pattern.sub(block, text)
    if new == text:
        print(f"[stamp] no change (n_evals={n_evals}, best_obj={best['obj']:.3f})")
        return 0
    MD.write_text(new)
    print(f"[stamp] rewrote highlights: n_evals={n_evals} best_obj={best['obj']:.3f} "
          f"calo_floor={calo_floor:.1e} n_down_mode={nd_mode} rOut_mean={rout_mean:.0f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
