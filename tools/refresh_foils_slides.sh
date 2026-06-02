#!/usr/bin/env bash
# Refresh foils talk artifacts in docs/ from the latest GP cloud render.
# Safer mode: copies images + re-renders HTML, but does NOT commit/push.
# Operator reviews `git status docs/` then commits manually.
#
# Steps:
#   1. Copy fresh GIF + PNG from autoresearch_grid/mmackenz_table_plots
#   2. Re-render docs/foils_talk.html from docs/foils_talk.md via marp-cli
#   3. Print git status for docs/ so the operator knows what changed
#
# Companion cron prompt: see CronList output for the 4h refresh job.

set -euo pipefail

ROOT=/exp/mu2e/app/users/oksuzian/autoresearch
DOCS="$ROOT/docs"
PLOTS=/exp/mu2e/data/users/oksuzian/autoresearch_grid/mmackenz_table_plots

GIF_SRC="$PLOTS/gp_predicted_foils_cloud.gif"
PNG_SRC="$PLOTS/gp_predicted_foils_cloud.png"
BOTORCH_SRC="$PLOTS/botorch_predicted_foils_cloud.png"
DIVERSITY_SRC="$PLOTS/diversity_overlay_foils.png"

if [[ ! -f "$GIF_SRC" ]]; then
  echo "[refresh-slides] missing $GIF_SRC — render it first" >&2
  exit 1
fi

cp -p "$GIF_SRC" "$DOCS/gp_predicted_foils_cloud.gif"
# PNG ships only in Slack today; keep optional copy in docs in case slide refs it.
[[ -f "$PNG_SRC" ]] && cp -p "$PNG_SRC" "$DOCS/gp_predicted_foils_cloud.png" || true
# Slide deck also embeds BoTorch cross-check + diversity overlay images.
# These are not always present; warn but don't fail if missing.
if [[ -f "$BOTORCH_SRC" ]]; then
  cp -p "$BOTORCH_SRC" "$DOCS/botorch_predicted_foils_cloud.png"
else
  echo "[refresh-slides] WARN: missing $BOTORCH_SRC (slide will show stale)" >&2
fi
if [[ -f "$DIVERSITY_SRC" ]]; then
  cp -p "$DIVERSITY_SRC" "$DOCS/diversity_overlay_foils.png"
else
  echo "[refresh-slides] WARN: missing $DIVERSITY_SRC (slide will show stale)" >&2
fi

# Regenerate saturation panels (slides 9-10). The _slim/_hv/_pf variants
# don't live in mmackenz_table_plots/ — they're rendered straight into docs/
# from the live leaderboard via saturation_report.py with --panels.
SAT=/exp/mu2e/data/users/oksuzian/autoresearch_grid/mmackenz_table_plots/saturation_report.py
LB="$ROOT/leaderboard_bo_foils_v1.tsv"
VENV="$ROOT/.venv-botorch/bin/python"
if [[ -f "$LB" && -x "$VENV" && -f "$SAT" ]]; then
  "$VENV" "$SAT" "$LB" --prefix foilsX --panels hitrate,regret \
    --out "$DOCS/saturation_bo_foils_v1_slim.png" 2>&1 | tail -1
  "$VENV" "$SAT" "$LB" --prefix foilsX --panels hv \
    --out "$DOCS/saturation_bo_foils_v1_hv.png" 2>&1 | tail -1
  "$VENV" "$SAT" "$LB" --prefix foilsX --panels pf \
    --out "$DOCS/saturation_bo_foils_v1_pf.png" 2>&1 | tail -1
else
  echo "[refresh-slides] WARN: skipping saturation panels (missing $LB or $VENV or $SAT)" >&2
fi

# Stamp leaderboard-derived numbers into foils_talk.md highlights block.
# Idempotent: rewrites only the region between <!-- highlights:start/end -->.
if [[ -x "$VENV" ]]; then
  "$VENV" "$ROOT/tools/stamp_foils_highlights.py" || \
    echo "[refresh-slides] WARN: stamp_foils_highlights.py failed (continuing)" >&2
fi

# Refresh the larger data-derived caption regions
# (botorch-cross-check, run-timeline, footer line).
if [[ -x "$VENV" ]]; then
  "$VENV" "$ROOT/tools/refresh_foils_talk_captions.py" || \
    echo "[refresh-slides] WARN: refresh_foils_talk_captions.py failed (continuing)" >&2
fi

# Re-render HTML. --allow-local-files lets the GIF be inlined as data URI.
cd "$DOCS"
npx -y @marp-team/marp-cli@latest \
  --html --allow-local-files \
  foils_talk.md -o foils_talk.html \
  2>&1 | grep -v "^npm" || true

echo
echo "[refresh-slides] docs/ status (review then commit + push manually):"
cd "$ROOT"
git status --short docs/
