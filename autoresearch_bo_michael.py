#!/usr/bin/env python3
"""Bayesian Optimization for Mu2e geometry: joint S/sqrt(B) − α·calo/POT.

Two modes (select with --mode):

  michael (default, 4D foil-stack search):
    tsda_rin           Real    [0.001, 130.0]   mm
    tsda_halfLength4   Real    [7.5,   12.5]    cm
    holeRadius         Real    [0.0,   50.0]    mm
    col5               Cat     {"air","poly"}
    Pinned: tsda.r4=600, tsda.z0=4195, materialName=StoppingTarget_Al,
            degrader.build=false, degrader.rotation=120. (mmackenz parked detent)

  helical (4D inner-namespace search, all else pinned at v111):
    tsda.helical.dx          Real [0.01, 5.0]    mm   (ribbon half-width)
    tsda.helical.dy          Real [40,   400]    mm   (ribbon half-height)
    tsda.helical.halflength  Real [25,   500]    mm   (z half-length)
    tsda.helical.angle       Real [60,   540]    deg  (total twist)
    Derived (coupled in render_geom; eliminates silent G4 sibling overlaps):
      tsda.helical.z0 = tsda.z0 + halfLength4 + halflen
                      → plug upstream face touches disc downstream face
      tsda.rin        = ceil(sqrt(dx^2+dy^2)) + 2 mm
                      → disc hole matches plug bounding circle + 2 mm
    Pinned: TSdA core (hL4=12.5, r4=600, z0=4195), foils (38 × r=125, hole=0),
            degrader off, COL5Poly, helical material/nsteps.
    Baseline geom_run1_a.txt + manual TT_MidInner→DS2Vacuum patches (mirrors v111).

Subcommands (both modes):
  show-priors  : load priors, print top-K by objective (no GP fitting required)
  propose      : seed GP, propose next candidate, render geom override file
  evaluate     : after pipeline run, parse summary.json + append to leaderboard
  preflight    : run mu2e -n 1 locally on a proposal to catch G4 init failures

Architecture: BOMode is an ABC; MichaelMode and HelicalMode are the two
adapters. MODES = {name: instance} is the registry argparse selects from.
Adding a third mode = subclass BOMode + add to MODES.
"""
from __future__ import annotations

import argparse
import csv
import fcntl
import json
import re
import shutil
import subprocess
import sys
import tempfile
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path

ROOT = Path("/exp/mu2e/app/users/oksuzian/autoresearch")
GEOM_TSV = Path("/exp/mu2e/data/users/oksuzian/autoresearch_grid/mmackenz_table_plots/geom_params.tsv")
MMACKENZ_WORKFLOWS = Path("/exp/mu2e/app/users/mmackenz/run1b/Run1BAna/workflows")

SETUPMU2E = "/cvmfs/mu2e.opensciencegrid.org/setupmu2e-art.sh"
MUSING = "/cvmfs/mu2e.opensciencegrid.org/Musings/SimJob/Run1Bak/setup.sh"

sys.path.insert(0, str(ROOT / "graph"))
from config import PREFLIGHT_TIMEOUT_S  # noqa: E402

DEFAULT_ALPHA = 1.0e5  # mmackenz calo range 4e-8..2.5e-5; alpha=1e5 makes
                       # 1e-5 calo cost 1 unit of S/sqrt(B). Override per study.


@dataclass
class Point:
    """Generic BO point: x layout depends on mode."""
    cfg: str
    x: list      # mode-specific list of param values
    sob: float
    calo: float

    def obj(self, alpha: float) -> float:
        return self.sob - alpha * self.calo


def _parse_float(s):
    if s is None or s == "" or str(s).lower() in ("none", "nan"):
        return None
    try:
        return float(s)
    except ValueError:
        return None


def _parse_bool(s) -> bool:
    return (s or "").strip().lower() == "true"


# ============================================================================
# BOMode: the seam. Two adapters below (MichaelMode, HelicalMode).
# ============================================================================

