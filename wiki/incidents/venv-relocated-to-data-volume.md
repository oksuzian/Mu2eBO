---
name: venv-relocated-to-data-volume
description: .venv-graph and .venv-botorch live on /exp/mu2e/data (symlinked from project root); Ceph cross-volume mv ran ~430 KB/s on many-small-files
type: incident
status: resolved
---

# venv relocated to /exp/mu2e/data volume

**Type:** incident
**Status:** resolved
**Updated:** 2026-05-23

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

## Cross-links

- Related: [[jobsub-disk-quota-stderr-swallowed]] (the /nashome 94%
  side of the same 2026-05-22 quota episode; /app was also at 94%
  which is why these venvs got moved).
- Source files: none — relocation is filesystem-level only.
- External: [[mu2e-offline]] for /cvmfs paths (unaffected).

## Open questions / TODO

- None. If `/exp/mu2e/data` ever hits pressure, see the "Faster-mv
  alternatives" above for the next relocation.
