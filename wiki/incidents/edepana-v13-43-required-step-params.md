---
type: incident
title: EdepAna in Offline v13_43_00 requires six step-count parameters
description: 'MDC2025bb (Offline v13_43_00) EdepAna requires TrkStepEnergyThreshold,
  TrkStepTimeMin/Max, CaloStepEnergyThreshold, CaloStepTimeMin/Max (no defaults);
  anakit edep.fcl at 3ba8d23 set none, so the foilsnopa_bb smoke''s flash step died
  at module construction (mu2e exit 9); fixed by rebasing on anakit a96b57a, which
  probes the module and passes them only where declared'
status: resolved
status_note: fixed 2026-10-31 (anakit straw-maps rebased onto a96b57a, pin c4c30e3)
timestamp: '2026-10-31'
---

# EdepAna in Offline v13_43_00 requires six step-count parameters

## Summary

The first grid smoke of [bo-foilsnopa](/projects/bo-foilsnopa.md) on SimJob
MDC2025bb (`nopasmk01`, 2026-10-31) lost its `flash` step: anakit's `edep`
ran EdepAna and art stopped at module construction with exit 9. Offline PR
#2067 (merged 2026-10-27, in v13_43_00) added six required parameters to
EdepAna. [anakit](/external/anakit.md) at the pin then (3ba8d23 plus our
straw tools) set none of them. MDC2025ay, behind the `_ax` studies, has the
old module, which rejects the new parameters, so `edep.fcl` cannot simply add
them.

## Key facts

- The art error: `Module label: EDepAna ... Missing parameters:
  TrkStepEnergyThreshold, TrkStepTimeMin, TrkStepTimeMax,
  CaloStepEnergyThreshold, CaloStepTimeMin, CaloStepTimeMax`, then `Art has
  completed and will exit with status 9`.
- The six only gate EdepAna's printed step counts (all steps, above the
  energy threshold, and also inside the time window). The tracker and calo
  energy sums are taken before the cuts (`EdepAna_module.cc` in v13_43_00,
  the loops after "Approximate hit counts"), so `flash_edep` and the
  `ce_edep` numbers do not depend on the values.
- The fix is upstream: M. MacKenzie's anakit 7ebc2f9 (2026-10-28, merged in
  a96b57a) asks the configured Offline with `mu2e --print-description
  EdepAna` (`tools/mu2e_job.py` `module_accepts`) and passes the parameters
  only when the module declares them. On older Offline `edep` runs as before.
- Our local branch `straw-maps` was rebased onto a96b57a (now c4c30e3);
  `ANAKIT_PIN_SHA` moved, `VERSION` kept (no existing analysis computes
  differently), so no board moved.
- The fix had a second edge. a96b57a's `edep` DECLARES the 18
  `calo_nsteps_*`/`trk_nsteps_*` metrics but leaves them out on older
  Offline, and our anakit adapter required every declared metric in the
  reply. So the pin bump broke `edep` on MDC2025ax (`foilsflash_ax`,
  `foilspfbpz_ax`): the reference point `ffaxref01` died "anakit's reply
  lacks declared metric(s) [calo_nsteps_total, ...]" though the analysis
  succeeded. The adapter now keeps the declared metrics that came back; a
  metric a study reads is still checked by the launch check, `params_from`
  and scoring. Because the analysis had succeeded, removing `broken.txt` and
  re-running the same config resumed the point (the kit reported the step
  completed; only the contract check had refused it).
- A step the kit itself reported failed cannot be re-run under the same
  config: its handle (`<config>.<step>`) is deterministic. The retry was a
  new config, `nopasmk02`.
- The values in the noipa note's own `edep.fcl` (AnalysisNotes
  noipa-edep-2026-10): tracker 0.0005 MeV from 500 ns, calo 0.5 MeV from
  500 ns.

## Cross-links

- Related: [anakit](/external/anakit.md), [bo-foilsnopa](/projects/bo-foilsnopa.md),
  [edepana-saw-events-scientific-notation-parse](/incidents/edepana-saw-events-scientific-notation-parse.md)
- Source: `core/adapters/anakit.py` (`ANAKIT_PIN_SHA`)

## Open questions / TODO