class BOMode(ABC):
    """A BO mode = search space + render + prior loader + leaderboard format.

    Each subclass owns its pinned constants and its 5 mode-specific methods
    (load_priors, build_space, _geom_text, parse_geom, format_row,
    load_history_row, print_top). Shared concerns (history I/O, optimizer
    construction, proposal file write) are concrete on this base class.
    """
    name: str
    leaderboard: Path
    proposal_dir: Path
    preflight_dir: Path

    # --- abstract: each concrete mode implements ---
    @abstractmethod
    def load_priors(self) -> list[Point]: ...

    @abstractmethod
    def build_space(self): ...

    @abstractmethod
    def _geom_text(self, x) -> str: ...

    @abstractmethod
    def parse_geom(self, text: str): ...

    @abstractmethod
    def format_row(self, p: Point, alpha: float) -> tuple[str, str]: ...

    @abstractmethod
    def load_history_row(self, row: dict) -> Point: ...

    @abstractmethod
    def print_top(self, pts, alpha, top): ...

    # --- concrete: shared ---
    def render_proposal(self, name: str, x) -> Path:
        self.proposal_dir.mkdir(parents=True, exist_ok=True)
        out = self.proposal_dir / f"{name}_geom.txt"
        out.write_text(self._geom_text(x))
        return out

    def load_history(self) -> list[Point]:
        if not self.leaderboard.exists():
            return []
        out = []
        with self.leaderboard.open() as f:
            for row in csv.DictReader(f, delimiter="\t"):
                try:
                    out.append(self.load_history_row(row))
                except (KeyError, ValueError):
                    continue
        return out

    def append_history(self, p: Point, alpha: float):
        new_file = not self.leaderboard.exists()
        header, line = self.format_row(p, alpha)
        with self.leaderboard.open("a") as f:
            if new_file:
                f.write(header)
            f.write(line)

    def build_optimizer(self):
        from skopt import Optimizer
        space = self.build_space()
        return Optimizer(
            dimensions=space,
            base_estimator="GP",
            acq_func="EI",
            n_initial_points=0,
            random_state=42,
        ), space

    # --- batch BO pending-state (see wiki/concepts/batch-bo.md) ---
    def pending_path(self) -> Path:
        return self.leaderboard.parent / f"pending_bo_{self.name}.tsv"

    def load_pending(self) -> list[tuple[str, list]]:
        pp = self.pending_path()
        if not pp.exists():
            return []
        out = []
        with pp.open() as f:
            for row in csv.DictReader(f, delimiter="\t"):
                try:
                    out.append((row["config"], json.loads(row["x"])))
                except (KeyError, ValueError, json.JSONDecodeError):
                    continue
        return out

    def append_pending(self, name: str, x, alpha: float):
        pp = self.pending_path()
        new = not pp.exists()
        with pp.open("a") as f:
            if new:
                f.write("config\tx\talpha\tsubmitted_at\n")
            f.write(f"{name}\t{json.dumps(list(x))}\t{alpha:.3f}\t{int(time.time())}\n")

    def remove_pending(self, name: str) -> bool:
        pp = self.pending_path()
        if not pp.exists():
            return False
        rows = pp.read_text().splitlines()
        if len(rows) < 2:
            return False
        header, body = rows[0], rows[1:]
        kept = [r for r in body if not r.startswith(name + "\t")]
        if len(kept) == len(body):
            return False
        pp.write_text("\n".join([header] + kept) + ("\n" if kept else ""))
        return True


# ============================================================================
# MichaelMode: 4D foil-stack search
# ============================================================================

