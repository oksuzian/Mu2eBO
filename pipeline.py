#!/usr/bin/env python3
"""
Parametric grid pipeline orchestrator for the BO loop.

Single canonical pipeline.py. Pass --config CFG; ROOT, GEOM_FILE, DSCONF,
PNFS_STAGE and per-stage `desc` fields are derived from CFG. Stage templates
live next to this script under pipeline_templates/<stage>/template.fcl with
the geom basename slot marked `__GEOM_FILE__`; submit_stage materializes the
template into <work_root>/<cfg>/state/<stage>_template_materialized.fcl
before handing it to mu2ejobdef.

Per-config working tree (auto-created):
  /exp/mu2e/data/users/oksuzian/autoresearch_grid/<cfg>/
    geom/autoresearch_<cfg>_geom.txt   (placed by autoresearch_bo_michael.py propose)
    <stage>/                           (cnf tarballs, Code.tar.bz2)
    state/                             (cluster IDs, output lists, materialized FCL)
    harvest/                           (summary.json, EdepAna outputs)

Stages run in sequence at a fixed BO knob point:
  mubeam (200) + run1b_mubeam (200) -> concat (1) -> mustops_ce (200) -> harvest

Each stage is its own subcommand so a failed stage can be re-run without redoing
the earlier ones.

Polling uses jobsub_q --user=$USER and direct /pnfs ls.
Outstage convention: /pnfs/mu2e/scratch/users/$USER/workflow/default/outstage/<CLUSTER>/00/<hash>/
"""
from __future__ import annotations

import argparse
import datetime as dt
import fcntl
import hashlib
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import time
from contextlib import contextmanager
from pathlib import Path

# Host-wide lock guarding the mu2ejobsub critical section. condor_vault_storer
# races when N concurrent chains call submit within seconds; serializing the
# token-refresh+submit block eliminates the "Failed to obtain weakened token"
# crashes (see wiki/incidents/concurrent-token-contention.md).
_SUBMIT_LOCK_PATH = Path(f"/tmp/mu2e_submit.{os.environ.get('USER', 'unknown')}.lock")


@contextmanager
def _submit_lock(stage: str):
    """Block until we hold the host-wide submit lock; release on exit."""
    _SUBMIT_LOCK_PATH.touch(exist_ok=True)
    t0 = time.time()
    with open(_SUBMIT_LOCK_PATH, "w") as f:
        fcntl.flock(f.fileno(), fcntl.LOCK_EX)
        waited = time.time() - t0
        if waited > 1.0:
            print(f"[{stage}] acquired submit lock after {waited:.1f}s wait", flush=True)
        try:
            yield
        finally:
            fcntl.flock(f.fileno(), fcntl.LOCK_UN)

# --- Paths fixed at the code-repo level (config-independent) ---
TEMPLATES_ROOT = Path(__file__).resolve().parent / "pipeline_templates"

sys.path.insert(0, str(Path(__file__).resolve().parent / "graph"))
from config import (  # noqa: E402
    GRID_DATA_ROOT as DATA_ROOT,
    MUSING,
    SETUPMU2E,
    STAGE_TARGETS,
)

# Canonical muse-built Code.tar.bz2 produced by `muse tarball` from
# /exp/mu2e/app/users/oksuzian/autoresearch_muse/ (mgit Mu2eG4 sparse
# checkout of v13_12_10 + helical-plug.patch, backed by SimJob/Run1Bak).
# Contains Code/setup.sh that does `muse setup $CODE_DIR -q e29 prof p094`,
# so the local libs (incl. patched libmu2e_Mu2eG4.so with mu2e::makeHelicalPlug)
# win via Muse's normal link/path order — no LD_PRELOAD needed.
# See wiki/external/muse-backing-pattern.md for the build workflow and
# wiki/incidents/calo-constant-across-helical.md for the motivating bug.
MUSE_BASE_TARBALL = Path(
    "/exp/mu2e/app/users/oksuzian/autoresearch_muse/Code_helical_base.tar.bz2"
)
USER = os.environ["USER"]
OUTSTAGE = Path(f"/pnfs/mu2e/scratch/users/{USER}/workflow/default/outstage")

# --- Per-config paths populated by main() once --config is parsed ---
CONFIG: str = ""
ROOT: Path = Path()
STATE: Path = Path()
GEOM_FILE: Path = Path()
DSCONF: str = ""
PNFS_STAGE: Path = Path()


def _bind_config(cfg: str) -> None:
    """Resolve all per-config paths from CFG. Called once by main()."""
    global CONFIG, ROOT, STATE, GEOM_FILE, DSCONF, PNFS_STAGE
    CONFIG = cfg
    ROOT = DATA_ROOT / cfg
    STATE = ROOT / "state"
    GEOM_FILE = ROOT / "geom" / f"autoresearch_{cfg}_geom.txt"
    DSCONF = f"Run1Bak_{cfg}"
    PNFS_STAGE = Path(f"/pnfs/mu2e/scratch/users/{USER}/autoresearch_grid/{cfg}/staged")


