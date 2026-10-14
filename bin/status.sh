#!/usr/bin/env bash
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/env.sh"
q=$(http_code "http://127.0.0.1:$QWEN_PORT/v1/models")
m=$(http_code "http://127.0.0.1:$MINI_PORT/v1/models" "Authorization: Bearer $(mini_key)")
echo "qwen    :$QWEN_PORT  http=$q"
echo "minicpm :$MINI_PORT  http=$m"
echo "MemAvailable $(mem_avail_mib) MiB  (guard floor $MEM_FLOOR_MIB)"
nvidia-smi --query-compute-apps=pid,used_memory --format=csv,noheader 2>/dev/null
for n in qwen minicpm; do echo "$n engine: $(grep -a -m1 'exllamav3 version' "$LOG_DIR/$n.log" 2>/dev/null | sed 's/.*version: //')"; done
