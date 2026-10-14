#!/usr/bin/env bash
# Download both packs (skip either by setting SKIP_QWEN=1 / SKIP_MINI=1). Existing complete downloads are reused.
set -euo pipefail
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/env.sh"
if [[ "${SKIP_QWEN:-0}" != 1 ]]; then
  say "Qwen3.8-Flash-Next EXL3 3.05bpw -> $QWEN_MODEL_DIR"
  "$QWEN_RECIPE_HOME/venv/bin/hf" download turboderp/Qwen3.8-Flash-Next-exl3 --revision 3.05bpw_h5_ng5 --local-dir "$QWEN_MODEL_DIR"
fi
if [[ "${SKIP_MINI:-0}" != 1 ]]; then
  say "MiniCPM-V 4.7 SAGE EXL3 3.74bpw + dSparK drafter -> $MINI_MODEL_DIR"
  RECIPE_HOME="$MINI_RECIPE_HOME" STATE_DIR="$MINI_STATE" MODEL_DIR="$MINI_MODEL_DIR" \
    bash "$MINI_RECIPE/exllamav3-tabby/download.sh" --include-drafter
fi