# Per-stage knobs (config-invariant). desc_fmt and template path are derived
# at submit time from CONFIG. Inputs that vary per config (geom basename) are
# substituted into the template via __GEOM_FILE__ in submit_stage.
STAGES = {
    "mubeam": {
        "desc_fmt": "Run1A_MuBeam_{cfg}",
        "njobs": STAGE_TARGETS["mubeam"],
        "events_per_job": 5000,
        "run_number": 1800,
        "ships_geom": True,
        "auxinput": f"1:physics.filters.beamResampler.fileNames:{TEMPLATES_ROOT / 'mubeam' / 'MuBeamCat.txt'}",
        "default_loc": "disk",
        "output_glob": "sim.*.TargetStops.*.art",
    },
    "run1b_mubeam": {
        "desc_fmt": "Run1B_MuBeam_{cfg}",
        "njobs": STAGE_TARGETS["run1b_mubeam"],
        "events_per_job": 5000,
        "run_number": 1810,
        "ships_geom": True,
        "auxinput": f"1:physics.filters.beamResampler.fileNames:{TEMPLATES_ROOT / 'run1b_mubeam' / 'MuBeamCat.txt'}",
        "default_loc": "disk",
        "output_glob": "nts.*.mubeam.*.root",
    },
    "concat": {
        "desc_fmt": "Run1A_MuStopsCat_{cfg}",
        "njobs": STAGE_TARGETS["concat"],
        "merge_factor": 200,
        "ships_geom": False,
        "default_loc": "disk",
        "output_glob": "sim.*.MuminusStopsCat.*.art",
    },
    "mustops_ce": {
        "desc_fmt": "Run1A_CeEndpoint_{cfg}",
        # 100 jobs per A/B noise test on helical001 (2026-05-16): half-vs-half
        # ce_seen agreed to 0.4% at 97 jobs each — well below GP noise floor.
        "njobs": STAGE_TARGETS["mustops_ce"],
        # 5000 events/job. Briefly cut to 2500 (2026-05-21 AM) to chase a
        # historical 24–147 min long-pole tail, but that tail was driven by
        # broken-plug stuck-track floods (see [[tessellated-solid-facet-orientation]]);
        # post N_crit-gate the real 5000-event tail is 25–43 min (helicalP01/P03),
        # not a meaningful bottleneck. Reverted same day: ~15 min/round saved
        # wasn't worth the σ(sob) hit 0.10→0.14. Stamping fix protects future
        # mid-flight edits (see [[events-per-job-mid-flight-edit]]).
        "events_per_job": 5000,
        "run_number": 1801,
        "ships_geom": True,
        "default_loc": "disk",
        "output_glob": "dts.*.CeEndpoint.*.art",
        # Default 2000 MB OOMs ~3% of CE jobs (cluster 28166301 had 5/200 held).
        # 2500 MB is the Mu2e community norm — covers the OOM tail without
        # hurting slot matching the way 4000 MB would.
        "memory_mb": 2500,
    },
}


def _stage_desc(stage: str) -> str:
    return STAGES[stage]["desc_fmt"].format(cfg=CONFIG)


def _stage_config_sha(stage: str) -> str:
    """Stable SHA-256 of STAGES[stage] — the per-stage config snapshot.

    Stamped at submit, re-read at harvest. Generalizes the events_per_job
    stamp (which only covered one field) to the whole stage dict.
    Path objects are coerced to str so the serialization is reproducible.
    See wiki/incidents/events-per-job-mid-flight-edit.md.
    """
    payload = json.dumps(STAGES[stage], sort_keys=True, default=str)
    return hashlib.sha256(payload.encode()).hexdigest()


def _stamp_stage_config_sha(stage: str) -> None:
    (STATE / f"{stage}_config_sha.txt").write_text(_stage_config_sha(stage) + "\n")


def _check_stage_config_sha(stage: str) -> None:
    """Warn (do not fail) if STAGES[stage] changed between submit and read.

    Called from cmd_harvest. Silent if no stamp file (legacy chains
    submitted before this guard existed).
    """
    stamp_path = STATE / f"{stage}_config_sha.txt"
    if not stamp_path.exists():
        return
    stamped = stamp_path.read_text().strip()
    current = _stage_config_sha(stage)
    if stamped != current:
        print(
            f"[harvest] WARN: STAGES[{stage!r}] changed since submit "
            f"(stamp={stamped[:12]}, current={current[:12]}). "
            f"Harvest may compute biased metrics; see "
            f"wiki/incidents/events-per-job-mid-flight-edit.md.",
            file=sys.stderr, flush=True,
        )


def _materialize_template(stage: str) -> Path:
    """Read pipeline_templates/<stage>/template.fcl, substitute __GEOM_FILE__,
    write to <STATE>/<stage>_template_materialized.fcl, return that path.
    """
    src = TEMPLATES_ROOT / stage / "template.fcl"
    text = src.read_text()
    materialized = text.replace("__GEOM_FILE__", GEOM_FILE.name)
    out = STATE / f"{stage}_template_materialized.fcl"
    out.write_text(materialized)
    return out


def run(cmd, *, env=None, check=True, capture=True):
    """Run a shell command; print invocation; return CompletedProcess."""
    if isinstance(cmd, list):
        printable = shlex.join(cmd)
    else:
        printable = cmd
    print(f"$ {printable}", flush=True)
    return subprocess.run(
        cmd,
        shell=isinstance(cmd, str),
        env=env,
        check=check,
        capture_output=capture,
        text=True,
    )