class MichaelMode(BOMode):
    name = "michael"
    leaderboard = ROOT / "leaderboard_bo_michael.tsv"
    proposal_dir = ROOT / "bo_michael_proposals"
    preflight_dir = ROOT / "bo_michael_preflight"

    # Pinned constants (matches v22-v50 mmackenz convention)
    TSDA_R4 = 600.0
    TSDA_Z0 = 4195.0
    TSDA_MATERIAL = "StoppingTarget_Al"

    def load_priors(self):
        pts = []
        with GEOM_TSV.open() as f:
            for row in csv.DictReader(f, delimiter="\t"):
                if _parse_bool(row.get("degrader_in_beam")):
                    continue
                sob = _parse_float(row.get("run_1a_ce_s_sqrt_b"))
                calo = _parse_float(row.get("calo_stop_per_pot"))
                rin = _parse_float(row.get("tsda_rin"))
                hL4 = _parse_float(row.get("tsda_halfLength4"))
                hole = _parse_float(row.get("holeRadius"))
                if None in (sob, calo, rin, hL4, hole):
                    continue
                mat = (row.get("coll5_material1") or "").strip()
                col5 = "poly" if mat in ("COL5Poly", "G4_POLYETHYLENE") else "air"
                pts.append(Point(cfg=row["version"], x=[rin, hL4, hole, col5],
                                 sob=sob, calo=calo))
        return pts

    def build_space(self):
        from skopt.space import Real, Categorical
        return [
            Real(0.001, 130.0, name="tsda_rin"),
            Real(7.5,   12.5,  name="tsda_halfLength4"),
            Real(0.0,   50.0,  name="holeRadius"),
            Categorical(["air", "poly"], name="col5"),
        ]

    def _geom_text(self, x) -> str:
        rin, hL4, hole, col5 = x
        col5_mat = "COL5Poly" if col5 == "poly" else "DSVacuum"
        return (
            '#include "Offline/Mu2eG4/geom/geom_run1_a.txt"\n'
            '\n// === autoresearch_bo_michael (michael mode) proposal ===\n'
            f'bool hasTSdA = true;\n'
            f'double tsda.r4         = {self.TSDA_R4:.1f};\n'
            f'double tsda.rin        = {rin:.4f};\n'
            f'double tsda.halfLength4 = {hL4:.4f};\n'
            f'double tsda.z0         = {self.TSDA_Z0:.1f};\n'
            f'string tsda.materialName = "{self.TSDA_MATERIAL}";\n'
            '\n// stopping-target hole\n'
            f'double stoppingTarget.holeRadius = {hole:.4f};\n'
            '\n// degrader: pinned out of beam (120° = mmackenz parked detent)\n'
            f'bool degrader.build      = false;\n'
            f'double degrader.rotation = 120.0;\n'
            '\n// COL5 shield\n'
            f'string ts.coll5.material1Name = "{col5_mat}";\n'
        )

    def parse_geom(self, text: str):
        def _grab(pat, default=None):
            m = re.search(pat, text)
            return m.group(1) if m else default
        mat = _grab(r'ts\.coll5\.material1Name\s*=\s*"(\w+)"')
        return [
            float(_grab(r"tsda\.rin\s*=\s*([\d.eE+-]+)", "0")),
            float(_grab(r"tsda\.halfLength4\s*=\s*([\d.eE+-]+)", "0")),
            float(_grab(r"stoppingTarget\.holeRadius\s*=\s*([\d.eE+-]+)", "0")),
            "poly" if mat in ("COL5Poly", "G4_POLYETHYLENE") else "air",
        ]

    def format_row(self, p: Point, alpha: float) -> tuple[str, str]:
        header = ("config\ttsda_rin\ttsda_halfLength4\tholeRadius\tcol5"
                  "\tsob\tcalo\talpha\tobj\n")
        rin, hL4, hole, col5 = p.x
        line = (f"{p.cfg}\t{rin:.4f}\t{hL4:.4f}\t{hole:.4f}\t{col5}"
                f"\t{p.sob:.5f}\t{p.calo:.5e}\t{alpha:.3f}\t{p.obj(alpha):.5f}\n")
        return header, line

    def load_history_row(self, row: dict) -> Point:
        return Point(cfg=row["config"],
                     x=[float(row["tsda_rin"]), float(row["tsda_halfLength4"]),
                        float(row["holeRadius"]), row["col5"]],
                     sob=float(row["sob"]), calo=float(row["calo"]))

    def print_top(self, pts, alpha, top):
        print(f"{'cfg':>6}  {'rin':>7}  {'hL4':>5}  {'hole':>6}  {'col5':>5}"
              f"  {'sob':>6}  {'calo':>10}  {'obj':>7}")
        for p in pts[:top]:
            rin, hL4, hole, col5 = p.x
            print(f"{p.cfg:>6}  {rin:7.2f}  {hL4:5.2f}"
                  f"  {hole:6.2f}  {col5:>5}"
                  f"  {p.sob:6.3f}  {p.calo:10.3e}  {p.obj(alpha):7.3f}")


# ============================================================================
# HelicalMode: 5D inner-namespace, all else pinned at v111
# ============================================================================

