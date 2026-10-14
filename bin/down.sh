#!/usr/bin/env bash
# Stop both servers (and the guard) by walking their real process trees. Waits until the GPU is released.
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/env.sh"
tree() { local p="$1"; echo "$p"; for c in $(pgrep -P "$p" 2>/dev/null); do tree "$c"; done; }
for n in qwen minicpm $([[ "${1:-}" == --from-guard ]] || echo guard); do
  f="$LOG_DIR/$n.pid"; [[ -f "$f" ]] || continue
  p="$(live_pid "$n")"
  if [[ -n "$p" ]]; then kill -TERM $(tree "$p") 2>/dev/null || true
  else say "$n: recorded process is gone (or its PID now belongs to another process); not signalling"; fi
  rm -f "$f"
done
for _ in $(seq 1 90); do nvidia-smi --query-compute-apps=pid --format=csv,noheader 2>/dev/null | grep -q . || break; sleep 1; done
left="$(nvidia-smi --query-compute-apps=pid --format=csv,noheader 2>/dev/null | tr '\n' ' ')"
[[ -z "$left" ]] && say "both servers stopped; GPU idle" || say "GPU still in use by: $left"