def sourced_env(extra="", *, with_muse=False) -> dict:
    """Return an env dict with setupmu2e-art.sh + Run1Bak musing + mu2egrid sourced.

    Use for invoking mu2ejobdef / mu2ejobsub from Python so the child process
    sees the right PATH, MU2E_*_PATH, etc. Set with_muse=True for the harvest
    step which needs the autoresearch-built EdepAna module from mmackenz's
    run1b workspace (matches autoresearch_loop.py SETUP).
    """
    if with_muse:
        # Use our own autoresearch_muse work area (same one that produces the
        # base Code.tar.bz2). `-q p094` is required: without it muse picks
        # p095 from main-HEAD's Offline/.muse and errors on the backing.
        # See wiki/external/muse-backing-pattern.md.
        #
        # EdepAna lives in mmackenz's Run1BAna build (not in Offline/Run1Bak).
        # His HEAD doesn't match v13_12_10 ABI, so we can't rebuild Run1BAna
        # locally without effort. Prepend his lib dir to CET_PLUGIN_PATH +
        # LD_LIBRARY_PATH; harvest is local-only so /exp paths are fine.
        mmlib = "/exp/mu2e/app/users/mmackenz/run1b/build/al9-prof-e29-p094/Run1BAna/lib"
        prelude = (
            "cd /exp/mu2e/app/users/oksuzian/autoresearch_muse && "
            f"source {SETUPMU2E} >/dev/null 2>&1 && "
            "muse setup -q p094  >/dev/null 2>&1 && "
            f"export CET_PLUGIN_PATH={mmlib}:$CET_PLUGIN_PATH && "
            f"export LD_LIBRARY_PATH={mmlib}:$LD_LIBRARY_PATH && "
        )
    else:
        prelude = (
            f"source {SETUPMU2E} >/dev/null 2>&1 && "
            f"source {MUSING}     >/dev/null 2>&1 && "
            f"setup mu2egrid      >/dev/null 2>&1 && "
        )
    cmd = f"{prelude}{extra} env"
    out = subprocess.run(["bash", "-c", cmd], capture_output=True, text=True, check=True)
    env = {}
    for line in out.stdout.splitlines():
        if "=" not in line:
            continue
        k, _, v = line.partition("=")
        env[k] = v
    return env


def write_code_tarball(stage_dir: Path) -> Path:
    """Build Code.tar.bz2 for the --code path.

    Extracts the canonical muse-built base tarball, drops the per-config geom
    file into Code/, writes Code/setup_post.sh to extend MU2E_SEARCH_PATH +
    FHICL_FILE_PATH so the geom is found by GeometryService, then repacks.
    The base tarball's setup.sh handles all framework setup via `muse setup`,
    so local libs win by link/path order (no LD_PRELOAD).
    """
    if not GEOM_FILE.exists():
        raise SystemExit(
            f"geom file missing: {GEOM_FILE}\n"
            f"  Run: ./autoresearch_bo_michael.py --mode <mode> propose {CONFIG}\n"
            f"  (propose auto-stages the geom into the per-config work dir)"
        )
    if not MUSE_BASE_TARBALL.exists():
        raise SystemExit(f"muse base tarball missing: {MUSE_BASE_TARBALL}")
    code_dir = stage_dir / "Code"
    if code_dir.exists():
        shutil.rmtree(code_dir)
    run(["tar", "xjf", str(MUSE_BASE_TARBALL), "-C", str(stage_dir)])
    shutil.copy(GEOM_FILE, code_dir / GEOM_FILE.name)
    (code_dir / "setup_post.sh").write_text(
        'export MU2E_SEARCH_PATH="$CODE_DIR:$MU2E_SEARCH_PATH"\n'
        'export FHICL_FILE_PATH="$CODE_DIR:$FHICL_FILE_PATH"\n'
    )
    tarball = stage_dir / "Code.tar.bz2"
    if tarball.exists():
        tarball.unlink()
    run(["bash", "-c", f"cd {stage_dir} && tar cf - Code/ | bzip2 > {tarball.name}"])
    return tarball


def stage_hardlink_farm(stage: str, source_paths: list[Path]) -> tuple[Path, Path]:
    """Build a /pnfs hard-link farm so all input files appear in one dir.

    Needed because mu2ejobdef's --inputs only accepts basenames, and
    mu2ejobsub's --default-location dir:DIR assumes all files live in DIR.
    Hard links (not symlinks): xrootd doors don't follow /pnfs symlinks, but
    hard links share the same dCache namespace entry. Returns (staged_dir, basenames_file).
    """
    staged_dir = PNFS_STAGE / stage
    if staged_dir.exists():
        for p in staged_dir.iterdir():
            p.unlink()
    else:
        staged_dir.mkdir(parents=True, exist_ok=True)
    basenames = []
    for src in source_paths:
        link = staged_dir / src.name
        os.link(src, link)
        basenames.append(src.name)
    basenames_file = STATE / f"{stage}_basenames.txt"
    basenames_file.write_text("\n".join(basenames) + "\n")
    print(f"[{stage}] hard-linked {len(basenames)} files into {staged_dir}")
    return staged_dir, basenames_file


