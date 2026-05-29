---
name: jobsub-disk-quota-stderr-swallowed
description: mu2ejobsub fails rc=1 with no error in graph log — OSError 122 (disk quota) hidden by capture_output=True in submit_stage
type: incident
status: resolved
---

# jobsub-disk-quota — stderr swallowed by submit_stage

**Type:** incident
**Status:** resolved (workaround documented; root-cause is env, not code)
**Updated:** 2026-05-23

## Summary

A chain reaches "preflight: pass", builds the cnf .tar, then dies with
`subprocess.CalledProcessError: ... mu2ejobsub ... returned non-zero exit
status 1` and no stderr in either the graph log or the per-stage
`submit_<stage>_<ts>.log`. The real failure is **`OSError: [Errno 122]
Disk quota exceeded`** thrown by jobsub_lite during RCDS hash
publishing. The error is invisible because `pipeline.py:420` uses
`subprocess.run(..., check=True, capture_output=True)` — `check=True`
raises before lines 421-423 print `out.stderr`.

## Key facts

- **Symptom in graph log:** chain ends after `preflight: pass` with
  `[run] done. final keys: [...]` — no `cluster_id`, no stage transition.
- **Symptom in `submit_<stage>_<ts>.log`:** trace ends at
  `[mubeam] submitting: mu2ejobsub ...` followed directly by the
  `CalledProcessError` traceback — no jobsub_lite output.
- **Root cause (this incident, 2026-05-22):** `/nashome` at 94% global
  usage; per-user quota exhausted. jobsub_lite gzips the cnf .tar to a
  hash and uploads to RCDS; the second hash publish step throws
  `OSError: [Errno 122] Disk quota exceeded`. First hash publish often
  succeeds because the first gzip fits in remaining space.
- **Casualties (2026-05-22 episode):** `helicalQR00_02_ftfp` died at
  mubeam submit (chain never got a cluster_id). Three SR02 chains —
  `helicalSR02R00_01`, `_04`, `_05` — got past mubeam + run1b_mubeam
  with real cluster IDs but died at the *downstream* submit:
  `_01` and `_05` at concat, `_04` at mustops_ce. **The quota
  tightened mid-chain**, between the 12:05 mubeam-batch submissions
  (which succeeded) and the 12:08–12:16 downstream submissions (which
  failed). Lesson: a chain clearing preflight + mubeam is no
  guarantee the next submit will not hit the same wall — quota is a
  moving target during the run, not a one-shot precondition.
- **Per-stage recovery is cheap.** Because `pipeline.py` is per-stage
  idempotent and clusters from earlier stages are recorded in the
  SqliteSaver checkpoint, the recovery path for the 3 SR02 chains is
  `python pipeline.py --config <cfg> submit <stage>` for *just* the
  failed stage — no need to re-run mubeam. Pull the failed stage name
  from the checkpoint's `errors` field, not from the log (the log
  ends silent).
- **Footgun on retrying a template-edit experiment (2026-05-23):** the
  materialized `cnf.<...>.tar` reflects the template's contents at the
  moment pipeline.py rendered it, NOT at the moment the user "set up"
  the experiment. If template.fcl was edited (e.g. FTFP_BERT line
  added), then reverted, then the chain submitted (and the tar
  materialized post-revert), the tar carries the *reverted* state —
  the experimental knob never made it onto the grid. Verified on
  `helicalQR00_02_ftfp/mubeam/cnf...tar`: grepping for
  `physicsListName|FTFP_BERT` inside the tar's `mu2e.fcl` returned
  nothing despite the chain being launched with that intent. **Always
  grep the materialized tar's mu2e.fcl for the edited knob before
  declaring a chain ran the intended variant.** Recovery: delete the
  stale stage-dir contents and re-run with the edit live in template
  so pipeline.py re-materializes — per-stage idempotence will skip
  the re-materialization step if the cnf tar already exists.
- **`pipeline.py:420` stderr-swallow bug:**
  ```python
  out = subprocess.run(submit, ..., capture_output=True, text=True, check=True)
  print(out.stdout)
  if out.stderr.strip():
      print("STDERR:", out.stderr, file=sys.stderr)
  ```
  `check=True` raises `CalledProcessError` before the `print` lines.
  `CalledProcessError.stderr` *is* populated but Python's default
  `str(exc)` doesn't include it. Fix: wrap in `try/except
  CalledProcessError as e: print("STDERR:", e.stderr); raise`.

## Recovery recipe (when stderr is hidden)

1. Look at the per-stage log under
   `/exp/mu2e/data/users/oksuzian/autoresearch_grid/<cfg>/graph_logs/submit_<stage>_<ts>.log`.
   If it ends at the `[<stage>] submitting: mu2ejobsub ...` line + a
   traceback, stderr was swallowed.
2. Re-run mu2ejobsub by hand with the full env to see jobsub_lite
   output:
   ```bash
   cd /exp/mu2e/data/users/oksuzian/autoresearch_grid/<cfg>/<stage>
   bash -c 'source /cvmfs/mu2e.opensciencegrid.org/setupmu2e-art.sh >/dev/null 2>&1 \
     && source /cvmfs/mu2e.opensciencegrid.org/Musings/SimJob/Run1Bak/setup.sh >/dev/null 2>&1 \
     && setup mu2egrid >/dev/null 2>&1 \
     && getToken >/dev/null 2>&1 \
     && mu2ejobsub --jobdef <cnf.tar> --firstjob 0 --njobs 1 \
        --default-location disk --default-protocol root --predefined-args=al9'
   ```
   `setup mu2egrid` is required to put mu2ejobsub on PATH; sourcing
   setupmu2e + Run1Bak musing alone is not enough.
3. If error is `OSError: [Errno 122] Disk quota exceeded`: free
   `/nashome` space (and possibly `/exp/mu2e/app`), then re-run
   `pipeline.py --config <cfg> submit <stage>`. The materialized
   `.tar` is per-stage idempotent so the FCL/code in the tar is
   preserved across the retry.

## Cross-links

- Related: [[concurrent-token-contention]] (other mu2ejobsub failure
  mode — also under submit-lock, but token-races, not quota).
- Source files: `pipeline.py:413-432` (`submit_stage` jobsub call +
  swallowed stderr), `pipeline.py:265-274` (env construction —
  `setup mu2egrid` requirement).
- Driver page: [[pipeline]] (per-stage submit semantics).

## Open questions / TODO

- Patch `pipeline.py:420` to surface stderr on CalledProcessError
  before re-raising. One-liner; do next time we touch that block.
- Add a pre-submit quota probe (e.g., `df` of `/nashome`) and skip
  submit with a clear error if free-space < 200 MB.
