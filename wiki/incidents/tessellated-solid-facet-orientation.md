# TSdAHelicalTube tessellated solid — negative cubic volume (self-intersection)

**Type:** incident
**Status:** resolved (source fix landed 2026-05-20: stacked G4TwistedBox analytic primitive; grid tarball repackage still pending)
**Updated:** 2026-05-21

## Summary
`G4TessellatedSolid::SetSolidClosed()` issues `G4Exception : GeomSolids1001`
on the `TSdAHelicalTube` solid: *"negative cubic volume, please check
orientation of facets!"* — the message blames facet orientation, but static
analysis of `makeHelicalPlug` shows the winding is **correct** for all 8 side
triangles + 2 end caps (right-hand rule produces outward normals). The real
cause is **per-slice broad-face warp**: each tessellated slice's two ±x broad
faces are non-planar quads (twist accumulates linearly along the slice's
axial extent), and G4 splits each non-planar quad into two triangles using a
fixed diagonal. At extreme aspect ratios (helical050a: `dy/dx = 1044`) the
warp height exceeds the plate thickness and the two triangles representing
the +x face cross *through* the two triangles representing the −x face
*within the same slice*; G4's divergence-theorem volume integral double-counts
the self-overlap with reversed sign → net negative volume (~32.1 vs ~18 cm³
intended → ~80% mass inflation in every grid job built with this lib). G4
still constructs the solid but its internal navigation produces a flood of
`GeomNav1002` "Stuck Track" warnings during tracking. Discovered 2026-05-20
in helical050a worker logs; preflight surface-check passed because it
validates sibling overlaps, not internal self-intersection.

## Key facts
- **Warning text:**
  `Defects in solid: TSdAHelicalTube - negative cubic volume, please check
  orientation of facets!` issued by `G4TessellatedSolid::SetSolidClosed()`.
- **Cascading effect:** 1× GeomSolids1001 per worker at construction →
  thousands of GeomNav1002 "Stuck Track" / "Likely geometry overlap" per
  worker during event tracking. helical050a totals (see
  `/exp/mu2e/data/users/oksuzian/autoresearch_grid/helical050a/scan_logs/report.tsv`):
  ~28.5M GeomNav1002 events across mubeam + run1b_mubeam + mustops_ce.
  Stuck-track position `(-3925.8, -0.59, 4569.0)` (r≈22 mm, z=4569 → deep
  inside plug, not at the disc-face boundary).
- **Hit rate:** GeomSolids1001 fires in **197/200 mubeam workers, 199/200
  run1b_mubeam, 90/98 mustops_ce** for helical050a — near-100% across every
  worker that constructs the plug. Concat is unaffected (no G4).