def submit_stage(stage: str, env: dict, *, inputs_file: Path | None = None,
                 staged_input_dir: Path | None = None, dry_run: bool = False) -> int | None:
    """Build cnf via mu2ejobdef, smoke-test with mu2ejobfcl, submit via mu2ejobsub.

    Returns the cluster id (or None for dry-run).
    """
    cfg = STAGES[stage]
    desc = _stage_desc(stage)
    stage_dir = ROOT / stage
    stage_dir.mkdir(parents=True, exist_ok=True)

    # Materialize the template (substitute geom basename) into state/.
    template_fcl = _materialize_template(stage)

    cnf = stage_dir / f"cnf.{USER}.{desc}.{DSCONF}.0.tar"
    if cnf.exists():
        print(f"[{stage}] removing existing cnf: {cnf.name}")
        cnf.unlink()

    jobdef = ["mu2ejobdef", "--dsconf", DSCONF, "--dsowner", USER, "--desc", desc,
              "--embed", str(template_fcl)]
    if cfg["ships_geom"]:
        tarball = write_code_tarball(stage_dir)
        jobdef += ["--code", str(tarball)]
    else:
        jobdef += ["--setup", MUSING]
    if "events_per_job" in cfg:
        jobdef += ["--run-number", str(cfg["run_number"]),
                   "--events-per-job", str(cfg["events_per_job"])]
        # Stamp the per-stage events_per_job at submit time so harvest reads
        # the actual value used, not the current (possibly edited) dict.
        # Without this, editing STAGES[*]["events_per_job"] between submit
        # and harvest mis-scales ce_simulated_events / mubeam_sim_total
        # → biases sob (helicalP01 false high, 2026-05-21).
        (STATE / f"{stage}_events_per_job.txt").write_text(
            f"{cfg['events_per_job']}\n"
        )
    if "merge_factor" in cfg:
        if inputs_file is None:
            raise SystemExit(f"[{stage}] needs --inputs file but none provided")
        jobdef += ["--inputs", str(inputs_file), "--merge-factor", str(cfg["merge_factor"])]
    if "auxinput" in cfg:
        jobdef += [f"--auxinput={cfg['auxinput']}"]

    # mu2ejobdef writes cnf.* in cwd
    print(f"$ (cd {stage_dir} && {shlex.join(jobdef)})", flush=True)
    subprocess.run(jobdef, cwd=stage_dir, env=env, check=True)

    # smoke-test: ask mu2ejobfcl to print job-0's resolved fcl
    default_loc = f"dir:{staged_input_dir}" if staged_input_dir else cfg["default_loc"]
    fcl_check = ["mu2ejobfcl", "--jobdef", cnf.name, "--index", "0",
                 "--default-proto", "root", "--default-loc", default_loc]
    print(f"$ (cd {stage_dir} && {shlex.join(fcl_check)})", flush=True)
    subprocess.run(fcl_check, cwd=stage_dir, env=env, check=True)

    if dry_run:
        print(f"[{stage}] DRY-RUN: would submit {cfg['njobs']} job(s)")
        return None

    # Host-wide serialization of the token-refresh + submit block. Under
    # concurrent load condor_vault_storer races; the lock guarantees only one
    # process at a time touches the bearer token + mu2ejobsub.
    with _submit_lock(stage):
        print(f"[{stage}] renewing bearer token: mu2einit && getToken", flush=True)
        subprocess.run(
            ["bash", "-c", f"source {SETUPMU2E} >/dev/null 2>&1 && getToken"],
            check=True,
        )

        submit = ["mu2ejobsub", "--jobdef", cnf.name,
                  "--firstjob", "0", "--njobs", str(cfg["njobs"]),
                  "--default-location", default_loc, "--default-protocol", "root",
                  "--predefined-args=al9"]
        if "memory_mb" in cfg:
            submit += ["--memory", f"{cfg['memory_mb']}MB"]
        print(f"[{stage}] submitting: {shlex.join(submit)}")
        out = subprocess.run(submit, cwd=stage_dir, env=env, capture_output=True, text=True, check=True)
        print(out.stdout)
        if out.stderr.strip():
            print("STDERR:", out.stderr, file=sys.stderr)

        # parse "<N> job(s) submitted to cluster <CLUSTER>."
        m = re.search(r"submitted to cluster\s+(\d+)", out.stdout)
        if not m:
            raise SystemExit(f"[{stage}] could not parse cluster id from mu2ejobsub output")
        cluster = int(m.group(1))
        (STATE / f"{stage}_cluster.txt").write_text(f"{cluster}\n")
        _stamp_stage_config_sha(stage)
        print(f"[{stage}] cluster={cluster}")
        return cluster


