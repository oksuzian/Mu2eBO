---
type: incident
title: Without the outer proton absorber, ST_In/ST_Out/STMUpstream overlap DS2 volumes
description: 'hasProtonAbsorber=false builds on Offline v13_44_00 (PR #2089), but then
  constructVirtualDetectors sizes ST_In, ST_Out and STMUpstream to the DS2 bore minus 5 mm and
  they overlap Coupler_DS2_1 and others (3 overlaps); keep the OPA as DS vacuum instead'
status: resolved
status_note: worked around 2026-11-06 (foilsnopa_bc keeps foilsnopa_bb's geometry)
timestamp: '2026-11-06'
---

# Without the outer proton absorber, ST_In/ST_Out/STMUpstream overlap DS2 volumes

## Summary

The spec revision for [bo-foilsnopa](/projects/bo-foilsnopa.md) on SimJob
MDC2025bc planned to drop the absorbers with `hasProtonAbsorber = false`, which
Offline v13_44_00 builds (PR #2089). The geometry pre-check at the middle of the
knob box failed the zero-overlap policy with 3 overlaps, none in our target.

## Key facts

- `Mu2eG4/src/constructVirtualDetectors.cc` (v13_44_00): ST_In, ST_Out and
  STMUpstream take their radius from the OPA's inner radius at their z, minus
  5 mm, only when `hasProtonAbsorber` is true and the OPA exists. Otherwise the
  radius is the DS2 bore `ds->rIn1()` minus 5 mm (or `TSdA.rFactorForVDs` with
  `hasTSdA`).
- At bore size they overlap other DS2 volumes: `VirtualDetector_STMUpstream`
  overlaps `Coupler_DS2_1` (G4Box) by 9.26 mm; ST_In and ST_Out overlap too.
  The surface check counts them as baseline (not in managed volumes), and
  `require_zero_overlaps` refuses them.
- Workaround, the one `foilsnopa_bb` already uses: `protonabsorber.ipa.build=false`,
  `protonabsorber.outerPAMaterialName="DSVacuum"`,
  `protonabsorber.oPASupportNSupportRing=0`. The vacuum OPA is physics-free and
  keeps the detectors at the OPA radius.

## Cross-links

- Related: [mu2e-overlap-check](/external/mu2e-overlap-check.md),
  [stickman-inds2vacuum-stmupstream-overlap](/incidents/stickman-inds2vacuum-stmupstream-overlap.md)
- Source: `mode_specs/foilsnopa_bc.json` (the geometry note)

## Open questions / TODO
