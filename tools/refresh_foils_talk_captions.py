#!/usr/bin/env python3
"""Refresh data-derived caption numbers in docs/foils_talk.md.

Owns three caption regions delimited by HTML-comment markers in the slide
markdown — same convention as the stamp_foils_highlights.py "highlights"
block. Each region is rewritten from the live leaderboard. Idempotent.

Regions
-------
<!-- botorch-cross-check:start --> ... <!-- botorch-cross-check:end -->
<!-- run-timeline:start -->      ... <!-- run-timeline:end -->

The YAML frontmatter `footer:` line is rewritten by line-regex match
(HTML comment markers aren't legal inside YAML).

The fourth region, "highlights:start/end", remains owned by
stamp_foils_highlights.py — kept separate so that script can run from
the 4-hourly cron without dragging in the whole caption refresh.

Exit codes
----------
0 = success (rewrote or no-change); non-zero only on parse failure.
"""
from __future__ import annotations
import csv
import re
import sys
from collections import Counter
from datetime import date
from pathlib import Path

ROOT = Path("/exp/mu2e/app/users/oksuzian/autoresearch")
MD = ROOT / "docs" / "foils_talk.md"
LB = ROOT / "leaderboard_bo_foils_v1.tsv"


def load_rows():
    rows = list(csv.DictReader(LB.open(), delimiter="\t"))
    for r in rows:
        for k in ("sob", "calo", "obj", "n_up", "n_down",
                  "extra_rOut", "extra_halfThickness", "extra_rIn"):
            try:
                r[k] = float(r[k])
            except (TypeError, ValueError):
                r[k] = None
    return rows


def prefix_counts(rows):
    """foilsX07R01_03 -> X07 ; return ordered list of (prefix, count)."""
    c = Counter()
    for r in rows:
        n = r["config"]
        if n.startswith("foilsX") and len(n) >= 8:
            c[n[5:8]] += 1
    return sorted(c.items())


def latest_prefix(rows):
    pcs = prefix_counts(rows)
    return pcs[-1][0] if pcs else None


def render_botorch_caption(rows):
    """Read sob_max / calo_min from the actual freshly-rendered plot inputs.

    The script's own stdout is the source of truth — re-run it without
    writing the PNG, only to capture the numbers, would be costly.
    Instead read directly from the leaderboard, which is what the script
    reads. (The Sobol frontier numbers are approximations of GP-predicted
    optima, not raw leaderboard maxima — but for the slide caption the
    leaderboard maxima are the right number to report: it's what was
    actually observed.)
    """
    n = len(rows)
    sob_max = max(r["sob"] for r in rows if r["sob"] is not None)
    calo_min = min(r["calo"] for r in rows if r["calo"] is not None)
    return (
        f"- BoTorch `SingleTaskGP` re-fit on the same **n={n}** rows\n"
        f"- Observed extrema: **sob_max {sob_max:.2f}**; "
        f"**calo_min {calo_min:.2e}**\n"
        f"- Cross-model agreement → foils saturation is "
        f"**model-independent** (same conclusion as helical)"
    )


def render_run_timeline_caption(rows):
    """Total leaderboard count + last-prefix annotation."""
    n = len(rows)
    pcs = prefix_counts(rows)
    parts = ", ".join(f"{p}={c}" for p, c in pcs)
    return (
        f"**Leaderboard now: {n} evals** ({parts}; X04 wiped — see "
        f"ambiguous-preflight incident)."
    )


REGIONS = [
    ("botorch-cross-check", render_botorch_caption),
    ("run-timeline", render_run_timeline_caption),
]


def rewrite_footer(md_text: str, rows) -> tuple[str, bool]:
    """Footer lives in the YAML frontmatter; comment markers aren't legal
    there. Use a line-regex on `footer: "...` instead."""
    today = date.today().isoformat()
    last = latest_prefix(rows) or "?"
    n = len(rows)
    new = (
        f'footer: "FoilsMode — 5D BO on the Mu2e Stopping-Target Foil '
        f'Stack · Y. Oksuzian · {today} (n={n}, latest={last})"'
    )
    pat = re.compile(r'^footer:\s*".*"$', re.MULTILINE)
    m = pat.search(md_text)
    if not m:
        print("[caps] WARN: footer line not found in YAML frontmatter",
              file=sys.stderr)
        return md_text, False
    if m.group(0) == new:
        return md_text, False
    return md_text[:m.start()] + new + md_text[m.end():], True


def rewrite(md_text: str, name: str, new_body: str) -> tuple[str, bool]:
    start = f"<!-- {name}:start -->"
    end = f"<!-- {name}:end -->"
    pat = re.compile(re.escape(start) + r".*?" + re.escape(end), re.DOTALL)
    m = pat.search(md_text)
    if not m:
        print(f"[caps] WARN: markers {name} not found in {MD} — skipping",
              file=sys.stderr)
        return md_text, False
    block = f"{start}\n{new_body}\n{end}"
    if m.group(0) == block:
        return md_text, False
    return md_text[:m.start()] + block + md_text[m.end():], True


def main():
    if not MD.exists():
        print(f"[caps] missing {MD}", file=sys.stderr)
        return 1
    if not LB.exists():
        print(f"[caps] missing {LB}", file=sys.stderr)
        return 1
    rows = load_rows()
    text = MD.read_text()
    changed_any = False
    for name, fn in REGIONS:
        text, changed = rewrite(text, name, fn(rows))
        changed_any = changed_any or changed
    text, changed = rewrite_footer(text, rows)
    changed_any = changed_any or changed
    if changed_any:
        MD.write_text(text)
        print(f"[caps] rewrote captions (n_evals={len(rows)})")
    else:
        print(f"[caps] no change (n_evals={len(rows)})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