class HelicalMode(BOMode):
    name = "helical"
    # New 4D leaderboard (Option A coupling). Old 5D leaderboard
    # `leaderboard_bo_helical.tsv` is kept as historical; entries there are
    # contaminated by silent disc/plug sibling overlap (see wiki
    # tsda-disc-helical-sibling-overlap).
    leaderboard = ROOT / "leaderboard_bo_helical_v2.tsv"
    proposal_dir = ROOT / "bo_helical_proposals"
    preflight_dir = ROOT / "bo_helical_preflight"

    # Pinned constants (matches v111 exactly except rin, now derived from dx/dy)
    TSDA_R4 = 600.0
    TSDA_HL4 = 12.5
    TSDA_Z0 = 4195.0
    TSDA_MATERIAL = "StoppingTarget_Al"
    HELICAL_NSTEPS = 5000
    HELICAL_MATERIAL = "StoppingTarget_Al"
    FOIL_RADIUS = 125.0
    FOIL_COUNT = 38
    HOLE_RADIUS = 0.0
    RIN_CLEARANCE_MM = 2.0  # extra radial gap between plug bounding circle and disc hole

    KNOB_PATTERNS = {
        "dx":         r"tsda\.helical\.dx\s*=\s*([\d.eE+-]+)",
        "dy":         r"tsda\.helical\.dy\s*=\s*([\d.eE+-]+)",
        "halflength": r"tsda\.helical\.halflength\s*=\s*([\d.eE+-]+)",
        "angle":      r"tsda\.helical\.angle\s*=\s*([\d.eE+-]+)",
    }

    @classmethod
    def _parse_helical_from_text(cls, text: str):
        """Return [dx, dy, halflength, angle] (4D) or None if any missing.

        Ignores tsda.helical.z0 in source — that knob is derived in render_geom
        as of Option A coupling (2026-05-18)."""
        out = []
        for key in ("dx", "dy", "halflength", "angle"):
            m = re.search(cls.KNOB_PATTERNS[key], text)
            if not m:
                return None
            out.append(float(m.group(1)))
        return out

    @classmethod
    def derive_z0(cls, halflength: float) -> float:
        """Touching-disc-face placement: plug upstream face at disc downstream face."""
        return cls.TSDA_Z0 + cls.TSDA_HL4 + halflength

    @classmethod
    def derive_rin(cls, dx: float, dy: float) -> float:
        """Disc hole = ceil(plug bounding circle) + clearance."""
        import math
        return math.ceil(math.sqrt(dx * dx + dy * dy)) + cls.RIN_CLEARANCE_MM

    def load_priors(self):
        """Cross-reference TSV (for sob/calo) with mmackenz geom files (for knobs).

        Note: mmackenz priors used z0 ∈ {4270, 4345, 4470}, NOT the Option-A
        derived z0. The (sob, calo) measurements therefore reflect a different
        physical placement than the current 4D search space would render. We
        keep them as orientation seeds anyway — the bias is acceptable for
        sparse seeding."""
        metrics = {}  # cfg → (sob, calo)
        with GEOM_TSV.open() as f:
            for row in csv.DictReader(f, delimiter="\t"):
                if not _parse_bool(row.get("tsda_helical_build")):
                    continue
                sob = _parse_float(row.get("run_1a_ce_s_sqrt_b"))
                calo = _parse_float(row.get("calo_stop_per_pot"))
                if sob is None or calo is None:
                    continue
                metrics[row["version"]] = (sob, calo)

        pts = []
        for cfg, (sob, calo) in metrics.items():
            geom = MMACKENZ_WORKFLOWS / f"config_{cfg}/run1b_beam/geom.txt"
            if not geom.exists():
                print(f"  warn: missing geom {geom}", file=sys.stderr)
                continue
            x = self._parse_helical_from_text(geom.read_text())
            if x is None:
                print(f"  warn: {cfg} flagged tsda_helical_build but geom missing helical knobs", file=sys.stderr)
                continue
            pts.append(Point(cfg=cfg, x=x, sob=sob, calo=calo))
        return pts

    def build_space(self):
        from skopt.space import Real
        return [
            Real(0.01, 5.0,    name="tsda_helical_dx"),
            Real(40.0, 400.0,  name="tsda_helical_dy"),
            Real(25.0, 500.0,  name="tsda_helical_halflength"),
            Real(60.0, 540.0,  name="tsda_helical_angle"),
        ]

    def _geom_text(self, x) -> str:
        dx, dy, hl, angle = x
        z0 = self.derive_z0(hl)
        rin = self.derive_rin(dx, dy)
        foils = ", ".join(f"{self.FOIL_RADIUS:.1f}" for _ in range(self.FOIL_COUNT))
        return (
            '#include "Offline/Mu2eG4/geom/geom_run1_a.txt"\n'
            '\n// === autoresearch_bo_michael (helical mode, Option A coupling) proposal ===\n'
            '// TSdA core pinned at v111 except rin, coupled to plug bounding radius.\n'
            'bool hasTSdA = true;\n'
            f'double tsda.r4           = {self.TSDA_R4:.1f};\n'
            f'double tsda.rin          = {rin:.4f};   // derived: ceil(sqrt(dx^2+dy^2)) + {self.RIN_CLEARANCE_MM:g} mm\n'
            f'double tsda.halfLength4  = {self.TSDA_HL4:.4f};\n'
            f'double tsda.z0           = {self.TSDA_Z0:.1f};\n'
            f'string tsda.materialName = "{self.TSDA_MATERIAL}";\n'
            '\n// Helical plug (4D BO knobs; z0 derived to touch disc downstream face)\n'
            f'bool   tsda.helical.build      = true;\n'
            f'double tsda.helical.dx         = {dx:.4f};\n'
            f'double tsda.helical.dy         = {dy:.4f};\n'
            f'double tsda.helical.halflength = {hl:.4f};\n'
            f'double tsda.helical.z0         = {z0:.4f};   // derived: tsda.z0 + halfLength4 + halflength\n'
            f'double tsda.helical.angle      = {angle:.4f};\n'
            f'int    tsda.helical.nsteps     = {self.HELICAL_NSTEPS};\n'
            f'string tsda.helical.material   = "{self.HELICAL_MATERIAL}";\n'
            '\n// Foil stack (matches v111: 38 × r=125 to block calo stops)\n'
            f'double stoppingTarget.holeRadius = {self.HOLE_RADIUS:.4f};\n'
            f'vector<double> stoppingTarget.radii = {{ {foils} }};\n'
            '\n// TT_MidInner→DS2Vacuum fix (manually patched, mirrors v111)\n'
            '// geom_run1_a.txt baseline lacks these; needed for run1b_mubeam.\n'
            'bool tracker.inDS2Vacuum = true;\n'
            'double ds2.halfLength = 3825;\n'
            'bool ds.hasServicePipes = false;\n'
            '\n// Other pins (degrader parked at 120° = mmackenz hardware detent)\n'
            'bool degrader.build = false;\n'
            'double degrader.rotation = 120.0;\n'
            'string ts.coll5.material1Name = "COL5Poly";\n'
            '\n// Overlap-suppression (v01 flags; drops 117 surface-check baseline\n'
            '// hits → 1; physics-irrelevant — disables foil support structures\n'
            '// and DS3 rails that have known stock-geometry self-overlaps).\n'
            'bool stoppingTarget.foilTarget_supportStructure = false;\n'
            'double ds.lengthRail2 = 0.1;\n'
            'double ds.lengthRail3 = 0.1;\n'
        )

    def parse_geom(self, text: str):
        return self._parse_helical_from_text(text)

    def format_row(self, p: Point, alpha: float) -> tuple[str, str]:
        header = ("config\tdx\tdy\thalflength\tangle\tz0_derived\trin_derived"
                  "\tsob\tcalo\talpha\tobj\n")
        dx, dy, hl, angle = p.x
        z0 = self.derive_z0(hl)
        rin = self.derive_rin(dx, dy)
        line = (f"{p.cfg}\t{dx:.4f}\t{dy:.4f}\t{hl:.4f}\t{angle:.4f}"
                f"\t{z0:.4f}\t{rin:.4f}"
                f"\t{p.sob:.5f}\t{p.calo:.5e}\t{alpha:.3f}\t{p.obj(alpha):.5f}\n")
        return header, line

    def load_history_row(self, row: dict) -> Point:
        # 4D leaderboard (Option A). z0_derived/rin_derived columns are
        # human-readable derived values, ignored when reconstructing x.
        return Point(cfg=row["config"],
                     x=[float(row["dx"]), float(row["dy"]),
                        float(row["halflength"]), float(row["angle"])],
                     sob=float(row["sob"]), calo=float(row["calo"]))

    def print_top(self, pts, alpha, top):
        print(f"{'cfg':>6}  {'dx':>5}  {'dy':>6}  {'hLen':>6}  {'angle':>6}"
              f"  {'z0~':>7}  {'rin~':>5}"
              f"  {'sob':>6}  {'calo':>10}  {'obj':>7}")
        for p in pts[:top]:
            dx, dy, hl, angle = p.x
            z0 = self.derive_z0(hl)
            rin = self.derive_rin(dx, dy)
            print(f"{p.cfg:>6}  {dx:5.2f}  {dy:6.2f}  {hl:6.2f}  {angle:6.2f}"
                  f"  {z0:7.2f}  {rin:5.1f}"
                  f"  {p.sob:6.3f}  {p.calo:10.3e}  {p.obj(alpha):7.3f}")


