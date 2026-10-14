#!/usr/bin/env bash
# Full side-by-side suite against running servers (bin/up.sh). Results land in $LOG_DIR/results-<time>/.
#   bash tests/run_all.sh            # all
#   bash tests/run_all.sh tools hermes
set -uo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
source "$ROOT/bin/env.sh"
export QWEN_PORT MINI_PORT MINI_KEY="$(mini_key)" QWEN_MODEL_DIR TWOMODEL_LOG_DIR="$LOG_DIR"
O="$LOG_DIR/results-$(date +%Y%m%d-%H%M%S)"; mkdir -p "$O"; export OUT_DIR="$O"
want="${*:-tools decode concurrency hermes longctx}"
for t in $want; do
  say "test: $t"
  case $t in
    tools)       python3 "$ROOT/tests/tools_conformance.py" qwen mini | tee "$O/tools.txt" ;;
    decode)      python3 "$ROOT/tests/batch_decode.py" "$MINI_PORT" 1,4,8 minicpm | tee "$O/decode-minicpm.jsonl"
                 python3 "$ROOT/tests/batch_decode.py" "$QWEN_PORT" 1 qwen | tee "$O/decode-qwen.jsonl" ;;
    concurrency) python3 "$ROOT/tests/conc_sweep.py" "$O/concurrency.json" 1,2,4,8 | tee "$O/concurrency.jsonl" ;;
    hermes)      bash "$ROOT/tests/hermes_fanout.sh" 4 8 | tee "$O/hermes.jsonl" ;;
    longctx)     python3 "$ROOT/tests/longctx_side.py" "$O/longctx.json" | tee "$O/longctx.jsonl" ;;
    *) die "unknown test $t" ;;
  esac
done
say "results: $O"
