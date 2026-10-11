# Kit param rules are decided on the names the kit receives

The rules on what a step (or the preflight) sends its kit lived in six
places that disagreed, mostly because the loader checked names before a
profile is split into `<p>_0 .. <p>_{N-1}` and the run built them after.
Eight cases reproduced at `ed39d1b` (none in a live study): a beamkit
`deck_params` value silently replaced a split profile element (the board
recorded one number, G4beamline ran another); `params: {"r": <profile>,
"r_1": <knob>}` loaded and one value replaced the other by JSON key order;
a split element and a `params_from` name clashed only after the upstream
step ran; a preflight param clashing with a kit setting broke every point
and passed the launch check; the launch check compared only `<p>_0` with a
kit's `describe`, and anakit's used the names before the split; a knob
mapped to prodtools `njobs` skipped the 200-job check; a path nested in a
setting escaped the path rule.

Decided 2026-10-11: one module, `core/kit_params.py`, lists every name a
kit receives, after the split, with every origin that produces it, and the
loader, the launch check and the run all ask it. Every name has exactly one
origin, and nothing overrides anything (the old "a fixed value may override
a kit setting" never applied to a loaded study and is dropped). A mapping
may not name what the kit reads itself (`KitDecl.own_params` and
`reserved_params`). A path inside a nested value is refused.

Consequences: a study that used to load and break later is refused at
load, and since every study loads when any command starts, a refused file
on the study path stops every command until it is fixed. A step's job count
is never taken from the point (the 2026-10-08 mapped `njobs` is removed):
the dry-run budget is always a number, the 200-job cap on a fixed njobs is checked at load,
and a point's noise does not depend on its own job count.