- **Why preflight missed it:**
  - `g4.doSurfaceCheck=true` (wired in task #52) validates *sibling*
    geometric overlap, not facet winding inside a single solid.
  - Preflight scans for "Overlap" lines only; "negative cubic volume" is a
    warning, not an error, and `mu2e -n 1` exits 0.
- **Source location:** `makeHelicalPlug()` in
  `/exp/mu2e/app/users/oksuzian/autoresearch_muse/Offline/Mu2eG4/src/constructTSdA.cc:59-129`.
  Builds the solid as `nSteps` stacked twisted slices; each slice contributes
  8 triangular side facets + (at the ends) one quad cap. Vertex order verified
  at `angle=0`: front -ŷ, right +x̂, back +ŷ, left -x̂, bottom -ẑ, top +ẑ —
  all outward. **Winding is not the bug.**
- **Real cause — per-slice broad-face warp (corrected 2026-05-20).** Each
  slice's ±x faces are non-planar quads because the cross-section rotates
  linearly along the slice's axial extent. G4 splits each non-planar quad
  into two triangles using a fixed diagonal; the diagonal pair is offset
  from the true ruled surface by a warp height that scales as
  `warp ≈ dy · (angle/N) · (1/4)` where `N = nsteps`. For helical050a
  (`dy=109.6, angle=459.6° → 8.02 rad, N=100`) that's `warp ≈ 712/N mm
  = 7.12 mm`, dwarfing the plate thickness `2·dx = 0.21 mm`. The +x
  triangle-pair and −x triangle-pair therefore cross each other *within the
  same slice*. Same mechanism causes the divergence-theorem volume integral
  to over-count: actual integrated volume ≈ 32.1 cm³ vs intended ~18 cm³ —
  about an **80% mass inflation** in every grid job built with the broken
  lib.
- **Predicate (corrected):** crossover when warp ≈ `2·dx` (plate thickness):
  `N_crit ≈ dy · angle_rad / (8 · dx)`. For helical050a: `N_crit ≈ 3390`.
  Below ~3400 the solid self-intersects; above it does not. The original
  default `nsteps=100` and the empirical mitigation `nsteps=500` are both
  well below this threshold, which is why both produce GeomSolids1001.
  `nsteps=5000` would have been sufficient (no source patch needed), but at
  ~50× the facet count it is not the chosen fix.
- **Direction of bias on calo_per_pot — INVERTED from initial hypothesis
  (measured 2026-05-21).** End-to-end A/B at fixed helical050a x-point, OLD
  tessellated lib both sides, only `nsteps` differs:

  | build | calo_per_pot | s_over_sqrt_b | obj |
  |---|---|---|---|
  | helical050a (broken, n=100) | 2.54e-6 | 3.21 | 2.96 |
  | helical050a_n5000 (clean, n=5000) | **1.09e-5** | 3.65 | 2.56 |

  Clean geometry produces **4.3× higher** calo_per_pot, not lower. The
  earlier "40× vs legacy helical050" comparison was misleading — that
  contrasted against a *different* x-point (pre-Option-A render), not the
  same geometry under a different build. Real direction: the broken plug
  was **masking** calo background, not inflating it.
- **Mechanism (corrected):** the 27M-per-worker `Stuck Track` events at the
  defective plug effectively **kill background particles** before they reach
  the calo — G4 absorbs anything that gets stuck. With clean geometry, those
  particles correctly propagate downstream and deposit energy in the calo,
  raising calo_per_pot ~4×. So the broken plug is a spurious absorber, not
  a spurious scatterer-into-calo.
- **Leaderboard implication:** many low-calo helicalNNN winners on the
  pre-fix leaderboard are likely **artifacts of stuck-track absorption** in
  the broken plug. Their true calo_per_pot is substantially higher. The
  retroactive sweep needs to re-evaluate all rows; rankings will shift.
- **Upstream physics impact — mubeam yield inflation (measured 2026-05-21).**
  The broken plug doesn't just dirty downstream stages; both mubeam stages
  themselves are affected because backsplash/stuck-tracks at the TSdA
  produce spurious TargetStops. Full-stage A/B from worker `TrigReport`
  blocks (200 workers × 5000 events per build per stage):

  | stage | DS field | broken (n=100) | clean (n=5000) | inflation |
  |---|---|---|---|---|
  | `mubeam` (Run1A) | **on** | 741.8 / 5000 (14.84%) | 539.6 / 5000 (10.79%) | **+37.5%** |
  | `run1b_mubeam` (Run1B) | **off** | 16.0 / 5000 (0.32%) | 10.8 / 5000 (0.22%) | **+48.0%** |

  Both DS configurations biased high; **DS-off hit relatively harder** because
  real stops drop ~70× when the focusing field is off, so backsplash/stuck-track
  noise is a larger fraction of the signal. This is the physical channel by
  which downstream calo_per_pot inflation gets seeded — every downstream stage
  consumes biased TargetStops products from both upstream paths.
  - Implication: any pre-fix helicalNNN row's mubeam *and* run1b_mubeam yields
    are biased, not just its calo. The retroactive sweep needs to flag mubeam
    impact too, not just scan_logs warnings.

## Workflow detection (landed 2026-05-20)
End-of-workflow `scan_logs` node in [[graph-runner]] (between `harvest` and
`evaluate`) walks every worker `.log` under each stage's outstage dir and
counts:
- G4Exception, Stuck Track, Likely geometry overlap, GeomSolids1001,
  GeomNav1002, Error, Warning, FATAL, SEGV
Writes `<grid_root>/<config_name>/scan_logs/report.tsv` + `report.json`.
**Report-only** — never gates evaluate; the leaderboard row is still written
so historical context is preserved. Existing in-flight chains (graph022/023/024,
helicalL01-L05, H1/H2, yellow-star re-evals) compiled the old topology in RAM
at startup and are unaffected; only freshly-launched `python -m graph.run`
invocations include the scan.

## Fix landed (2026-05-20)

**Replaced tessellated chord construction with stacked analytic G4TwistedBox.**
`makeHelicalPlug` in `constructTSdA.cc` now computes
`N = ceil(|angle| / 85°)` segments along z, each a `G4TwistedBox` of axial
extent `2·halflength/N` and twist `angle/N`, combined via `G4UnionSolid`
(segment 0 wrapped in `G4DisplacedSolid` so the assembly's local origin sits
at the geometric midpoint). The 85° cap stays under `G4VTwistedFaceted`'s hard
~90° per-solid twist limit; consecutive segment faces are matched by per-segment
z-rotation `phi_i = -angle/2 + (i+0.5)·angle/N`. No facets, no chord crossings,
no `tsda.helical.nsteps` knob.

**Empirical mitigations that did NOT work:**
- `tsda.helical.nsteps=500` (5× the default 100) — still produces
  `GeomSolids1001` for helical050a. Per the corrected mechanism above the
  crossover is at `N_crit ≈ 3390`; 500 is well below. `nsteps ≥ 3400`
  would in fact eliminate the warning without a source patch, but at
  ~50–100× the facet count (slower G4 navigation, much larger GDML), so
  the stacked-twistedbox source fix is preferred.

**Alternate mitigation that DOES work (empirically verified 2026-05-21).**
Local-muse preflight A/B at fixed helical050a knobs, broken-tessellated lib
swapped in via `git`-snapshot revert (`/exp/mu2e/app/users/oksuzian/autoresearch_muse/.snap/_scheduled-2026-05-20-00_00_02_UTC_*/Offline/Mu2eG4/src/constructTSdA.cc`)
+ explicit-target `muse build`:

| nsteps | lib | solid reported | GeomSolids1001 | surface-check |
|---|---|---|---|---|
| 100  | OLD tessellated | `G4TessellatedSolid` | **2** | OK |
| 5000 | OLD tessellated | `G4TessellatedSolid` | **0** | OK |
| 100  | patched twistedbox | `G4UnionSolid` (6 twistedbox segs) | **0** | OK |

Confirms the predicted `N_crit ≈ 3390` boundary: n=5000 with the OLD code is
sufficient to eliminate the construction defect, no source patch needed. We
nonetheless ship the twistedbox patched lib on grid (smaller GDML, faster
nav). The n=5000 alternative is kept as a fallback in case G4 navigation ever
misbehaves on twisted-prism solids for a future material/version.
- Naive single `G4TwistedBox` (pre-stacking) — analytic, no facet bugs, but
  G4 throws `GeomSolids0002 — twist angle too big` for any total twist > π/2.
  BO search space allows angle ∈ [60, 540]°, so this would have restricted
  exploration.

**Verification (helical050a, angle=459.591°):**
- N=6 segments expected; GDML confirms 6 `<twistedbox>` + 0 `<tessellated>`
- 4 `TSdAHelicalAsm_*` intermediate union solids + final `TSdAHelicalTube`
- mu2e exit 0, zero G4Exception, zero GeomSolids errors
- Per-segment seg_twist = 459.591/6 = 76.6° ✓ inside the 85° margin

**Major preflight caveat discovered while debugging.** `cmd_preflight` in
`autoresearch_bo_michael.py:684` only sources the CVMFS MUSING (line 724)
— it never loads the patched `libmu2e_Mu2eG4.so`, so the helical plug is
constructed using the **stock** Offline code, not the patched code. Until
preflight is taught to source the local muse setup (or `Code/setup.sh` from
the shipped tarball), preflight cannot detect helical-plug bugs. See
[[preflight]] for the limitation.

**Build gotcha discovered.** `muse build Offline` reports "up to date"
without re-linking the changed lib (it stops at the package target).
Targeting the .so explicitly works: `muse build build/al9-prof-e29-p094/Offline/lib/libmu2e_Mu2eG4.so`.
See [[muse-backing-pattern]].

**Outstanding:** repackage `Code_helical_base.tar.bz2` (task #53) so grid
workers pick up the patched lib. Until then, grid jobs still run the broken
tessellated path.

**Default flipped (2026-05-21):** `HelicalMode.HELICAL_NSTEPS` 100 → 5000
(autoresearch_bo_michael.py:328). The production `Code_helical_base.tar.bz2`
is the OLD tessellated lib (swapped in for the helical050a_n5000 test on
2026-05-21, not yet swapped back). At the old default of 100 the OLD lib
floods GeomSolids1001 + 28M GeomNav1002/worker; nsteps=5000 is above
N_crit≈3390 and produces zero hits.

## Upstream-table contamination
- mmackenz `table.org` rows that use the helical plug are also built with the
  broken tessellated lib (e.g. **v113**, added 2026-05-20, *"2.50 cm Al plate
  with 80 mm hole, optimized helical plug"*, sob=2.96, calo=8.52e-8). The
  artificially-low calo is the same stuck-track-absorption artifact as the
  pre-fix helicalNNN leaderboard rows. The overlay script
  `overlay_gp_predictions_helical_mpl.py` blacklists these entries via
  `TABLE_BLACKLIST` so they don't pollute the visualization.
- New mmackenz helical-plug table rows should be added to the blacklist (or
  the underlying mmackenz workflow must rebuild against the patched lib)
  before being trusted as ground-truth.

## Cross-links
- Related: [[graph-runner]], [[tsda]], [[tsda-disc-helical-sibling-overlap]],
  [[mu2e-overlap-check]], [[preflight]]
- Source: `/exp/mu2e/app/users/oksuzian/autoresearch_muse/Offline/Mu2eG4/src/constructTSdA.cc:58-128`
- Detection: `graph/pipeline_io.py:scan_worker_logs`, `graph/nodes.py:node_scan_logs`
- Sample report: `/exp/mu2e/data/users/oksuzian/autoresearch_grid/helical050a/scan_logs/report.tsv`

## Side-by-side GDML evidence
Two `gdmldump` outputs in `/exp/mu2e/app/users/oksuzian/autoresearch/gdml_dumps/`
make the fix visually inspectable (helical050a params, identical inputs):
- `mu2e_helical050a_tessellated.gdml` (4.9 MB) — old `Code_helical_base.tar.bz2`
  lib (LD_PRELOAD'd over Run1Bak). 1 `<tessellated>` solid (TSdAHelicalTube,
  4002 facets); `GeomSolids1001 negative cubic volume` thrown live during the
  dump.
- `mu2e_helical050a_twistedbox.gdml` (4.2 MB) — new patched lib. 0 tessellated,
  6 `<twistedbox>` solids (one per 85°-cap segment, `N=ceil(459.591/85)`), 5
  `TSdAHelicalAsm_*` intermediate unions + final `TSdAHelicalTube`. Zero
  warnings.

## Open questions / TODO
- Repackage `Code_helical_base.tar.bz2` with the patched lib + ship to grid;
  re-run helical050a end-to-end and compare new `calo_per_pot` vs current
  (2.54e-6). If the new value lands near 6.5e-8 (legacy 050), confirms the
  40× bump is entirely this defect (task #53).
- Teach `cmd_preflight` to source the local muse setup (or extracted
  `Code/setup.sh`) so future helical-plug bugs surface in preflight rather
  than only in grid logs.
- Retroactive sweep: opt-in run of `scan_worker_logs` over all completed
  helicalNNN configs to flag which historical leaderboard rows are tainted
  (built with the broken lib) vs trustworthy. The ~80% mass inflation
  almost certainly biases the bo-helical leaderboard — every pre-fix
  helicalNNN row should be re-run for trustworthy ranking.
- **Alternative fix — radial subdivision of broad faces.** The stacked-twistedbox
  patch is analytic and was preferred because no facet bookkeeping is needed,
  but if a tessellated path is ever wanted again (e.g. for a material whose
  G4 navigation misbehaves under twisted-prism solids), the cheaper fix is to
  subdivide the broad ±x faces *radially* (across the long `2·dy` dimension)
  rather than only axially. The warp scales as `dy·(angle/N)/4` — it's large
  only because each broad facet spans the full ribbon width as one
  un-subdivided piece. Splitting each broad quad into `M` strips along y
  cuts the per-strip warp by `1/M²` (the warp goes as length²), so M≈8
  would suffice for helical050a where N=100 is currently 34× under threshold.
  Net facet count: 4N (axial) × 2M (radial strips) per broad face, well
  under the 5000-step purely-axial fix.