MODES: dict[str, BOMode] = {
    "michael": MichaelMode(),
    "helical": HelicalMode(),
}


# ============================================================================
# Subcommands
# ============================================================================

def cmd_show_priors(args):
    mode = MODES[args.mode]
    priors = mode.load_priors()
    print(f"[{mode.name}] loaded {len(priors)} priors with both sob+calo")
    priors.sort(key=lambda p: -p.obj(args.alpha))
    print(f"\nTop-{args.top} by obj = sob - {args.alpha} * calo:")
    mode.print_top(priors, args.alpha, args.top)
    return 0


def cmd_propose(args):
    mode = MODES[args.mode]
    names = args.config_names
    lock_path = mode.leaderboard.parent / f".propose_{mode.name}.lock"
    with lock_path.open("w") as lock_f:
        fcntl.flock(lock_f, fcntl.LOCK_EX)
        return _cmd_propose_locked(args, mode, names)


def _cmd_propose_locked(args, mode, names):
    priors = mode.load_priors()
    history = mode.load_history()
    pending = mode.load_pending()

    existing = {p.cfg for p in history} | {n for n, _ in pending}
    dupes = [n for n in names if n in existing]
    if dupes:
        print(f"ERROR: name(s) already used (in leaderboard or pending): {dupes}",
              file=sys.stderr)
        return 1

    q = len(names)
    print(f"[{mode.name}] seeding GP: {len(priors)} priors + {len(history)} history "
          f"+ {len(pending)} pending (in-flight)")

    opt, space = mode.build_optimizer()
    in_bounds, skipped = 0, 0
    real_ys = []
    for p in priors + history:
        y = -p.obj(args.alpha)
        try:
            opt.tell(p.x, y)
            in_bounds += 1
            real_ys.append(y)
        except ValueError:
            skipped += 1
    print(f"  fed {in_bounds} real points to GP ({skipped} skipped: outside search bounds)")

    # Cross-invocation pending suppression: tell GP each in-flight x with the
    # CL-mean fake y so a separate `propose` call doesn't re-propose them. The
    # within-batch CL-mean below handles diversity inside this single call.
    if pending and real_ys:
        fake_y = sum(real_ys) / len(real_ys)
        suppressed = 0
        for _, px in pending:
            try:
                opt.tell(px, fake_y)
                suppressed += 1
            except ValueError:
                pass
        print(f"  CL-suppressed {suppressed}/{len(pending)} pending points "
              f"(fake y = {fake_y:+.3f})")

    if q == 1:
        xs = [opt.ask()]
    else:
        xs = opt.ask(n_points=q, strategy=args.strategy)
    print(f"\nProposed batch of {q} (strategy={args.strategy if q > 1 else 'sequential'}):")

    for name, x in zip(names, xs):
        print(f"\n  '{name}':")
        for dim, val in zip(space, x):
            print(f"    {dim.name:24s} = {val}")
        geom = mode.render_proposal(name, x)
        # Auto-stage geom into the parametric pipeline's per-config work tree
        # (see wiki/incidents/template-fcl-staleness.md).
        work_geom_dir = Path("/exp/mu2e/data/users/oksuzian/autoresearch_grid") / name / "geom"
        work_geom_dir.mkdir(parents=True, exist_ok=True)
        work_geom = work_geom_dir / f"autoresearch_{name}_geom.txt"
        shutil.copy(geom, work_geom)
        print(f"    geom: {geom}  →  {work_geom}")
        mode.append_pending(name, x, args.alpha)

    print(f"\nPending file: {mode.pending_path()}")
    print(f"\nNext per config (run in parallel):")
    for name in names:
        print(f"  pipeline.py --config {name} submit mubeam   (and run1b_mubeam)")
    print(f"\nThen as each finishes:")
    print(f"  ./autoresearch_bo_michael.py --mode {mode.name} --alpha {args.alpha} "
          f"evaluate <name> <summary.json>")
    return 0


