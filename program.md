# Run 1A CE Sensitivity — Stopping Target Thickness Scan

## Goal
Maximize **Run1A Coherent Electron (CE) S/√B** in the rough sensitivity analysis,
by scanning a single knob: the muon stopping target foil half-thickness.

## Knob
- `stoppingTarget.halfThicknesses` (mm half-thickness of each Al foil)
- Baseline (config_v00, 37-foil): `0.0528 mm` (full thickness 0.1056 mm)
- Allowed range: **[0.025, 0.150] mm**

## Pipeline
Each iteration forks `config_v00` → `config_tNNNN` (where NNNN encodes the proposed
half-thickness ×10000), overrides the foil half-thickness in
`config_tNNNN/run1a_beam/geom.txt`, runs Run1A-only (run1a_mubeam → run1a_mustops),
and reads `S/√B` from the rough sensitivity analysis log.

## Physics
Two competing effects:
- **Thicker foils** → more muon stops → linear gain in CE signal events.
- **Thicker foils** → more energy loss & multiple scattering before tracker
  → broader CE momentum peak → wider optimal window → more cosmic background.
The cosmic background is hard-coded at `~1.8e-3 events/s/MeV/c`, so cosmics scale
linearly with window width. There should be an optimum where signal-acceptance gain
stops outpacing the resolution loss.

## How to propose
- Look at history. With **<3 points**, spread out across the range to characterize the curve.
- Once a peak is visible, **bisect around the best** half-thickness.
- Avoid points within `0.005 mm` of any tried thickness.
- Stay strictly inside `[0.025, 0.150]`.

## Output format (strict)
Reply with **only** a JSON object on a single line, no prose:
`{"thickness": <float in mm>, "rationale": "<one short sentence>"}`
