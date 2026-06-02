---
name: venv-relocated-to-data-volume
description: .venv-graph and .venv-botorch live on /exp/mu2e/data (symlinked from project root); Ceph cross-volume mv ran ~430 KB/s on many-small-files
type: incident
status: resolved
---

# venv relocated to /exp/mu2e/data volume

**Type:** incident
**Status:** resolved
**Updated:** 2026-05-31

## Summary

`/exp/mu2e/app` hit 94% used on 2026-05-22. Both project venvs were
moved off /app to /data and symlinked back so activate paths still
work. The cross-Ceph-volume mv is **bottlenecked by metadata ops on
many small files**, not byte throughput. Measured rates:
`.venv-graph` 693M → 26 min (~440 KB/s effective);
`.venv-botorch` 6.7G → 47 min (~2.4 MB/s — much faster because
libtorch/CUDA shared objects are large single files). Do NOT
linearly extrapolate from small-venv timing.

## Key facts

- **Current layout (2026-05-22):**
  - `/exp/mu2e/app/users/oksuzian/autoresearch/.venv-graph` → symlink
    → `/exp/mu2e/data/users/oksuzian/autoresearch_venvs/.venv-graph`
  - `/exp/mu2e/app/users/oksuzian/autoresearch/.venv-botorch` → symlink
    → `/exp/mu2e/data/users/oksuzian/autoresearch_venvs/.venv-botorch`
- **Why symlinks instead of just moving + changing path:** uv-built
  venvs hardcode their absolute path in `pyvenv.cfg` and `bin/activate`.
  Keeping the original path live via symlink avoids rewriting any
  scripts or rebuilding the venv. Verified: `source
  .venv-graph/bin/activate && python -c "import langgraph"` works
  through the symlink.
- **Ceph cross-volume mv rate (this transfer):** dominated by
  per-file metadata cost. .venv-graph (small pure-Python site-pkgs)
  ran ~440 KB/s; .venv-botorch (libtorch ~2GB shared objects) ran
  ~2.4 MB/s — 5.5× faster despite being 10× larger. Don't estimate
  from file count or total bytes alone; the file-size *distribution*
  matters. Background any venv-sized mv.
- **Faster-mv alternatives (not tested here, may help next time):**
  `tar -C src -cf - . | tar -C dst -xf -` cuts metadata-op count and
  often runs 2-5× faster on Ceph; or rebuild the venv at destination
  via `uv venv` + `uv pip install -r requirements.txt` (often the
  fastest option if the uv cache is warm).
- **The slow rate is Ceph→Ceph specific, NOT cross-volume mv
  universally.** Measured 2026-05-23 for `~/.cache` cleanup
  (NFS `/nashome` → Ceph `/exp/mu2e/data`): puppeteer 612M and
  pip 517M each finished in ~30s **concurrently** = ~17-20 MB/s
  effective — **40-50× faster** than the 440 KB/s Ceph→Ceph
  small-file rate. Inference: the bottleneck above was the source-side
  Ceph metadata reads, not destination writes. Estimating-rule:
  on `nashome → data` moves (small files), assume tens of MB/s; on
  `app → data` (small files), assume hundreds of KB/s. Don't carry
  the Ceph→Ceph pessimism over to NFS→Ceph.
- **No source file references `.venv-botorch`** — it's
  manually-activated only. `.venv-graph` is referenced from the
  [[graph-runner]] skill and is the standard entrypoint for
  `python -m graph.run`.
- **Leaked CVMFS `PYTHONPATH` shadows venv packages** (2026-05-31): if a
  Musing env was sourced into the launching shell (e.g. `MDC2025ap` —
  `muse setup` / `setupmu2e-art.sh`), `PYTHONPATH` gets stuffed with cvmfs
  spack **python3.10** site-packages (`…/environments/{muse-…-p096,ops-019}/
  .spack-env/view/lib/python3.10/site-packages`) AND cvmfs `python3.10`
  becomes first on `PATH`. Both venvs prepend `PYTHONPATH` ahead of their
  own `site-packages`, so the py3.10 copies of numpy/typing_extensions
  shadow the venv's:
  - `.venv-botorch` (py3.9): imports numpy 2.1.2 → `ModuleNotFoundError:
    numpy._core._multiarray_umath` + the *misleading* "do not import numpy
    from its source directory" message (NOT a source-tree issue).
  - `.venv-graph` (py3.11): `ImportError: cannot import name 'Sentinel'
    from 'typing_extensions'` (py3.10 copy lacks it) → breaks
    `unittest discover -s tests`.
  - **Fix: prefix the command with `PYTHONPATH=` only.** `PYTHONHOME` is
    NOT involved (it stays unset); do not `-u PYTHONHOME`. Verified
    2026-05-31: `PYTHONPATH= .venv-graph/bin/python -m unittest …` →
    56/56 green; `import typing_extensions` resolves inside the venv.
  - **Scope: interactive / Claude-Bash sessions only.** The production
    closed-loop parent runs with a CLEAN env (no `PYTHONPATH`/`PYTHONHOME`,
    no cvmfs on PATH — verified via `/proc/<pid>/environ`), so grid runs
    are unaffected. This only bites venv invocations from a shell that
    sourced a Musing first (the `/closed-loop-status` saturation step,
    ad-hoc test runs, etc.).
- **skopt is NOT installed in `.venv-botorch`** (2026-05-31): any
  cross-picker comparison script (e.g.
  `mmackenz_table_plots/diversity_overlay_foils.py`) that wants both a
  BoTorch qNEHVI batch AND a skopt CL-min batch in the same process
  must invoke `gp_predict_{foils,helical}.compute_explore_picks` via a
  `.venv-graph` subprocess (pipe picks back as JSON). matplotlib +
  torch + botorch live in `.venv-botorch`; skopt + langgraph + scikit-
  learn live in `.venv-graph`; there is no single venv with all four.

## Cross-links

- Related: [[jobsub-disk-quota-stderr-swallowed]] (the /nashome 94%
  side of the same 2026-05-22 quota episode; /app was also at 94%
  which is why these venvs got moved).
- Source files: none — relocation is filesystem-level only.
- External: [[mu2e-offline]] for /cvmfs paths (unaffected).

## Open questions / TODO

- None. If `/exp/mu2e/data` ever hits pressure, see the "Faster-mv
  alternatives" above for the next relocation.
