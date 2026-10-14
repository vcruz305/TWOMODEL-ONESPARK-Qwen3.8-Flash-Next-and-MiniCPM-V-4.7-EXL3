#!/usr/bin/env bash
# Low-memory guard: stops both servers (cleanly) if MemAvailable drops below MEM_FLOOR_MIB. Started by up.sh.
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/env.sh"
while sleep 2; do
  ma="$(mem_avail_mib)"
  if (( ma < MEM_FLOOR_MIB )); then
    echo "$(date -Is) GUARD_TRIP MemAvailable=${ma}MiB < ${MEM_FLOOR_MIB}MiB; stopping both servers"
    bash "$(dirname "$0")/down.sh" --from-guard; exit 0
  fi
done
