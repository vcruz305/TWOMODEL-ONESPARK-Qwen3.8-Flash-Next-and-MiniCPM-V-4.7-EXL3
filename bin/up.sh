#!/usr/bin/env bash
# Start both servers side by side: MiniCPM first (fixed-size reservation), then Qwen. Prints memory headroom.
set -euo pipefail
BIN="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$BIN/env.sh"
mkdir -p "$LOG_DIR"
export PATH="$CUDA_HOME/bin:$PATH" CUDA_HOME
unset EXL3_REF TABBY_REF
for p in "$MINI_PORT" "$QWEN_PORT"; do
  ! (exec 3<>/dev/tcp/127.0.0.1/$p) 2>/dev/null || die "port $p is already in use; run bin/down.sh or pick another port"
done
[[ -f "$MINI_MODEL_DIR/config.json" && -f "$QWEN_MODEL_DIR/config.json" ]] || die "missing pack(s); run bin/download.sh"

wait_up() { # name url header
  local name="$1" url="$2" hdr="${3:-}" pidf="$LOG_DIR/$1.pid"
  for _ in $(seq 1 450); do
    kill -0 "$(cat "$pidf")" 2>/dev/null || { tail -40 "$LOG_DIR/$name.log" >&2; die "$name server exited during startup"; }
    if [[ -n "$hdr" ]]; then code=$(curl -s -o /dev/null -w '%{http_code}' -H "$hdr" "$url"); else code=$(curl -s -o /dev/null -w '%{http_code}' "$url"); fi
    [[ "$code" == 200 ]] && return 0
    sleep 2
  done
  die "$name did not become ready"
}

say "starting MiniCPM-V 4.7 (subagents) on :$MINI_PORT  batch=$MINI_MAX_BATCH cache=$MINI_CACHE_SIZE Q4"
# Start each server detached and in the background of THIS shell (a "( ... & )" subshell would block
# until the server exits).
cd "$MINI_RECIPE"
PROFILE=long MAX_BATCH_SIZE="$MINI_MAX_BATCH" CACHE_SIZE="$MINI_CACHE_SIZE" MAX_SEQ_LEN="$MINI_MAX_SEQ" \
  BASE_PYTHON="$BASE_PYTHON" RECIPE_HOME="$MINI_RECIPE_HOME" STATE_DIR="$MINI_STATE" MODEL_DIR="$MINI_MODEL_DIR" PORT="$MINI_PORT" \
  setsid nohup bash exllamav3-tabby/serve.sh > "$LOG_DIR/minicpm.log" 2>&1 < /dev/null &
echo $! > "$LOG_DIR/minicpm.pid"
cd - >/dev/null
sleep 3
for _ in $(seq 1 60); do K="$(mini_key)"; [[ -n "$K" ]] && break; sleep 2; done
wait_up minicpm "http://127.0.0.1:$MINI_PORT/v1/models" "Authorization: Bearer $(mini_key)"
say "MiniCPM ready; MemAvailable $(mem_avail_mib) MiB"

say "starting Qwen3.8-Flash-Next (main agent) on :$QWEN_PORT  profile=$QWEN_PROFILE ngram_ram=$QWEN_NGRAM_RAM"
cd "$QWEN_RECIPE"
RECIPE_HOME="$QWEN_RECIPE_HOME" STATE_DIR="$QWEN_STATE" MODEL_DIR="$QWEN_MODEL_DIR" \
  PROFILE="$QWEN_PROFILE" NGRAM_RAM="$QWEN_NGRAM_RAM" PORT="$QWEN_PORT" \
  setsid nohup bash exllamav3-tabby/serve.sh > "$LOG_DIR/qwen.log" 2>&1 < /dev/null &
echo $! > "$LOG_DIR/qwen.pid"
cd - >/dev/null
wait_up qwen "http://127.0.0.1:$QWEN_PORT/v1/models"
ma="$(mem_avail_mib)"
say "both servers ready; MemAvailable $ma MiB (floor $MEM_FLOOR_MIB)"
(( ma > MEM_FLOOR_MIB )) || { bash "$BIN/down.sh"; die "memory below floor after load; stopped both"; }
setsid nohup bash "$BIN/guard.sh" > "$LOG_DIR/guard.log" 2>&1 < /dev/null &
echo $! > "$LOG_DIR/guard.pid"
cat >&2 <<EOF
Qwen    (main):      http://127.0.0.1:$QWEN_PORT/v1   model Qwen3.8-Flash-Next-EXL3   (no key on localhost)
MiniCPM (subagents): http://127.0.0.1:$MINI_PORT/v1   model MiniCPM-V-4.7-35B-A3B-EXL3-SAGE-3.74bpw
                     key: $MINI_STATE/api_tokens.yml (api_key)
EOF
