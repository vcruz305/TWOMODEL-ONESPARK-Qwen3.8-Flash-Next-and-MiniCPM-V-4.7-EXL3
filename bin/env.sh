#!/usr/bin/env bash
# Shared settings for running Qwen3.8-Flash-Next (main agent) and MiniCPM-V 4.7 (subagents) on one DGX Spark.
# Everything here can be overridden from the environment. Both sub-recipes track the LATEST commits of the
# vcruz305/exllamav3 and vcruz305/tabbyAPI forks; nothing is pinned.
TWOMODEL_HOME="${TWOMODEL_HOME:-$HOME/twomodel-onespark}"
QWEN_RECIPE_URL="${QWEN_RECIPE_URL:-https://github.com/vcruz305/Qwen3.8-Flash-Next-EXL3-DGX-Spark-recipe.git}"
MINI_RECIPE_URL="${MINI_RECIPE_URL:-https://github.com/vcruz305/MiniCPM-V-4.7-35B-A3B-EXL3-DGX-Spark-recipe.git}"
QWEN_RECIPE="${QWEN_RECIPE:-$TWOMODEL_HOME/qwen-recipe}"
MINI_RECIPE="${MINI_RECIPE:-$TWOMODEL_HOME/minicpm-recipe}"
QWEN_RECIPE_HOME="${QWEN_RECIPE_HOME:-$TWOMODEL_HOME/qwen-runtime}"
MINI_RECIPE_HOME="${MINI_RECIPE_HOME:-$TWOMODEL_HOME/minicpm-runtime}"
QWEN_STATE="${QWEN_STATE:-$TWOMODEL_HOME/qwen-state}"
MINI_STATE="${MINI_STATE:-$TWOMODEL_HOME/minicpm-state}"
QWEN_MODEL_DIR="${QWEN_MODEL_DIR:-$HOME/models/Qwen3.8-Flash-Next-EXL3}"
MINI_MODEL_DIR="${MINI_MODEL_DIR:-$HOME/models/MiniCPM-V-4.7-35B-A3B-EXL3-SAGE-3.74bpw}"
LOG_DIR="${LOG_DIR:-$TWOMODEL_HOME/logs}"
CUDA_HOME="${CUDA_HOME:-/usr/local/cuda-13.0}"
# Base CUDA PyTorch environment for the MiniCPM recipe (its installer reuses your existing CUDA torch).
BASE_PYTHON="${BASE_PYTHON:-python3}"

# Ports
QWEN_PORT="${QWEN_PORT:-8899}"
MINI_PORT="${MINI_PORT:-8898}"

# Qwen (main agent): full 262,144-token context, one job, MTP, n-gram table streamed from NVMe (keeps ~30 GB free).
QWEN_PROFILE="${QWEN_PROFILE:-single}"
QWEN_NGRAM_RAM="${QWEN_NGRAM_RAM:-false}"

# MiniCPM (subagents): Q4 KV, 262,144 max per request, one shared KV pool, batched requests.
# 8 is the measured sweet spot for agent-sized prompts (README: Subagent concurrency).
MINI_MAX_BATCH="${MINI_MAX_BATCH:-8}"
MINI_CACHE_SIZE="${MINI_CACHE_SIZE:-1048576}"
MINI_MAX_SEQ="${MINI_MAX_SEQ:-262144}"

# Refuse to start if less than this much memory would remain (MiB), and stop both servers below it at runtime.
MEM_FLOOR_MIB="${MEM_FLOOR_MIB:-6144}"

say() { printf '==> %s\n' "$*" >&2; }
die() { printf 'error: %s\n' "$*" >&2; exit 1; }
mem_avail_mib() { awk '/MemAvailable/{print int($2/1024)}' /proc/meminfo; }
# Prints the MiniCPM API key, or nothing if the server has not written it yet. Always returns 0 so
# callers running under "set -e" can poll it while the server starts.
mini_key() { python3 -c "import json,sys;print(json.load(open(sys.argv[1]))['api_key'])" "$MINI_STATE/api_tokens.yml" 2>/dev/null || true; }