def cmd_list_pending(args):
    mode = MODES[args.mode]
    pending = mode.load_pending()
    print(f"[{mode.name}] pending file: {mode.pending_path()}")
    if not pending:
        print("  (none in flight)")
        return 0
    print(f"  {len(pending)} in flight:")
    for cfg, x in pending:
        print(f"    {cfg:24s}  x = {x}")
    return 0


def cmd_evaluate(args):
    mode = MODES[args.mode]
    summary = json.loads(Path(args.summary).read_text())
    sob = summary.get("s_over_sqrt_b")
    calo = summary.get("calo_per_pot")
    if sob is None or calo is None:
        print(f"summary.json missing s_over_sqrt_b or calo_per_pot: {summary}")
        return 1
    geom = mode.proposal_dir / f"{args.config_name}_geom.txt"
    if not geom.exists():
        print(f"Proposal geom not found: {geom}", file=sys.stderr)
        return 1
    x = mode.parse_geom(geom.read_text())
    if x is None:
        print(f"Failed to parse {mode.name} params from {geom}", file=sys.stderr)
        return 1
    p = Point(cfg=args.config_name, x=x, sob=float(sob), calo=float(calo))
    mode.append_history(p, args.alpha)
    removed = mode.remove_pending(args.config_name)
    pend_tag = "  (cleared from pending)" if removed else ""
    print(f"[{mode.name}] recorded {p.cfg}: sob={p.sob:.3f} calo={p.calo:.3e} "
          f"obj={p.obj(args.alpha):+.3f}  →  {mode.leaderboard}{pend_tag}")
    return 0


PREFLIGHT_FCL_TEMPLATE = """\
#include "Offline/fcl/standardServices.fcl"
#include "Production/JobConfig/common/prolog.fcl"

process_name: PreflightG4Init
source: {{ module_type: EmptyEvent maxEvents: 1 firstRun: 1430 firstSubRun: 0 firstEvent: 1 }}

services: @local::Services.Sim
physics: {{
  producers: {{
    g4run: @local::mu2eg4runDefaultSingleStage
    genCounter: {{ module_type: GenEventCounter }}
  }}
  initPath: [ genCounter, g4run ]
  trigger_paths: [ initPath ]
}}

services.GeometryService.inputFile:  "{geom_basename}"
services.GeometryService.bFieldFile: "Offline/Mu2eG4/geom/bfgeom_DSOff.txt"
services.SeedService.baseSeed: 1
"""

