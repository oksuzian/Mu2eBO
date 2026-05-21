#!/usr/bin/env python3
"""
7D Bayesian Optimization over stopping-target geometry, maximizing Run1A CE S/sqrt(B).

Knobs:
  halfT, nFoils, deltaZ, z0, R_start, R_mid, R_end  (quadratic Lagrange radius profile)

Resumable: reads existing leaderboard_bo.tsv on start, plus seeds from leaderboard.tsv
(the 7 LLM-greedy thickness priors).
"""

import json
import re
import subprocess
import sys
from pathlib import Path

ROOT          = Path("/exp/mu2e/app/users/oksuzian/autoresearch")
WORKFLOWS     = ROOT / "Run1BAna" / "workflows"
RUNS_DIR      = ROOT / "runs"
LEADERBOARD   = ROOT / "leaderboard_bo.tsv"
LEADERBOARD_OLD = ROOT / "leaderboard.tsv"  # 1D thickness scan
LOG_DIR       = ROOT / "loop_logs"
N_FRESH_EVALS = 40
RUN_BASE      = 1800
PARENT_CFG    = "config_v00"
PARENT_RUN    = 1500
HOLE_RADIUS   = 21.5
Z0_LIMIT      = 6500.0
NOISE_FRAC    = 0.02

SETUP = (
    "cd /exp/mu2e/app/users/mmackenz/run1b && "
    "source /cvmfs/mu2e.opensciencegrid.org/setupmu2e-art.sh > /dev/null 2>&1 && "
    "muse setup -q p092 > /dev/null 2>&1 && "
    f"export FHICL_FILE_PATH={ROOT}:$FHICL_FILE_PATH && "
    f"export MU2E_SEARCH_PATH={ROOT}:/cvmfs/mu2e.opensciencegrid.org/Musings/SimJob/Run1Baj/backing:$MU2E_SEARCH_PATH && "
    f"cd {WORKFLOWS}"
)


def quadratic_radii(R_start, R_mid, R_end, N):
    """Lagrange interpolation of N foil radii through 3 control points at u={0, 0.5, 1}."""
    radii = []
    for i in range(N):
        u = i / (N - 1) if N > 1 else 0.5
        L0 = 2 * (u - 0.5) * (u - 1)
        L1 = -4 * u * (u - 1)
        L2 = 2 * u * (u - 0.5)
        r = R_start * L0 + R_mid * L1 + R_end * L2
        r = max(HOLE_RADIUS + 1.0, min(110.0, r))  # clip outside the BO box
        radii.append(r)
    return radii


def feasible(x):
    halfT, nFoils, deltaZ, z0, R_start, R_mid, R_end = x
    nFoils_i = int(round(nFoils))
    if nFoils_i < 2:
        return False
    if z0 + (nFoils_i - 1) * deltaZ > Z0_LIMIT:
        return False
    return True


def write_geom(cfg, x):
    halfT, nFoils, deltaZ, z0, R_start, R_mid, R_end = x
    nFoils_i = int(round(nFoils))
    radii = quadratic_radii(R_start, R_mid, R_end, nFoils_i)
    radii_str = ", ".join(f"{r:.4f}" for r in radii)

    cfg_dir = WORKFLOWS / cfg / "run1a_beam"
    (cfg_dir / "geom.txt").write_text(
        f'#include "Run1BAna/workflows/{cfg}/run1b_beam/geom.txt"\n'
        '\n// Autoresearch BO knobs\n'
        f'vector<double> stoppingTarget.halfThicknesses = {{ {halfT} }};\n'
        f'double stoppingTarget.deltaZ = {deltaZ};\n'
        f'double stoppingTarget.z0InMu2e = {z0};\n'
        f'vector<double> stoppingTarget.radii = {{ {radii_str} }};\n'
    )
    (cfg_dir / "epilog_geom.fcl").write_text(
        f'services.GeometryService.inputFile: "Run1BAna/workflows/{cfg}/run1a_beam/geom.txt"\n'
        'services.GeometryService.bFieldFile: "Offline/Mu2eG4/geom/bfgeom_v01.txt"\n'
    )


def fork_config(cfg, run_no):
    cmd = (
        f"{SETUP} && rm -rf {cfg} && "
        f"./scripts/new_config.sh {cfg} {run_no} {PARENT_CFG} {PARENT_RUN}"
    )
    subprocess.run(["bash", "-c", cmd], check=True, capture_output=True, text=True)


def run_pipeline(cfg):
    log = LOG_DIR / f"{cfg}.log"
    cmd = (
        f"{SETUP} && "
        f"python scripts/run_configuration.py {cfg} 30 --stage run1a_mubeam "
        f"  --run1a-mubeam-events-per-job 5000 --run-root {RUNS_DIR} && "
        f"python scripts/run_configuration.py {cfg} 30 --stage run1a_mustops "
        f"  --mustop-events-per-job 10000 --run-root {RUNS_DIR}"
    )
    with log.open("w") as fh:
        proc = subprocess.run(["bash", "-c", cmd], stdout=fh, stderr=subprocess.STDOUT)
    if proc.returncode != 0:
        raise RuntimeError(f"Pipeline failed for {cfg} (rc={proc.returncode}); see {log}")


