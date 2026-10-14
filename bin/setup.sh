#!/usr/bin/env bash
# Clone (or update) both sub-recipes and build each runtime from the LATEST fork commits.
# Re-run any time to pick up new fork commits. Never touches running servers.
set -euo pipefail
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/env.sh"
mkdir -p "$TWOMODEL_HOME" "$LOG_DIR"
sync_recipe() {
  local url="$1" dir="$2"
  if [[ -d "$dir/.git" ]]; then
    [[ -z "$(git -C "$dir" status --porcelain)" ]] || die "$dir has local changes; refusing to update it"
    git -C "$dir" pull -q --ff-only
  else
    git clone -q "$url" "$dir"
  fi
  say "$(basename "$dir") at $(git -C "$dir" log -1 --format='%h %s')"
}
sync_recipe "$QWEN_RECIPE_URL" "$QWEN_RECIPE"
sync_recipe "$MINI_RECIPE_URL" "$MINI_RECIPE"
export PATH="$CUDA_HOME/bin:$PATH" CUDA_HOME
unset EXL3_REF TABBY_REF   # always latest fork heads
say "building Qwen runtime (latest vcruz305/exllamav3 master + tabbyAPI main)"
RECIPE_HOME="$QWEN_RECIPE_HOME" STATE_DIR="$QWEN_STATE" bash "$QWEN_RECIPE/exllamav3-tabby/setup.sh"
say "building MiniCPM runtime (latest vcruz305/exllamav3 master + tabbyAPI main)"
RECIPE_HOME="$MINI_RECIPE_HOME" STATE_DIR="$MINI_STATE" BASE_PYTHON="$BASE_PYTHON" bash "$MINI_RECIPE/exllamav3-tabby/setup.sh"
say "both runtimes ready. Next: bin/download.sh, then bin/up.sh"