def poll_cluster(stage: str, cluster: int, *, quorum: float = 0.9, cap_hours: float = 24.0) -> None:
    """Wait until stage-out convergence (or wall-clock cap).

    Convergence = (jobs left queue >= target) AND (settled bare-form
    outstage dirs >= target). Polling jobsub_q alone is a lying proxy:
    jobs exit the queue when they *start finishing*, but stage-out
    (worker -> /pnfs copy + jobsub_lite hash->bare rename) is async and
    lags by minutes. Without the outstage check, list_outputs would race
    with stage-out and SystemExit on a missing base or undercount on a
    partial dir. By gating poll on the same /pnfs ls that list_outputs
    ultimately reads, we make list_outputs's precondition structural,
    not hopeful. See wiki/incidents/stage-out-lag.md.
    """
    cfg = STAGES[stage]
    target = max(1, int(cfg["njobs"] * quorum))
    base = OUTSTAGE / str(cluster) / "00"
    deadline = time.time() + cap_hours * 3600
    while time.time() < deadline:
        out = subprocess.run(
            ["jobsub_q", "-G", "mu2e", f"--user={USER}",
             "--constraint", f"ClusterId=={cluster}"],
            capture_output=True, text=True,
        )
        if out.returncode != 0:
            # Don't silently treat a jobsub_q failure as "queue is empty" - that
            # let the poll claim 200/200 finished within seconds of submission.
            print(f"WARN: jobsub_q rc={out.returncode}; will retry. stderr:\n{out.stderr}",
                  file=sys.stderr)
            time.sleep(60)
            continue
        in_queue = sum(1 for line in out.stdout.splitlines()
                       if re.match(rf"^{cluster}\.\d+@", line))
        finished_q = cfg["njobs"] - in_queue
        if base.exists():
            settled = sum(1 for d in base.iterdir() if d.name.isdigit())
        else:
            settled = 0
        ts = dt.datetime.now().strftime("%H:%M:%S")
        print(f"[{ts}] [{stage} cluster={cluster}] "
              f"queue:{finished_q}/{cfg['njobs']} settled:{settled}/{cfg['njobs']} "
              f"(target={target})", flush=True)
        if finished_q >= target and settled >= target:
            print(f"[{stage}] converged (queue={finished_q}, settled={settled})")
            return
        time.sleep(120)
    print(f"[{stage}] WARN: 24h cap hit, proceeding with whatever landed")


def list_outputs(stage: str, cluster: int) -> list[Path]:
    """Glob outstage for stage outputs; persist as <stage>_outputs.txt.

    Precondition: poll_cluster has converged, so `base` exists with at
    least `quorum * njobs` bare-form subdirs. /pnfs may still be renaming
    a small tail of hash-suffix subdirs; we drain those before globbing
    so bare-only enumeration doesn't undercount. See incidents
    stage-out-lag and stage-out-rename-race.
    """
    cfg = STAGES[stage]
    base = OUTSTAGE / str(cluster) / "00"
    if not base.exists():
        # poll_cluster's convergence gate is supposed to guarantee this.
        # If it fires, the gate has a bug or the cap-hours warning path
        # let us through with nothing on disk - either way, fail loudly.
        raise SystemExit(f"[{stage}] outstage missing after poll converged: {base}")

    pattern = f"[0-9][0-9][0-9][0-9][0-9]/{cfg['output_glob']}"
    for attempt in range(20):  # 20 × 30s = 10 min cap
        pending = [d.name for d in base.iterdir()
                   if "." in d.name and d.name.split(".", 1)[0].isdigit()]
        if not pending:
            break
        print(f"[{stage}] {len(pending)} job dir(s) still mid-rename "
              f"(e.g. {pending[0]}); sleeping 30s "
              f"(attempt {attempt + 1}/20)")
        time.sleep(30)
    else:
        print(f"[{stage}] WARN: rename pass did not quiesce after 10 min; "
              f"globbing bare form anyway (may undercount)")

    files = sorted(base.glob(pattern))
    out_list = STATE / f"{stage}_outputs.txt"
    out_list.write_text("\n".join(str(f) for f in files) + "\n")
    print(f"[{stage}] {len(files)} output file(s) -> {out_list}")
    return files


def cmd_submit(args):
    # Idempotency guard: if a prior submit already produced a cluster file,
    # treat re-entry as a no-op so a killed-and-resumed graph node doesn't
    # double-submit. --force overrides.
    cluster_file = STATE / f"{args.stage}_cluster.txt"
    if cluster_file.exists() and not getattr(args, "force", False):
        cid = cluster_file.read_text().strip()
        print(f"[{args.stage}] already submitted (cluster={cid}); skip submit "
              f"(use --force to override)")
        return
    env = sourced_env()
    inputs_file = None
    staged_input_dir = None
    if args.stage == "concat":
        mubeam_list = STATE / "mubeam_outputs.txt"
        if not mubeam_list.exists():
            raise SystemExit("Run 'list-outputs mubeam' first to populate mubeam_outputs.txt")
        sources = [Path(p) for p in mubeam_list.read_text().splitlines() if p.strip()]
        staged_input_dir, inputs_file = stage_hardlink_farm("concat", sources)
    elif args.stage == "mustops_ce":
        prev = STATE / "concat_outputs.txt"
        if not prev.exists():
            raise SystemExit("Run 'list-outputs concat' first to populate concat_outputs.txt")
        # auxinput list file requires basenames (same restriction as --inputs).
        # Hard-link concat outputs into a /pnfs stage dir so xrootd can resolve them
        # when --default-location dir:STAGED expands the basenames.
        sources = [Path(p) for p in prev.read_text().splitlines() if p.strip()]
        staged_input_dir, basenames_file = stage_hardlink_farm("mustops_ce", sources)
        STAGES["mustops_ce"]["auxinput"] = (
            f"1:physics.filters.TargetStopResampler.fileNames:{basenames_file}"
        )
    submit_stage(args.stage, env, inputs_file=inputs_file,
                 staged_input_dir=staged_input_dir, dry_run=args.dry_run)


