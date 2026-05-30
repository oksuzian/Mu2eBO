# Wiki Index

Catalog of every entity page. Keep entries one line each.
See [[CLAUDE]] for the schema and maintenance contract.

## Projects (active research lines)
- [bo-michael](projects/bo-michael.md) — 4D BO maximizing `S/√B − α·calo/POT` over TSdA + holeRadius + COL5
- [bo-helical](projects/bo-helical.md) — (dormant 2026-05-29) 4D BO over `tsda.helical.*` (Option A coupling); retired after Pareto saturation; superseded as active line by [[bo-foils]]
- [bo-foil](projects/bo-foil.md) — original 7D BO over foil-stack geometry; superseded by bo-michael
- [bo-foils](projects/bo-foils.md) — 5D extras-only BO over stopping-target +12 envelope (≤6 up + ≤6 down) on the pinned 37-foil v02 base; no helical plug; Phase 0 PASS 2026-05-28

## Concepts (physics + software)
- [tsda](concepts/tsda.md) — TS downstream Absorber; dominant variance knob in mmackenz sweep
- [col5-shield](concepts/col5-shield.md) — TS COL5 polyethylene shield categorical
- [degrader](concepts/degrader.md) — pion degrader Al plate; topology toggle (in-beam vs parked)
- [scalarized-objective](concepts/scalarized-objective.md) — `obj = S/√B − α·calo/POT`, α choice
- [bo-modes](concepts/bo-modes.md) — flat_gamma / flat_electron report vs CE-only optimizer signal
- [batch-bo](concepts/batch-bo.md) — q>1 parallel BO; CL-mean q=3 (michael) / CL-min q=2 (helical); skopt-native
- [fixed-geometry-constraint](concepts/fixed-geometry-constraint.md) — no moving parts between Run1A and Run1B; excludes v39's rotating degrader
- [orchestrator-evaluation-2026-05](concepts/orchestrator-evaluation-2026-05.md) — why LangGraph (vs Prefect 3) was chosen for Phase 1; revisit at end of Phase 2
- [closed-loop-bo-design](concepts/closed-loop-bo-design.md) — load-bearing constraints for `graph/closed_loop.py` (SqliteSaver WAL, leaderboard/pending locking, barrier source-of-truth, config-SHA stamping, scan_logs gating)
- [g4-speed-knobs](concepts/g4-speed-knobs.md) — `minRangeCut=0.05` is the safe speedup arm (−6% CPU); `Minimal` physics list zeros stop counts even though workflow looks "EM-only"
- [wiki-review-hooks](concepts/wiki-review-hooks.md) — Stop hook must emit `{"decision":"block","reason":...}` JSON + check `stop_hook_active` guard to actually feed back to the model; plain echo / stderr are invisible
- [bfield-at-helical-plug](concepts/bfield-at-helical-plug.md) — Bz drops 10% across plug (graded TS5→DS region); muon pitch ~1m >> plug halflength, so "matched-pitch" model is wrong — plug is a Coulomb-scatter + azimuth-randomizer, not a pitch-resonant filter
- [gp-cloud-rendering](concepts/gp-cloud-rendering.md) — GP density cloud silently fails to envelope top-3 champions: <1.1% of Sobol samples at sob≥3.2 (invisible under LogNorm) + GP under-predicts calo there by 2.3× (matches forward-LOO log-calo bias −0.80)
- [stopping-target-foil-base-spec](concepts/stopping-target-foil-base-spec.md) — deployed 37 foils at rOut=75, halfThickness=0.0528 mm (≈105.6 µm full — not the "100 µm" design spec); holeRadius is a SINGLE SCALAR (StoppingTargetMaker.cc:41 getDouble), not per-foil

## Datasets
- [mmackenz-priors](datasets/mmackenz-priors.md) — 104 hand-designed configs; 96 with both metrics
- [leaderboards](datasets/leaderboards.md) — TSV history files for each BO driver

## Drivers (executable scripts)
- [autoresearch-bo-michael](drivers/autoresearch-bo-michael.md) — `propose | evaluate | preflight | show-priors`
- [autoresearch-bo](drivers/autoresearch-bo.md) — original 7D BO driver
- [pipeline](drivers/pipeline.md) — per-config runner: forks config, submits grid, harvests
- [preflight](drivers/preflight.md) — local `mu2e -n 1` G4 init feasibility check
- [graph-runner](drivers/graph-runner.md) — LangGraph state-machine orchestrator (Phase 1 mock-grid); Studio + Streamlit overlay
- [closed-loop-runner](drivers/closed-loop-runner.md) — multi-round Pareto-pick BO driver: wraps q parallel graph-runner children, refits GP between rounds
- [tests](drivers/tests.md) — `tests/test_closed_loop.py` + `tests/test_audit_fixes.py`; 37 tests, no grid contact; `.venv-graph/bin/python -m unittest discover -s tests -v`

