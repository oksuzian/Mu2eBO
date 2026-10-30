"""Campaign reports: start the reporting agent (the mu2ebo-reporter sibling
checkout, wiki/drivers/reporter.md) on one campaign, and read back the
reports it wrote.

graph/closed_loop.py starts one at every loop exit (trigger "exit"); the
autoresearch MCP server's start_report starts one when the driving agent
asks (trigger "milestone"). Each report is a detached job with its own
directory, <GRAPH_DATA>/<prefix>/reports/<stamp>-<trigger>/: job.json, lock,
log, out/ (the reporter's report.md, facts.json, check.json, run.json) and
rc, written last. The job holds lock for as long as it lives (the pattern of
service/jobs.py), so a report outlives the loop that started it, and a
killed one reads as "lost".

Stdlib only, plus core/paths.py.
"""
from __future__ import annotations

import fcntl
import json
import os
import secrets
import subprocess
import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional

import paths

CHECKOUT_ENV = "AUTORESEARCH_REPORTER"   # the mu2ebo-reporter checkout
LAUNCHER = Path("bin") / "mu2ebo-report"
TRIGGERS = ("exit", "milestone")
REPORTS = "reports"
JOB_SCRIPT = ('"$2" report --prefix "$3" --study "$4" --trigger "$5" '
              '--note "$6" --data-root "$7" --out "$1/out" >"$1/log" 2>&1; '
              'echo $? >"$1/rc.tmp" && mv "$1/rc.tmp" "$1/rc"')
# The reporter's exit codes: 0 every number checked, 1 a number the tools
# did not return (the report is still written), anything else no report.
CHECKED, FLAGGED = 0, 1


def launcher(env: Optional[Mapping[str, str]] = None) -> Optional[Path]:
    """The reporter's launcher in the checkout $AUTORESEARCH_REPORTER
    names, or None."""
    root = (os.environ if env is None else env).get(CHECKOUT_ENV)
    if not root:
        return None
    exe = Path(root) / LAUNCHER
    return exe if os.access(exe, os.X_OK) else None


def problem(env: Optional[Mapping[str, str]] = None) -> Optional[str]:
    """Why no report could be started, or None."""
    root = (os.environ if env is None else env).get(CHECKOUT_ENV)
    if not root:
        return (f"{CHECKOUT_ENV} is not set: clone the reporting agent beside "
                f"this repo (QUICKSTART: mu2ebo-reporter) and source "
                f"activate.sh (--no-report silences this)")
    if launcher(env) is None:
        return (f"{CHECKOUT_ENV}={root} has no executable {LAUNCHER}: not a "
                f"mu2ebo-reporter checkout")
    return None


def reports_dir(camp_path: Path) -> Path:
    return Path(camp_path) / REPORTS


def start(camp_path: Path, study: str, trigger: str, note: str = "",
          env: Optional[Mapping[str, str]] = None) -> Dict[str, Any]:
    """Start a report on the campaign at <GRAPH_DATA>/<prefix>; returns
    {report_id, dir, pid} at once. ValueError when it cannot start."""
    if trigger not in TRIGGERS:
        raise ValueError(f"trigger must be one of {TRIGGERS}, got {trigger!r}")
    env = dict(os.environ if env is None else env)
    why = problem(env)
    if why:
        raise ValueError(why)
    camp_path = Path(camp_path)
    prefix = camp_path.name
    report_id = (f"{time.strftime('%Y%m%d-%H%M%S')}-{trigger}-"
                 f"{secrets.token_hex(2)}")
    job_dir = reports_dir(camp_path) / report_id
    job_dir.mkdir(parents=True, exist_ok=False)
    data_root = camp_path.parent.parent    # GRAPH_DATA is <data root>/...
    env.update(MU2EBO_ROOT=str(paths.REPO_ROOT), PYTHONPATH="")
    args = [str(launcher(env)), prefix, study, trigger, note, str(data_root)]
    fd = os.open(job_dir / "lock", os.O_CREAT | os.O_RDWR, 0o644)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
        proc = subprocess.Popen(
            ["bash", "-c", JOB_SCRIPT, "_", str(job_dir), *args],
            cwd=paths.REPO_ROOT, env=env, stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            start_new_session=True, pass_fds=(fd,))
    finally:
        os.close(fd)
    threading.Thread(target=proc.wait, daemon=True).start()
    info = {"report_id": report_id, "prefix": prefix, "study": study,
            "trigger": trigger, "note": note, "dir": str(job_dir),
            "pid": proc.pid, "started": time.time()}
    (job_dir / "job.json").write_text(json.dumps(info, indent=1) + "\n")
    return info


def _held(lock: Path) -> bool:
    try:
        fd = os.open(lock, os.O_RDONLY)
    except FileNotFoundError:
        return False
    try:
        fcntl.flock(fd, fcntl.LOCK_SH | fcntl.LOCK_NB)
    except BlockingIOError:
        return True
    finally:
        os.close(fd)
    return False


def status(job_dir: Path) -> Dict[str, Any]:
    """One report: {report_id, trigger, state ("running" | "done" | "lost"),
    exit_code, checked, report, unsupported, note, started}."""
    job_dir = Path(job_dir)
    try:
        job = json.loads((job_dir / "job.json").read_text())
    except (OSError, ValueError):
        job = {"report_id": job_dir.name}
    rc = job_dir / "rc"
    # rc first, then the lock, then rc again: a job that ends between the
    # two reads is done, never lost.
    if rc.exists():
        state = "done"
    elif _held(job_dir / "lock"):
        state = "running"
    else:
        state = "done" if rc.exists() else "lost"
    out = {"report_id": job.get("report_id"), "trigger": job.get("trigger"),
           "note": job.get("note"), "started": job.get("started"),
           "state": state, "exit_code": None, "checked": None,
           "report": None, "unsupported": None}
    if state == "done":
        out["exit_code"] = int(rc.read_text().strip() or -1)
        md = job_dir / "out" / "report.md"
        out["report"] = str(md) if md.exists() else None
        out["checked"] = out["exit_code"] == CHECKED
        try:
            check = json.loads((job_dir / "out" / "check.json").read_text())
            out["unsupported"] = len(check.get("unsupported", []))
        except (OSError, ValueError):
            pass
    return out


def reports(camp_path: Path) -> List[Dict[str, Any]]:
    """Every report of the campaign, oldest first."""
    d = reports_dir(camp_path)
    if not d.is_dir():
        return []
    return [status(p) for p in sorted(d.iterdir()) if p.is_dir()]