def cmd_poll(args):
    cluster_file = STATE / f"{args.stage}_cluster.txt"
    cluster = int(cluster_file.read_text().strip())
    poll_cluster(args.stage, cluster, quorum=args.quorum, cap_hours=args.cap_hours)


def cmd_list_outputs(args):
    # Idempotency guard: if outputs were already listed and every basename
    # still resolves on /pnfs, skip the re-glob. --force overrides.
    outputs_file = STATE / f"{args.stage}_outputs.txt"
    if outputs_file.exists() and not getattr(args, "force", False):
        paths = [p for p in outputs_file.read_text().splitlines() if p.strip()]
        if paths and all(Path(p).exists() for p in paths):
            print(f"[{args.stage}] outputs already listed ({len(paths)} files); "
                  f"skip (use --force to override)")
            return
    cluster_file = STATE / f"{args.stage}_cluster.txt"
    cluster = int(cluster_file.read_text().strip())
    list_outputs(args.stage, cluster)


def cmd_materialize(args):
    """Debug helper: write the materialized template to --out (or stdout)."""
    out = _materialize_template(args.stage)
    if args.out:
        Path(args.out).write_text(out.read_text())
        print(f"[{args.stage}] materialized -> {args.out}")
    else:
        sys.stdout.write(out.read_text())


# Constant from extract_analysis_results._MUBEAM_INPUT_EFFICIENCY_BY_FCL["run1a_beam/mubeam.fcl"].
# This is the fraction of upstream POT that survive into the MuBeamCat resampler input,
# needed to convert per-simulated-event yields into per-POT yields.
RUN1A_MUBEAM_INPUT_CORRECTION = 0.01278168

# Path to the autoresearch repo so we can find the EdepAna fcl + ROOT macro.
AUTORESEARCH = Path("/exp/mu2e/app/users/oksuzian/autoresearch")
EDEP_FCL = AUTORESEARCH / "Run1BAna/workflows/fcl/edep.fcl"
SENSITIVITY_MACRO = AUTORESEARCH / "Run1BAna/workflows/scripts/rough_run1a_sensitivity.C"

_EDEP_SAW_RX = re.compile(r"EdepAna summary:\s*Saw\s+(\d+)\s+events")
_S_OVER_SQRTB_RX = re.compile(r"^Signal box.*S/sqrt\(B\)\s*=\s*([\d.eE+-]+)\s*$", re.MULTILINE)

# TargetMuonFinder/stopmat bin labels (mmackenz extract_analysis_results._CALO_STOP_MATERIALS)
_CALO_STOP_MATERIALS = ("G4_CESIUM_IODIDE", "CarbonFiber", "AluminumHoneycomb")


_CALO_EXTRACT_SCRIPT = r"""
import json, sys
import ROOT
files = json.loads(sys.stdin.read())
mats = set({mats!r})
total_calo = 0.0
files_seen = 0
for path in files:
    tfile = ROOT.TFile.Open(path, "READ")
    if not tfile or tfile.IsZombie():
        continue
    hist = tfile.Get("TargetMuonFinder/stopmat")
    if not hist:
        tfile.Close()
        continue
    files_seen += 1
    xaxis = hist.GetXaxis()
    for b in range(1, xaxis.GetNbins() + 1):
        if xaxis.GetBinLabel(b) in mats:
            total_calo += float(hist.GetBinContent(b))
    tfile.Close()
print(json.dumps({{"total_calo": total_calo, "files_seen": files_seen}}))
"""


def _events_per_job(stage: str) -> int:
    """Resolve the per-stage events_per_job actually used at submit time.

    Reads STATE/<stage>_events_per_job.txt (stamped by submit_stage). Falls back
    to STAGES[stage]["events_per_job"] for chains submitted before the stamping
    fix landed (2026-05-21). Without this, editing STAGES[*]["events_per_job"]
    between submit and harvest mis-scales metrics — see helicalP01 incident.
    """
    stamp = STATE / f"{stage}_events_per_job.txt"
    if stamp.exists():
        return int(stamp.read_text().strip())
    return STAGES[stage]["events_per_job"]


def _extract_calo_per_pot(run1b_files, env):
    """Sum TargetMuonFinder/stopmat calo bins across run1b_mubeam nts files.

    Returns calo_per_pot = (sum calo entries / total simulated events) * input_corr.
    Mirrors mmackenz extract_analysis_results._extract_target_al_entries.

    PyROOT requires the muse env (PYTHONPATH on cvmfs); this process was launched
    without it, so we shell out to a python subprocess that inherits `env`.
    """
    if not run1b_files:
        return None, None, None
    # Use len(run1b_files), not STAGES.njobs — same OOM-bias rationale as ce branch.
    total_events = len(run1b_files) * _events_per_job("run1b_mubeam")

    script = _CALO_EXTRACT_SCRIPT.format(mats=list(_CALO_STOP_MATERIALS))
    proc = subprocess.run(
        ["python3", "-c", script],
        input=json.dumps([str(p) for p in run1b_files]),
        env=env, capture_output=True, text=True, check=True,
    )
    result = json.loads(proc.stdout.strip().splitlines()[-1])
    total_calo = result["total_calo"]
    files_seen = result["files_seen"]
    if files_seen == 0:
        return None, None, None
    calo_per_event = total_calo / total_events
    calo_per_pot = calo_per_event * RUN1A_MUBEAM_INPUT_CORRECTION
    return calo_per_pot, total_calo, files_seen


