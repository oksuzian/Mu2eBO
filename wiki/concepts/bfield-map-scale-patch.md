---
type: concept
title: Per-map field scale patch (bfield.mapScale)
description: GeometryService patch that scales single field maps (DS, TSd, ...) from
  geometry-file keys `bfield.mapScale.<map>`; shipped in Code_mdc2025ax_bfscale.tar.bz2
status: active
timestamp: '2026-10-29'
---

# Per-map field scale patch (bfield.mapScale)

## Summary
Stock Offline (v13_38_00) has one field scale, `bfield.scaleFactor`, read from
the **bfield file** (`services.GeometryService.bFieldFile`, `bfgeom_v01.txt` in
every stage), and it scales every map at once. A geometry knob can therefore not
scale one solenoid's field. The patch adds an optional per-map factor read from
the **geometry file**, which the study's geom writer renders:

    double bfield.mapScale.DSMap  = 1.05;
    double bfield.mapScale.TSdMap = 0.97;

The key suffix is the map's name, the file basename (`DSMap`, `TSdMap`,
`DSExtension`, `TSuMap_fix`, `PSMap`, ...). The factor multiplies
`bfield.scaleFactor`. Used by `mode_specs/foilsflash_col5bf_ax.json`
(foilsflash_ax + COL5 rIn + DS/TSd scales 0.75–1.1; added 2026-10-29).
Upstream: Mu2e/Offline#2079.

## Key facts
- Patch: `GeometryService/src/GeometryService.cc` collects `bfield.mapScale.*`
  from the geometry config and passes them to `BFieldManagerMaker`, which
  multiplies each map's `scaleFactor`. GeometryService only, so it builds ABI-safely as a
  one-package partial checkout ([muse-backing-pattern](/external/muse-backing-pattern.md)):
  26 s, 2 libs.
- Work area, patch and `rebuild.sh`: `/exp/mu2e/app/users/mmackenz/Offline_mdc2025ax_bfscale/`
  (`bfield_mapscale.patch`). Tarball:
  `${ARTIFACT}/autoresearch_muse/Code_mdc2025ax_bfscale.tar.bz2` (mmackenz's
  artifact root; another operator must build their own or point at it).
- Loud failures: a key naming no loaded map aborts with a GEOM exception, and so does a
  `bfield.mapScale.*` key in the bfield file. Exception: a field-off bfield file
  (`bfgeom_no_field.txt`, which the offline_preflight surface check uses) loads no
  maps, so the keys are reported unused rather than fatal. Without this, every
  preflight failed (found 2026-10-29). Each applied factor is printed
  (`BFieldManagerMaker: map DSMap scaled by ...`), so job logs show what ran.
- **Stock Offline silently ignores the keys.** A study using them must point both
  `kits.prodtools.code_tarball` and `kits.offline_preflight.code_tarball` at
  the patched tarball.
- Validated 2026-10-29 with BFieldPlotter (y = 0 plane, 250 mm grid), DS 1.1 / TSd 0.9:
  DSMap points ×1.1000, TSdMap ×0.9000, TSu/PS/outer maps ×1.0000.
- Map extents (Mau13, Mu2e coords): TSdMap x ∈ [-5096, 4], z ∈ [-829, 3071]
  (TS3 downstream half, TS4, TS5); TSuMap_fix x ∈ [4, 5004]; DSMap
  z ∈ [3071, 16071]; DSExtension z ≥ 16071. The maps share faces and don't overlap.
- Scaling a map region scales the total field computed in that region, all coils
  included. It is not a coil-current change: with unequal DS/TSd factors the field
  jumps at z = 3071 (TS5/DS face). To model a coil-current change, regenerate
  the maps.
- The Run 1B beam samples the foils studies resample are recorded entering
  TS3Vacuum (upstream end of TS3, x > 0), so the TSd and DS regions are
  fully resimulated per point, and `stops.upstream_eff` doesn't depend on these scales.

## Cross-links
- Related: [muse-backing-pattern](/external/muse-backing-pattern.md),
  [bo-foilsflash](/projects/bo-foilsflash.md)
- Source: Offline `GeometryService/src/BFieldConfigMaker.cc` (`bfield.scaleFactor`),
  `GeometryService/src/BFieldManagerMaker.cc` (`loadG4BL`)

## Open questions / TODO
- Upstream: Mu2e/Offline PR #2079 (opened 2026-10-29, branch
  `michaelmackenzie:bfield-map-scale`). Once a release carries it, point the study at
  that release's stock tarball and drop Code_mdc2025ax_bfscale.
- `approx_ce_sensitivity` assumes a fixed 0.2 MeV tracker resolution, so it does not see
  any resolution change from a scaled DS field.