G4_GEOM_FAIL_RX = re.compile(
    r"G4Exception.*?(GeomMgt000\d|GeomVol1002|placement|outside mother|overlap)",
    re.IGNORECASE | re.DOTALL,
)

# Surface-check pass detects silent volume overlaps that wouldn't fail G4 init
# (e.g. TSdA disc vs helical plug as siblings of DS2Vacuum). See wiki:
# external/mu2e-overlap-check + incidents/tsda-disc-helical-sibling-overlap.
SURFACE_CHECK_GEOM_OVERLAY = """\
#include "{base_geom_basename}"

// Activate G4 CheckOverlaps surface sampling.
bool g4.doSurfaceCheck             = true;
int  g4.nSurfaceCheckPointsPercmsq = 1;
int  g4.minSurfaceCheckPoints      = 100;
int  g4.maxSurfaceCheckPoints      = 10000000;
"""

SURFACE_CHECK_FCL = """\
#include "Offline/Mu2eG4/fcl/surfaceCheck.fcl"

services.GeometryService.inputFile : "{geom_basename}"
"""

# G4 CheckOverlaps emits lines like
#   "Overlap is detected for volume <X> ... with [its mother volume] <Y> ..."
# We only care about overlaps that involve volumes our BO knobs touch:
#   - TSdA*       (TSdA disc, TSdA4)
#   - AbsorberPV  (helical-plug placement volume — confirmed via GDML dump)
#   - AbsorberS   (helical-plug solid name in some Mu2e versions)
# Stock Mu2e geometry has ~117 baseline overlap lines (FoilSupportStructure_*
# with StoppingTargetMother; NorthRailDS3 / SouthRailDS3 with DS3Vacuum;
# VirtualDetector_EMC_0_Front with StoppingTargetMother). Whitelisting by
# volume name keeps those out of our failure signal.
SURFACE_OVERLAP_RX = re.compile(r"Overlap is detected for volume\s+(\S+)")
SURFACE_OVERLAP_MANAGED = re.compile(r"^(TSdA|AbsorberPV|AbsorberS)")


