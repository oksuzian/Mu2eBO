# refresh-foils-slides

**Type:** driver
**Status:** active
**Updated:** 2026-05-31

## Summary
`tools/refresh_foils_slides.sh` rebuilds the `docs/foils_talk.*` artifacts
from the latest GP-cloud render so the GitHub Pages slide deck at
https://oksuzian.github.io/Mu2eBO/foils_talk.html stays in sync with the
animated GIF the 4-hourly cron posts to Slack. Safer split: this script
**does not commit or push** — operator reviews `git status docs/` then
pushes manually.

## Key facts
- Inputs (read-only):
  `/exp/mu2e/data/users/oksuzian/autoresearch_grid/mmackenz_table_plots/gp_predicted_foils_cloud.{gif,png}`
- Outputs (written into `docs/`):
  `gp_predicted_foils_cloud.gif`, optional `.png`,
  `foils_talk.html` (re-rendered from `foils_talk.md`).
- **Image-copy gap (resolved 2026-05-31):** the script now also copies
  `botorch_predicted_foils_cloud.png` and `diversity_overlay_foils.png`
  from `mmackenz_table_plots/` into `docs/` (WARN-but-continue if either
  source is missing). Previously these were hand-cp'd, which let them
  decay independently of the GP cloud.
- Renderer: `npx -y @marp-team/marp-cli@latest --html --allow-local-files`.
  Confirmed working with v4.4.0; no system `marp` binary required.
  `--allow-local-files` lets the GIF be inlined as data-URI.
- Cron `d3cf6d4b` (session-only, 7-day expiry): runs at `:22 */4 * * *`,
  9 min after the existing GIF-render cron `41e49197` (`:13`) finishes
  writing the new GIF — ordering is load-bearing.
- The script does **not** touch the slide content (`foils_talk.md`)
  itself; if md needs updating, that's a manual edit. Memory rule
  "do NOT modify slide deck" applies to `slides/slides.tex` (LaTeX);
  `docs/foils_talk.md` is editable when asked.
- **Highlights templating (added 2026-05-30):** before marp re-render,
  `tools/stamp_foils_highlights.py` rewrites the block between
  `<!-- highlights:start -->` / `<!-- highlights:end -->` markers in
  `docs/foils_talk.md:137-141` (slide 9 caption) from
  `leaderboard_bo_foils_v1.tsv`. Stamps `n_evals`, best `obj`/`sob`/`calo`,
  calo floor, modal `n_down` + mean `rOut` over top-5. Idempotent
  (re-run on unchanged leaderboard prints `[stamp] no change`). Prose
  outside the markers is preserved; if you remove the markers the
  caption stops auto-updating.
- **Stamp bug (fixed 2026-05-31):** the first highlights bullet was
  hardcoded `"frontier still expanding (not saturated)"` and contradicted
  the deck's own slide 14 SAT verdict. Now `stamp_foils_highlights.py`
  shells out to `saturation_report.py --prefix foilsX`, parses its
  VERDICT line, and emits `"frontier saturated"` / `"frontier still
  expanding"` / `"frontier status unknown"` (fallback if the script
  can't run). 60 s timeout.
- **Caption refresh (added 2026-05-31):** `tools/refresh_foils_talk_captions.py`
  rewrites three more leaderboard-derived regions before marp:
  `<!-- botorch-cross-check:start/end -->` (n + sob_max + calo_min),
  `<!-- run-timeline:start/end -->` (total + per-prefix breakdown),
  and the YAML `footer:` line by line-regex (HTML comments aren't
  legal inside YAML frontmatter). Idempotent — prints `[caps] no change`
  if leaderboard unchanged. The four marker regions and the footer
  line are owned by this pair of scripts; do not hand-edit the regions
  themselves, edit prose outside the markers.
- **Full-deck refresh skill (added 2026-05-31):** the `/refresh-foils-talk`
  skill at `.claude/skills/refresh-foils-talk/SKILL.md` is the heavier
  cousin: it renders all four plots (GP cloud, BoTorch, diversity overlay)
  in `.venv-botorch` *before* calling this shell script. Diversity overlay
  is the bottleneck (~90 min); pass `--skip-overlay` for a fast refresh.

## Cross-links
- Related: [[foils-slides-refresh]] (skill that wraps this script)
- Related: [[gp-cloud-rendering]] (what produces the input GIF)
- Related: [[github-pages-publish-dir]] (why `docs/` is the publish dir)
- Related: [[slack-file-upload-flow]] (sibling Slack cron `41e49197`)
- Source files: `tools/refresh_foils_slides.sh`,
  `tools/stamp_foils_highlights.py`, `tools/refresh_foils_talk_captions.py`,
  `.claude/skills/refresh-foils-talk/SKILL.md`

## Open questions / TODO
- Decide whether `docs/saturation_bo_foils_v1*.png` (untracked legacy
  outputs) should be committed or `.gitignore`'d so the cron's
  `git status docs/` report stays clean.
- Mirror an analogous script for the helical talk if/when a helical
  cron is added.