def _count_events_art(art_path: Path, env: dict, harvest_dir: Path) -> int:
    """Run a tiny mu2e job that just opens art_path and reports events."""
    fcl = harvest_dir / "count_events.fcl"
    fcl.write_text(
        '#include "Offline/fcl/minimalMessageService.fcl"\n'
        "process_name: count\n"
        "source: { module_type: RootInput }\n"
        "services: { message: @local::default_message }\n"
        "physics: {}\n"
    )
    log = harvest_dir / f"count_{art_path.stem}.log"
    proc = subprocess.run(
        ["mu2e", "-c", str(fcl), "-s", str(art_path), "-n", "-1"],
        cwd=harvest_dir, env=env, capture_output=True, text=True, check=True,
    )
    log.write_text(proc.stdout + "\n=== STDERR ===\n" + proc.stderr)
    m = re.search(r"TrigReport Events total =\s*(\d+)", proc.stdout)
    if not m:
        raise SystemExit(f"could not parse event count from {art_path} (see {log})")
    return int(m.group(1))


def cmd_harvest(args):
    """Compute s_over_sqrt_b from the smoke pipeline outputs.

    Steps (mirrors extract_analysis_results.run_rough_run1a_sensitivity_analysis):
      1. Run EdepAna on mustops_ce CeEndpoint art files -> nts ROOT + 'Saw N' line
      2. Count events in concat MuminusStopsCat -> muminus_stops_events
      3. ce_scale = input_corr * (muminus_stops / mubeam_sim_total) / ce_simulated_events
         ce_abs_eff = ce_seen * ce_scale
      4. Run rough_run1a_sensitivity.C -> parse 'S/sqrt(B) = X'
    """
    for stage in ("mubeam", "run1b_mubeam", "concat", "mustops_ce"):
        _check_stage_config_sha(stage)
    env = sourced_env(with_muse=True)
    harvest_dir = ROOT / "harvest"
    harvest_dir.mkdir(parents=True, exist_ok=True)

    ce_files = [Path(p) for p in (STATE / "mustops_ce_outputs.txt").read_text().splitlines() if p.strip()]
    concat_files = [Path(p) for p in (STATE / "concat_outputs.txt").read_text().splitlines() if p.strip()]
    if not ce_files:
        raise SystemExit("No mustops_ce outputs to harvest")
    muminus_files = [f for f in concat_files if "MuminusStopsCat" in f.name]
    if not muminus_files:
        raise SystemExit("No MuminusStopsCat in concat outputs")

    # Derive denominators from the actual files we'll harvest, not STAGES.njobs
    # — if any grid jobs were lost (OOM, held), STAGES.njobs over-counts and biases
    # ce_abs_eff / s_over_sqrt_b high by the loss fraction. See A/B test on
    # helical001 (2026-05-16) which surfaced this.
    mubeam_files = [Path(p) for p in (STATE / "mubeam_outputs.txt").read_text().splitlines() if p.strip()]
    mubeam_sim_total = len(mubeam_files) * _events_per_job("mubeam")
    ce_simulated_events = len(ce_files) * _events_per_job("mustops_ce")

    print(">>> Step 1: EdepAna on CeEndpoint outputs")
    ce_list = harvest_dir / "ce_files.txt"
    ce_list.write_text("\n".join(str(p) for p in ce_files) + "\n")
    nts_path = harvest_dir / "nts.ce.root"
    wrapper = harvest_dir / "edep_wrapper.fcl"
    wrapper.write_text(
        f'#include "{EDEP_FCL.relative_to(AUTORESEARCH).as_posix()}"\n'
        f'services.TFileService.fileName: "{nts_path.name}"\n'
    )
    edep_log = harvest_dir / "edep.log"
    proc = subprocess.run(
        ["mu2e", "-c", str(wrapper), "-S", str(ce_list)],
        cwd=harvest_dir, env={**env, "FHICL_FILE_PATH": f"{AUTORESEARCH}:{env.get('FHICL_FILE_PATH','')}"},
        capture_output=True, text=True, check=False,
    )
    edep_log.write_text(proc.stdout + "\n=== STDERR ===\n" + proc.stderr)
    if proc.returncode != 0:
        raise SystemExit(f"EdepAna failed (rc={proc.returncode}); see {edep_log}")
    m = _EDEP_SAW_RX.search(proc.stdout)
    if not m:
        raise SystemExit(f"EdepAna 'Saw N events' summary not found; see {edep_log}")
    ce_seen = int(m.group(1))

    print(">>> Step 2: counting events in MuminusStopsCat")
    muminus_stops = sum(_count_events_art(f, env, harvest_dir) for f in muminus_files)

    stopping_factor = muminus_stops / mubeam_sim_total
    ce_scale = RUN1A_MUBEAM_INPUT_CORRECTION * stopping_factor / ce_simulated_events
    ce_abs_eff = ce_seen * ce_scale

    print(f"    ce_seen             = {ce_seen}")
    print(f"    muminus_stops       = {muminus_stops}")
    print(f"    mubeam_sim_total    = {mubeam_sim_total}")
    print(f"    ce_simulated_events = {ce_simulated_events}")
    print(f"    stopping_factor     = {stopping_factor:.6g}")
    print(f"    ce_abs_eff          = {ce_abs_eff:.6g}")

    print(">>> Step 4: rough_run1a_sensitivity.C")
    macro_log = harvest_dir / "rough_run1a_sensitivity.log"
    cwd = SENSITIVITY_MACRO.parent.parent
    cmd = ["root", "-q", "-b", "-l",
           f'scripts/rough_run1a_sensitivity.C("{nts_path}", {ce_abs_eff:.16g}, "{harvest_dir}")']
    proc = subprocess.run(cmd, cwd=cwd, env=env, capture_output=True, text=True, check=False)
    macro_log.write_text(proc.stdout + "\n=== STDERR ===\n" + proc.stderr)
    if proc.returncode != 0:
        raise SystemExit(f"rough_run1a_sensitivity.C failed (rc={proc.returncode}); see {macro_log}")
    m = _S_OVER_SQRTB_RX.search(proc.stdout)
    if not m:
        raise SystemExit(f"S/sqrt(B) not found in macro output; see {macro_log}")
    s_over_sqrt_b = float(m.group(1))

    print(">>> Step 5: TargetMuonFinder/stopmat from run1b_mubeam outputs")
    run1b_outputs = STATE / "run1b_mubeam_outputs.txt"
    calo_per_pot = None
    calo_total = None
    calo_files_seen = None
    if run1b_outputs.exists():
        run1b_files = [Path(p) for p in run1b_outputs.read_text().splitlines() if p.strip()]
        try:
            calo_per_pot, calo_total, calo_files_seen = _extract_calo_per_pot(run1b_files, env)
        except Exception as e:  # noqa: BLE001
            print(f"    calo extraction failed: {e}")
    if calo_per_pot is not None:
        print(f"    calo_total          = {calo_total}")
        print(f"    calo_files_seen     = {calo_files_seen}")
        print(f"    calo_per_pot        = {calo_per_pot:.6g}")
    else:
        print("    calo_per_pot        = (unavailable)")

    summary = {
        "config": CONFIG,
        "ce_seen": ce_seen,
        "muminus_stops": muminus_stops,
        "mubeam_sim_total": mubeam_sim_total,
        "ce_simulated_events": ce_simulated_events,
        "stopping_factor": stopping_factor,
        "ce_abs_eff": ce_abs_eff,
        "s_over_sqrt_b": s_over_sqrt_b,
        "calo_per_pot": calo_per_pot,
        "calo_total": calo_total,
        "calo_files_seen": calo_files_seen,
        "nts_path": str(nts_path),
        "edep_log": str(edep_log),
        "macro_log": str(macro_log),
    }
    (harvest_dir / "summary.json").write_text(json.dumps(summary, indent=2))
    print("\n" + json.dumps(summary, indent=2))


