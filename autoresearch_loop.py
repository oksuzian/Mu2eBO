#!/usr/bin/env python3
"""
Autoresearch loop: 1D LLM-guided scan over stopping-target foil half-thickness,
maximizing Run1A CE S/sqrt(B). Resumable — reads existing leaderboard.tsv on start.
"""

import json
import os
import re
import subprocess
import sys
from pathlib import Path

ROOT          = Path("/exp/mu2e/app/users/oksuzian/autoresearch")
WORKFLOWS     = ROOT / "Run1BAna" / "workflows"
RUNS_DIR      = ROOT / "runs"
LEADERBOARD   = ROOT / "leaderboard.tsv"
PROGRAM_MD    = ROOT / "program.md"
LOG_DIR       = ROOT / "loop_logs"
N_ITER        = 10
RUN_BASE      = 1700
PARENT_CFG    = "config_v00"
PARENT_RUN    = 1500
T_RANGE       = (0.025, 0.150)
LITELLM_URL   = "https://litellm.fnal.gov/v1"
MODEL         = "azure/claude-opus-4-7"
KEY_FILE      = Path("~/an.txt").expanduser()

# bash chain that sets up the mu2e env. Each subprocess.run for mu2e jobs
# runs this first via "bash -c '<setup> && <cmd>'" so env is fresh & explicit.
SETUP = (
    "cd /exp/mu2e/app/users/mmackenz/run1b && "
    "source /cvmfs/mu2e.opensciencegrid.org/setupmu2e-art.sh > /dev/null 2>&1 && "
    "muse setup > /dev/null 2>&1 && "
    f"export FHICL_FILE_PATH={ROOT}:$FHICL_FILE_PATH && "
    f"export MU2E_SEARCH_PATH={ROOT}:$MU2E_SEARCH_PATH && "
    f"cd {WORKFLOWS}"
)


def read_leaderboard():
    if not LEADERBOARD.exists():
        return []
    rows = []
    for line in LEADERBOARD.read_text().splitlines():
        if line.startswith("#") or not line.strip():
            continue
        cfg, t, sob = line.split("\t")
        rows.append((cfg, float(t), float(sob)))
    return rows


def append_leaderboard(cfg, t, sob):
    if not LEADERBOARD.exists():
        LEADERBOARD.write_text("# config\thalf_thickness_mm\tS_over_sqrtB\n")
    with LEADERBOARD.open("a") as fh:
        fh.write(f"{cfg}\t{t}\t{sob}\n")


def llm_propose(history):
    from openai import OpenAI
    client = OpenAI(
        base_url=LITELLM_URL,
        api_key=KEY_FILE.read_text().strip(),
    )
    program = PROGRAM_MD.read_text()
    if history:
        hist_str = "\n".join(
            f"  - half_thickness={t:.4f} mm -> S/sqrt(B)={s:.4f}" for _, t, s in history
        )
    else:
        hist_str = "  (none yet)"

    prompt = (
        f"{program}\n\n"
        f"## History so far ({len(history)} of {N_ITER})\n{hist_str}\n\n"
        f"Propose the next half-thickness in mm to try. "
        f"Strictly inside [{T_RANGE[0]}, {T_RANGE[1]}]."
    )
    resp = client.chat.completions.create(
        model=MODEL,
        max_tokens=300,
        messages=[{"role": "user", "content": prompt}],
    )
    text = resp.choices[0].message.content.strip()
    m = re.search(r'\{.*?"thickness"\s*:\s*([0-9.eE+-]+).*?\}', text, re.DOTALL)
    if not m:
        raise RuntimeError(f"Could not parse LLM JSON: {text!r}")
    obj = json.loads(m.group(0))
    t = float(obj["thickness"])
    if not (T_RANGE[0] <= t <= T_RANGE[1]):
        raise RuntimeError(f"Proposed thickness {t} out of range")
    # avoid near-duplicates
    for _, prev_t, _ in history:
        if abs(prev_t - t) < 0.005:
            raise RuntimeError(
                f"Proposed {t} too close to previously tried {prev_t} (<0.005 apart)"
            )
    return t, obj.get("rationale", "")


def fork_config(cfg, run_no):
    cmd = (
        f"{SETUP} && rm -rf {cfg} && "
        f"./scripts/new_config.sh {cfg} {run_no} {PARENT_CFG} {PARENT_RUN}"
    )
    subprocess.run(["bash", "-c", cmd], check=True, capture_output=True, text=True)


def write_geom(cfg, half_t):
    cfg_dir = WORKFLOWS / cfg / "run1a_beam"
    (cfg_dir / "geom.txt").write_text(
        f'#include "Run1BAna/workflows/{cfg}/run1b_beam/geom.txt"\n'
        '\n// Autoresearch thickness override\n'
        f'vector<double> stoppingTarget.halfThicknesses = {{ {half_t} }};\n'
    )
    (cfg_dir / "epilog_geom.fcl").write_text(
        f'services.GeometryService.inputFile: "Run1BAna/workflows/{cfg}/run1a_beam/geom.txt"\n'
        'services.GeometryService.bFieldFile: "Offline/Mu2eG4/geom/bfgeom_v01.txt"\n'
    )


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


def main():
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    history = read_leaderboard()
    if len(history) >= N_ITER:
        print(f"Already have {len(history)} iterations; nothing to do.")
        return 0

    for i in range(len(history), N_ITER):
        try:
            t, rationale = llm_propose(history)
        except Exception as e:
            print(f"[iter {i+1}] LLM proposal error: {e}", file=sys.stderr)
            return 1

        cfg     = f"config_t{int(round(t * 10000)):04d}"
        run_no  = RUN_BASE + i

        print(f"\n=== iter {i+1}/{N_ITER}: {cfg} (t={t:.4f} mm) ===")
        print(f"   rationale: {rationale}")

        try:
            fork_config(cfg, run_no)
            write_geom(cfg, t)
            run_pipeline(cfg)
            sob = parse_sob(cfg)
        except Exception as e:
            print(f"   FAILED: {e}", file=sys.stderr)
            continue

        append_leaderboard(cfg, t, sob)
        history = read_leaderboard()
        print(f"   S/sqrt(B) = {sob:.4f}")

    history.sort(key=lambda r: -r[2])
    print("\n=== FINAL LEADERBOARD ===")
    for cfg, t, sob in history:
        print(f"  {cfg}: t={t:.4f} mm, S/sqrt(B)={sob:.4f}")
    if history:
        best = history[0]
        print(f"\nBest: {best[0]} (t={best[1]:.4f} mm) -> S/sqrt(B)={best[2]:.4f}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