## Incidents (root-caused gotchas)
- [geom-run1a-vs-run1b](incidents/geom-run1a-vs-run1b.md) — `geom_run1_a.txt` baseline missing TT_MidInner fix; fails in run1b_mubeam
- [col5-projection-bug](incidents/col5-projection-bug.md) — `COL5Poly` material was being misclassified as "air" in prior loader
- [grid-job-completion-check](incidents/grid-job-completion-check.md) — use `jobsub_q` + plain `/pnfs ls`; avoid `condor_q` and `ifdh`
- [template-fcl-staleness](incidents/template-fcl-staleness.md) — `rsync+sed` fork misses `template.fcl`; G4 init fails on stale geom basename
- [harvest-denominator-bug](incidents/harvest-denominator-bug.md) — `s_over_sqrt_b`/`calo_per_pot` biased high by lost-job fraction (hardcoded denom)
- [calo-constant-across-helical](incidents/calo-constant-across-helical.md) — all harvest metrics bit-identical across 6 helical configs; **resolved 2026-05-17** via self-built patched libmu2e_Mu2eG4.so + LD_PRELOAD
- [concurrent-token-contention](incidents/concurrent-token-contention.md) — mu2ejobsub races when concurrent chains submit within ~10s; need 60-90s stagger
- [stage-out-rename-race](incidents/stage-out-rename-race.md) — `list-outputs` FileNotFoundError when /pnfs `NNNNN.<hash>` dirs rename to bare-index mid-glob; fix is 60s sleep before retry
- [stage-out-lag](incidents/stage-out-lag.md) — `list-outputs` "outstage missing" when poll returns before /pnfs stage-out catches up; resolved 2026-05-20 by convergence-poll gate
- [concat-xrootd-fileopen-postendjob](incidents/concat-xrootd-fileopen-postendjob.md) — concat art exits 1 in PostEndJob with xrootd FileOpenError under high concurrent IO; outstage has .log but no .art
- [tsda-disc-helical-sibling-overlap](incidents/tsda-disc-helical-sibling-overlap.md) — TSdA4 disc + helical plug are siblings in DS2Vacuum; silent G4 placement-order navigation when z-ranges overlap
- [tessellated-solid-facet-orientation](incidents/tessellated-solid-facet-orientation.md) — `TSdAHelicalTube` built with inverted facet winding → GeomSolids1001 + 28M GeomNav1002/iteration; preflight misses; scan_logs node now reports it
- [events-per-job-mid-flight-edit](incidents/events-per-job-mid-flight-edit.md) — editing `STAGES[*]["events_per_job"]` between submit and harvest mis-scales metrics; stamp-at-submit fix in pipeline.py; cluster.txt mtime is NOT a safe submit-time proxy
- [kerberos-mid-run-expiry](incidents/kerberos-mid-run-expiry.md) — closed_loop has no token watchdog; krb5 expiry mid-round → Errno 127 ENOKEY at subprocess.run → graph terminates before harvest, no leaderboard row
- [jobsub-disk-quota-stderr-swallowed](incidents/jobsub-disk-quota-stderr-swallowed.md) — `pipeline.py:420` `check=True` swallows mu2ejobsub stderr; real cause is OSError 122 (disk quota) during jobsub_lite RCDS publish; recovery recipe + stderr-leak fix TODO
- [venv-relocated-to-data-volume](incidents/venv-relocated-to-data-volume.md) — `.venv-graph`/`.venv-botorch` live on /data, symlinked from project root; Ceph cross-volume mv runs ~430 KB/s on many-small-files
- [fcl-unicode-parse-error](incidents/fcl-unicode-parse-error.md) — FHiCL parser hard-fails on non-ASCII bytes in template comments; Unicode minus (U+2212) killed 8/8 FT01 closed-loop children at mubeam submit
- [barrier-false-positive-round1](incidents/barrier-false-positive-round1.md) — closed-loop FT05 round-1 children mis-resolved by `saver.get_tuple.next`; silent premature convergence; use `--max-rounds 1` until fixed
- [scan-broken-codes-too-narrow](incidents/scan-broken-codes-too-narrow.md) — SCAN_BROKEN_CODES=("GeomSolids1001",) only; 19 configs with LikelyGeomOverlap > 100 (up to 28.5M on helical050a) entered leaderboard; champion status of top-3 may be tainted
- [slack-bot-dm-channel-not-found](incidents/slack-bot-dm-channel-not-found.md) — bot's `files.completeUploadExternal` → `channel_not_found` on user-MCP DM channels; call `conversations.open` first to mint the bot's own DM
- [claude-bash-no-ssh-agent](incidents/claude-bash-no-ssh-agent.md) — Bash-tool subshells can't reach user's `ssh-agent`; `git push` to GitHub fails for Claude even when it works in user's interactive shell
- [foilsx04-all-preflight-ambiguous](incidents/foilsx04-all-preflight-ambiguous.md) — foilsX04 silent total failure (2026-05-29): 20/20 children died at preflight=ambiguous rc=3, parent reported converged=True with zero new leaderboard rows; convergence check has no "new evals this round" gate

## External pointers
- [mmackenz-workflow](external/mmackenz-workflow.md) — `/exp/mu2e/app/users/mmackenz/run1b/Run1BAna/workflows/`
- [mu2e-offline](external/mu2e-offline.md) — Musings on CVMFS, geom files, FCL prologs
- [muse-backing-pattern](external/muse-backing-pattern.md) — build patched Offline subset against a Musing; how the helical-plug lib is produced
- [mu2e-overlap-check](external/mu2e-overlap-check.md) — `g4.doSurfaceCheck=true` + `surfaceCheck.fcl` recipe for detecting silent volume overlaps
- [slack-file-upload-flow](external/slack-file-upload-flow.md) — three-step `getUploadURLExternal → POST bytes → completeUploadExternal` recipe for posting binary files to Slack from this project
- [mu2e-exp-website-docroot](external/mu2e-exp-website-docroot.md) — `https://mu2e-exp.fnal.gov` docroot is NFS-mounted at `/web/sites/m/mu2e-exp.fnal.gov/htdocs/`; readable without Shibboleth login
- [github-pages-publish-dir](external/github-pages-publish-dir.md) — GitHub Pages branch-deploy folder dropdown hardcodes `/(root)` and `/docs` only; arbitrary names like `/talks` require switching source to GitHub Actions