def parse_sob(cfg):
    summaries = sorted((RUNS_DIR / cfg).glob("run1a_mustops_*/analysis_summary.json"))
    if not summaries:
        raise RuntimeError(f"No run1a_mustops summary for {cfg}")
    summary = json.loads(summaries[-1].read_text())
    sob = (summary.get("rough_run1a_sensitivity") or {}).get("s_over_sqrt_b")
    if sob is None:
        log_path = summaries[-1].parent / "rough_run1a_sensitivity.log"
        m = re.search(r"S/sqrt\(B\) = ([\d.eE+-]+)\s*$", log_path.read_text(), re.MULTILINE)
        if not m:
            raise RuntimeError(f"S/sqrt(B) not found in {log_path}")
        sob = float(m.group(1))
    return float(sob)


def append_leaderboard(cfg, x, sob):
    halfT, nFoils, deltaZ, z0, R_start, R_mid, R_end = x
    if not LEADERBOARD.exists():
        LEADERBOARD.write_text(
            "# config\thalfT\tnFoils\tdeltaZ\tz0\tR_start\tR_mid\tR_end\tS_over_sqrtB\n"
        )
    with LEADERBOARD.open("a") as fh:
        fh.write(
            f"{cfg}\t{halfT:.5f}\t{int(round(nFoils))}\t{deltaZ:.4f}\t{z0:.2f}"
            f"\t{R_start:.3f}\t{R_mid:.3f}\t{R_end:.3f}\t{sob:.4f}\n"
        )


def read_leaderboard():
    if not LEADERBOARD.exists():
        return []
    rows = []
    for line in LEADERBOARD.read_text().splitlines():
        if line.startswith("#") or not line.strip():
            continue
        p = line.split("\t")
        cfg = p[0]
        x = [float(p[1]), int(p[2]), float(p[3]), float(p[4]), float(p[5]), float(p[6]), float(p[7])]
        sob = float(p[8])
        rows.append((cfg, x, sob))
    return rows


def load_thickness_priors():
    """7 LLM-greedy thickness scan results — all at default geometry except halfT."""
    if not LEADERBOARD_OLD.exists():
        return []
    priors = []
    for line in LEADERBOARD_OLD.read_text().splitlines():
        if line.startswith("#") or not line.strip():
            continue
        cfg, t, sob = line.split("\t")
        x = [float(t), 37, 22.222, 5871.0, 75.0, 75.0, 75.0]
        priors.append((cfg, x, float(sob)))
    return priors


def main():
    LOG_DIR.mkdir(parents=True, exist_ok=True)

    from skopt import Optimizer
    from skopt.space import Real, Integer

    space = [
        Real(0.025, 0.150, name="halfT"),
        Integer(20, 60, name="nFoils"),
        Real(10.0, 30.0, name="deltaZ"),
        Real(5700.0, 6200.0, name="z0"),
        Real(50.0, 100.0, name="R_start"),
        Real(50.0, 100.0, name="R_mid"),
        Real(50.0, 100.0, name="R_end"),
    ]
    opt = Optimizer(
        dimensions=space,
        base_estimator="GP",
        acq_func="EI",
        n_initial_points=0,
        random_state=42,
    )

    # Seed: thickness priors + any existing BO history
    history = read_leaderboard()
    seeded = 0
    for cfg, x, sob in load_thickness_priors():
        opt.tell(x, -sob)
        seeded += 1
    for cfg, x, sob in history:
        opt.tell(x, -sob)
    print(f"Seeded GP with {seeded} thickness priors and {len(history)} existing BO points.")

    start_iter = len(history)
    if start_iter >= N_FRESH_EVALS:
        print(f"Already have {start_iter} BO evals; nothing to do.")
        return 0

    for i in range(start_iter, N_FRESH_EVALS):
        attempts = 0
        while True:
            x = opt.ask()
            attempts += 1
            if feasible(x):
                break
            opt.tell(x, 0.0)  # discourage infeasible region
            if attempts > 30:
                print(f"[iter {i+1}] could not find feasible point after 30 attempts; abort", file=sys.stderr)
                return 1

        halfT, nFoils, deltaZ, z0, R_start, R_mid, R_end = x
        cfg = f"config_bo{i:03d}"
        run_no = RUN_BASE + i

        print(f"\n=== iter {i+1}/{N_FRESH_EVALS}: {cfg} ===")
        print(
            f"   halfT={halfT:.4f}, nFoils={int(round(nFoils))}, "
            f"deltaZ={deltaZ:.2f}, z0={z0:.1f}, "
            f"R=({R_start:.1f},{R_mid:.1f},{R_end:.1f})"
        )

        try:
            fork_config(cfg, run_no)
            write_geom(cfg, x)
            run_pipeline(cfg)
            sob = parse_sob(cfg)
        except Exception as e:
            print(f"   FAILED: {e}", file=sys.stderr)
            opt.tell(x, 0.0)
            continue

        append_leaderboard(cfg, x, sob)
        opt.tell(x, -sob)
        print(f"   S/sqrt(B) = {sob:.4f}")

    history = read_leaderboard()
    history.sort(key=lambda r: -r[2])
    print("\n=== TOP 10 ===")
    for cfg, x, sob in history[:10]:
        halfT, nFoils, deltaZ, z0, R_start, R_mid, R_end = x
        print(
            f"  S/sqrt(B)={sob:.3f}  {cfg}  "
            f"halfT={halfT:.4f} n={int(round(nFoils))} "
            f"dZ={deltaZ:.2f} z0={z0:.1f} "
            f"R=({R_start:.0f},{R_mid:.0f},{R_end:.0f})"
        )
    if history:
        best = history[0]
        print(f"\nBest: {best[0]} -> S/sqrt(B)={best[2]:.4f}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