def cmd_preflight(args):
    mode = MODES[args.mode]
    name = args.config_name
    geom = mode.proposal_dir / f"{name}_geom.txt"
    if not geom.exists():
        print(f"Proposal geom not found: {geom}", file=sys.stderr)
        return 2

    mode.preflight_dir.mkdir(parents=True, exist_ok=True)
    workdir = Path(tempfile.mkdtemp(prefix=f"preflight_{name}_", dir="/tmp"))
    geom_basename = f"autoresearch_{name}_geom.txt"
    shutil.copyfile(geom, workdir / geom_basename)

    # One G4 init covers both checks. Helical mode uses surfacecheck.fcl
    # which enables g4.doSurfaceCheck=true AND exercises the same init path
    # as preflight.fcl — the prior two-pass design (init, then surface-check)
    # paid for G4 geometry construction twice. Non-helical modes use the
    # lighter preflight.fcl since they don't need overlap diagnostics.
    if mode.name == "helical":
        overlay_basename = f"autoresearch_{name}_surfacecheck_geom.txt"
        (workdir / overlay_basename).write_text(
            SURFACE_CHECK_GEOM_OVERLAY.format(base_geom_basename=geom_basename))
        fcl_basename = "surfacecheck.fcl"
        (workdir / fcl_basename).write_text(
            SURFACE_CHECK_FCL.format(geom_basename=overlay_basename))
    else:
        fcl_basename = "preflight.fcl"
        (workdir / fcl_basename).write_text(
            PREFLIGHT_FCL_TEMPLATE.format(geom_basename=geom_basename))

    log = mode.preflight_dir / f"{name}.log"
    print(f"[preflight/{mode.name}] cfg={name}  workdir={workdir}  log={log}")
    print(f"[preflight/{mode.name}] geom: {geom}  fcl: {fcl_basename}")

    bash_cmd = (
        f"source {SETUPMU2E} >/dev/null 2>&1 && "
        f"source {MUSING}     >/dev/null 2>&1 && "
        f"export MU2E_SEARCH_PATH=\"{workdir}:$MU2E_SEARCH_PATH\" && "
        f"export FHICL_FILE_PATH=\"{workdir}:$FHICL_FILE_PATH\" && "
        f"cd {workdir} && "
        f"mu2e -c {fcl_basename} -n 1"
    )
    try:
        proc = subprocess.run(
            ["bash", "-c", bash_cmd],
            capture_output=True, text=True, timeout=PREFLIGHT_TIMEOUT_S,
        )
        timed_out = False
        out = (proc.stdout or "") + "\n--- STDERR ---\n" + (proc.stderr or "")
        rc = proc.returncode
    except subprocess.TimeoutExpired as e:
        timed_out = True
        out = (e.stdout or "") + "\n--- STDERR ---\n" + (e.stderr or "")
        rc = -1

    log.write_text(out)

    past_init = (
        "BeginRun" in out
        or "Event::beginEvent" in out
        or "EndOfEventAction" in out
        or "Begin processing the 1st record" in out  # art entered event loop
        or "GenParticle" in out                       # produce() ran, asked for input
    )

    print(f"[preflight/{mode.name}] return code: {rc}  timed_out={timed_out}")

    # Helical preflight runs surface-check, which emits G4Exception(GeomVol1002)
    # WWWW warnings on every baseline overlap (~117 hits in stock geometry).
    # These are advisory, not init failures, so the geom_fail regex must only
    # be consulted when geometry construction actually aborted (past_init=False).
    if mode.name == "helical":
        all_hits = SURFACE_OVERLAP_RX.findall(out)
        unique_all = sorted(set(all_hits))
        managed_hits = [v for v in all_hits if SURFACE_OVERLAP_MANAGED.match(v)]
        unique_managed = sorted(set(managed_hits))
        baseline_count = len(all_hits) - len(managed_hits)
        print(f"[preflight/{mode.name}] surface-check "
              f"total_hits={len(all_hits)} unique_volumes={len(unique_all)} "
              f"baseline={baseline_count} managed={len(managed_hits)}")
        if managed_hits:
            print(f"[preflight/{mode.name}] FAIL  managed-volume overlap detected:")
            for v in unique_managed:
                print(f"    {v}")
            for v in unique_managed[:1]:
                m = re.search(rf"Overlap is detected for volume\s+{re.escape(v)}.*", out)
                if m:
                    ctx = out[max(0, m.start() - 100): m.end() + 400]
                    print(f"[preflight/{mode.name}] context:\n{ctx}")
            return 1
        if baseline_count:
            print(f"[preflight/{mode.name}] (info) {baseline_count} known "
                  f"stock-geometry overlaps ({len(unique_all)} unique volumes); "
                  f"ignored — not managed by BO knobs.")

    if not past_init:
        geom_fail = G4_GEOM_FAIL_RX.search(out)
        if geom_fail:
            snippet = out[max(0, geom_fail.start() - 200): geom_fail.end() + 600]
            print(f"[preflight/{mode.name}] FAIL  Geant4 geometry error:\n{snippet}")
            return 1

    if timed_out or rc == 0 or past_init:
        print(f"[preflight/{mode.name}] PASS  init=True; "
              f"no geom-fail signature"
              f"{' and no managed-volume overlap' if mode.name == 'helical' else ''}.")
        return 0

    print(f"[preflight/{mode.name}] AMBIGUOUS  rc={rc}, no geom-fail signature. See {log}")
    print(f"[preflight/{mode.name}] Last 40 lines of log:\n" + "\n".join(out.splitlines()[-40:]))
    return 3


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--mode", choices=list(MODES.keys()), default="michael",
                    help="Search-space mode (default: michael)")
    ap.add_argument("--alpha", type=float, default=DEFAULT_ALPHA,
                    help=f"Scalarization weight (default {DEFAULT_ALPHA})")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p_show = sub.add_parser("show-priors", help="Print top-K priors")
    p_show.add_argument("--top", type=int, default=10)
    p_show.set_defaults(func=cmd_show_priors)

    p_prop = sub.add_parser("propose",
                            help="Propose q≥1 candidate(s) + render geom(s). "
                                 "Pass multiple names for batch BO (CL-mean by default).")
    p_prop.add_argument("config_names", nargs="+",
                        help="One or more proposal names, e.g. `helical003 helical004 helical005`")
    p_prop.add_argument("--strategy", choices=["cl_min", "cl_mean", "cl_max"],
                        default="cl_mean",
                        help="Constant-Liar variant for batches (ignored when q=1)")
    p_prop.set_defaults(func=cmd_propose)

    p_pend = sub.add_parser("list-pending",
                            help="List in-flight proposals (rows in pending_bo_<mode>.tsv)")
    p_pend.set_defaults(func=cmd_list_pending)

    p_eval = sub.add_parser("evaluate", help="Record completed run in leaderboard")
    p_eval.add_argument("config_name")
    p_eval.add_argument("summary", help="path to harvest/summary.json")
    p_eval.set_defaults(func=cmd_evaluate)

    p_pre = sub.add_parser("preflight", help="Run mu2e -n 1 locally to test G4 init feasibility")
    p_pre.add_argument("config_name", help="Proposal name (must exist in proposal dir)")
    p_pre.set_defaults(func=cmd_preflight)

    args = ap.parse_args()
    sys.exit(args.func(args))


if __name__ == "__main__":
    main()
