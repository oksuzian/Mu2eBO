# Wiki Index

Catalog of every entity page. Keep entries one line each.
See [[CLAUDE]] for the schema and maintenance contract.

## Projects (active research lines)
- [bo-michael](projects/bo-michael.md) — 4D BO maximizing `S/√B − α·calo/POT` over TSdA + holeRadius + COL5
- [bo-helical](projects/bo-helical.md) — 4D BO over `tsda.helical.*` (Option A coupling); z0/rin derived from halflen/dx/dy; preflight surface-check enforces no managed-volume overlaps
- [bo-foil](projects/bo-foil.md) — original 7D BO over foil-stack geometry; superseded by bo-michael

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

## External pointers
- [mmackenz-workflow](external/mmackenz-workflow.md) — `/exp/mu2e/app/users/mmackenz/run1b/Run1BAna/workflows/`
- [mu2e-offline](external/mu2e-offline.md) — Musings on CVMFS, geom files, FCL prologs
- [muse-backing-pattern](external/muse-backing-pattern.md) — build patched Offline subset against a Musing; how the helical-plug lib is produced
- [mu2e-overlap-check](external/mu2e-overlap-check.md) — `g4.doSurfaceCheck=true` + `surfaceCheck.fcl` recipe for detecting silent volume overlaps
