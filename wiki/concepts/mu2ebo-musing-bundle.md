---
type: concept
title: A Mu2eBO Musing (one release that pins every kit)
description: 'Feasibility (2026-11-03) of a SimJob-like published bundle for Mu2eBO: muse already
  carries Python-only repos (.muse PYTHONPATH/PATH; pyutils ships in the EventNtuple and Analysis
  Musings) and Musings stack (AnalysisMDC2025 on SimJob MDC2025bb); blockers are four Python
  runtimes, untagged repos, DoseMap outside any repo, and Musing install rights'
status: open
status_note: investigated, not built
timestamp: '2026-11-06'
---

# A Mu2eBO Musing (one release that pins every kit)

## Summary

A Musing is a muse work area published on cvmfs: a `backing` link to another
Musing, repos checked out at tags, their `build/` for prof and debug, and a
`setup.sh` that runs `muse setup` on itself. SimJob MDC2025bb is Production
v02_22_00 + mu2e-trig-config v8_12_00 backed by Offline v13_43_00. A
"Mu2eBO" Musing would be the same thing one level up: backed by SimJob, with
Mu2eBO, prodtools, analysis-mcp-server (anakit), beamkit and the DoseMap
analyzer at tags. `muse setup Mu2eBO <tag>` would then name every kit
version at once, the grid code tarball could back onto it, and anakit's
`musing` setting could name it instead of a personal work area.

## Key facts

- muse puts a repo's own folders on the paths when its `.muse` file asks:
  `PYTHONPATH <dir>`, `PATH <dir>`, `FHICL_FILE_PATH <dir>`
  (`$MUSE_DIR/bin/museSetup.sh`, muse 4.17.1). Production's `.muse` uses
  `PATH Scripts` and `PYTHONPATH JobConfig/ensemble/python`.
- Python-only repos already ship in Musings: `pyutils` sits in the
  `EventNtuple` (v06_07_00) and `Analysis` (v01_02_00) Musings.
- Musings stack: `AnalysisMDC2025` v02_03_01 (ArtAnalysis, EventDisplay,
  EventNtuple, RefAna, Tutorial) backs onto `SimJob/MDC2025bb`.
- Only production managers and system administrators install Musings
  (MDC2020 note, DocDB 44084); dataset names carry the Musing name.
- Blocker 1, interpreters. The kits run under four runtimes today: Mu2eBO on
  `ana 2.8.0` (mcp 2.0), anakit on `ana 2.7.0` (its pyproject pins
  `mcp<2`), prodtools' MCP servers and beamkit each from a personal venv on
  the app disk (mcp 2.2; beamkit requires `mcp>=2.2`). A Musing does not
  carry Python packages, so one published env must serve all four: anakit
  must accept mcp 2, and an `ana` release with mcp >= 2.2 is needed.
- Blocker 2, tags. beamkit has tags (v0.5.1); prodtools runs v3.3.4 + 65
  commits with local edits; analysis-mcp-server has no tags; DoseMap lives
  in AnalysisNotes, not a code repo (or move it into Offline/Analyses next to
  EdepAna, so SimJob carries it).
- prodtools already publishes releases on cvmfs:
  `/cvmfs/mu2e.opensciencegrid.org/bin/prodtools/<tag>` (v2.3.0 to v3.3.4,
  `current` -> v3.3.4; grid workers run `prodtools_dir` from there). A
  release carries the MCP server source (`mcp/src`) but no Python packages.
  Verified 2026-11-03: `start_mcp.sh --check` from v3.3.4 passes with
  `MCP_PYTHON=<a venv with mcp 2.x and htcondor 25.0.*>` and
  `PYTHONPATH=<release>/mcp/src` (the start script does not add `mcp/src`
  itself; it relies on a pip install). No cvmfs env has both packages:
  `ana 2.8.0` has mcp but no htcondor, ops-022 (`muse setup ops`) has
  neither. The htcondor wheel must match the pool's major.minor
  (install.sh reads `/usr/bin/condor_version`), so a deps env must follow
  pool upgrades. v3.3.4 (2026-09-19) predates `submit_once`/`run_status`
  (d6d78d6, 09-20) and `run_local` (487b8cb, 09-25), which the adapter
  calls; Mu2e/prodtools main has them (6c982aa, 10-30) but no release yet,
  and our drain fix ee98590 is not on main.
- beamkit already does the whole thing: `/cvmfs/mu2e.opensciencegrid.org/bin/beamkit/<tag>`
  (v0.3.0, v0.3.1; `current` -> v0.3.1) ships the source plus a `.venv`
  built at its final cvmfs path on the ops-019 spack python
  (`bin/install_beamkit.sh`), so a client runs
  `current/scripts/beamkit-mcp-cvmfs` with nothing to install. It is the
  template for prodtools' missing packages. We run v0.5.1 from a checkout;
  v0.5.x is not published (same tool names as v0.3.1, 33 commits apart).
- anakit has no cvmfs release and no tags, but every Python package it
  needs is already in `ana 2.7.0` on cvmfs, so a release would be source
  only: tag it, copy it under `bin/`, set kits.toml's PYTHONPATH to it.