def main():
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--config", required=True,
                   help="BO config name (e.g. helical001). Selects per-config work tree under "
                        f"{DATA_ROOT}/<config>/")
    sub = p.add_subparsers(dest="cmd", required=True)

    p_sub = sub.add_parser("submit", help="Submit one stage")
    p_sub.add_argument("stage", choices=list(STAGES))
    p_sub.add_argument("--dry-run", action="store_true")
    p_sub.add_argument("--force", action="store_true",
                       help="Re-submit even if state/<stage>_cluster.txt exists.")
    p_sub.set_defaults(func=cmd_submit)

    p_poll = sub.add_parser("poll", help="Poll a stage's cluster until quorum or cap")
    p_poll.add_argument("stage", choices=list(STAGES))
    p_poll.add_argument("--quorum", type=float, default=0.9)
    p_poll.add_argument("--cap-hours", type=float, default=24.0)
    p_poll.set_defaults(func=cmd_poll)

    p_ls = sub.add_parser("list-outputs", help="Glob outstage and persist file list")
    p_ls.add_argument("stage", choices=list(STAGES))
    p_ls.add_argument("--force", action="store_true",
                      help="Re-glob even if state/<stage>_outputs.txt validates.")
    p_ls.set_defaults(func=cmd_list_outputs)

    p_harv = sub.add_parser("harvest", help="Aggregate stage outputs into summary.json")
    p_harv.set_defaults(func=cmd_harvest)

    p_mat = sub.add_parser("materialize",
                           help="Debug: write a stage's materialized template (geom basename substituted)")
    p_mat.add_argument("stage", choices=list(STAGES))
    p_mat.add_argument("--out", help="Output path (default stdout)")
    p_mat.set_defaults(func=cmd_materialize)

    args = p.parse_args()
    _bind_config(args.config)
    ROOT.mkdir(parents=True, exist_ok=True)
    STATE.mkdir(parents=True, exist_ok=True)
    args.func(args)


if __name__ == "__main__":
    main()