- Simpler than a Musing: each kit runs as its own MCP server process, so
  the kits need not share one Python env (Blocker 1 applies only to a
  single Musing). Once every kit is a versioned cvmfs folder carrying its
  own packages (the beamkit way) or running on a published `ana` env, a
  global release is just a manifest in a Mu2eBO tag: SimJob name, each
  kit's release folder, Mu2eBO's interpreter. Only C++ (DoseMap) still
  needs a build: into Offline, or a small Musing backed by SimJob.
- surrokit (the GP ask/tell engine) is a dependency too: github.com/Mu2e/surrokit (moved from oksuzian),
  no tags, the sibling checkout pinned to 26929f7 by
  `tests/test_botorch_predict.py::TestSurrokitPin`; its packages (torch,
  botorch) come from `ana 2.8.0`. Hazard found 2026-11-04: a stale `pip
  --user` copy sits in `~/.local/lib/python3.12/site-packages/surrokit`
  (commit 6967292, 2026-08-28; gp.py, pickers.py, problem.py differ).
  `core/botorch_predict.py` and `surrogate/` put the checkout first on
  sys.path, so the entry points load the checkout, but a bare `import
  surrokit` before them loads the stale copy, and the pin test checks only
  the checkout's HEAD, not what was imported.
- offline_preflight runs no server: it builds the geometry with the
  study's Offline, which comes from a SimJob Musing on cvmfs.
- Blocker 3, engine. kits.toml finds kits through `$AUTORESEARCH_*`
  checkouts; with a Musing these become `$MUSE_WORK_DIR/<repo>`. Only anakit
  is pinned (`ANAKIT_PIN_SHA`) and only anakit and beamkit record their
  build per step; prodtools records nothing.
- Interim without cvmfs: a manifest in Mu2eBO (SimJob name, repo -> tag,
  interpreter) plus a script that assembles the same layout as a work area
  on the app disk, and a startup check of every kit against it. Publishing
  later is a copy of that area.

- How SimJob is released (checked 2026-11-06): one text file per Musing
  family in github.com/Mu2e/MuseConfig, `musing/SimJob`, one line per
  release, e.g. `MDC2025bc Production/v02_23_00 mu2e-trig-config/v8_12_00
  backing/Offline/v13_44_00`. A Jenkins job (`mu2e_musing_build`) reads it
  and builds prof/debug tarballs that a production manager installs on
  cvmfs. One manifest plus one generic builder, not a script per repo.
- Where kits go (R. Culbertson, 2026-11-06): `ai/mcp/<kit>/<version>/venv`
  on Mu2e's cvmfs. A venv is not portable (full paths and links), and
  building one elsewhere then tarring it has been painful; beamkit's
  `install_beamkit.sh` avoids that by building at the final path on the
  publishing node.

- Written 2026-11-06 on branch `release-manifest` (worktree
  autoresearch-release, uncommitted): `release/manifest` (kit lines: repo,
  base python, site packages yes/no, pyproject dir, sys.path dir, extra pip,
  import check; release lines: kit/tag ... SimJob/<musing>) and
  `release/install_kits.py` (dry run by default; one cvmfs transaction per
  release, aborted on error; `--root` elsewhere = test, no cvmfs_server).
  The kit runs from its tree through a `.pth` in the venv, not a pip
  install, because analysis-mcp finds `fcl/` relative to `tools/`. Test
  installs into scratch: analysis-mcp v01_02_00 on ana 2.7.0 in 13 s (pip
  added typer, annotated-doc; the server starts and lists edep_occupancy);
  beamkit v0.5.1 on the ops-019 python in about 30 s (39 venv packages,
  htcondor 25.0.14, mcp 2.3.0). `compileall` must tolerate non-Python .py
  files (beamkit's job templates).

- Engine side, same branch (2026-11-06): `AUTORESEARCH_RELEASE=<record>`
  before `source activate.sh` runs analysis-mcp, surrokit and beamkit from
  the installed copies (`core/release_env.py` prints the exports; a kit
  setting already exported with another value is refused). kits.toml
  starts anakit and beamkit with `AUTORESEARCH_ANAKIT_PYTHON` /
  `AUTORESEARCH_BEAMKIT_PYTHON` (defaults ana 2.7.0 and the beamkit
  checkout's .venv). The anakit adapter and the two pin tests read an
  installed copy's commit from RELEASE.json (no .git). Tested on the /exp
  install: branin campaign q=2, 8 evals, 8 rows in 43 s with surrokit from
  the release; ffaxref01 (MDC2025ay) stops/ce_edep/sob/flash with the
  installed analysis-mcp gave all 36 recorded metrics bit for bit, so the
  branch's ANAKIT_PIN_SHA moved 53c5afa -> ec2f740 (v01_02_00).

## Cross-links

- Related: [contract-engine](/drivers/contract-engine.md), [anakit](/external/anakit.md),
  [mu2e-cvmfs-python-envs](/external/mu2e-cvmfs-python-envs.md),
  [muse-backing-pattern](/external/muse-backing-pattern.md)

## Open questions / TODO

- Who publishes ana envs, and can the next one carry mcp >= 2.2?
- Would the computing group install a Mu2eBO Musing, or should it be a
  Musing under the Analysis family?
