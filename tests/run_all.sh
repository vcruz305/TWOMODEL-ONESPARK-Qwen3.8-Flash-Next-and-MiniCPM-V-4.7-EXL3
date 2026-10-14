#!/usr/bin/env bash
# Full side-by-side suite against running servers (bin/up.sh). Results land in $LOG_DIR/results-<time>/.
#   bash tests/run_all.sh            # all
#   bash tests/run_all.sh tools hermes
set -uo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
source "$ROOT/bin/env.sh"
export QWEN_PORT MINI_PORT MINI_STATE QWEN_MODEL_DIR TWOMODEL_LOG_DIR="$LOG_DIR"
MINI_KEY="$(mini_key)"; export MINI_KEY
# Preflight: refuse to run against servers that are not up, so a failed bin/up.sh can't turn into
# a page of misleading test failures.
[[ -n "$MINI_KEY" ]] || die "no MiniCPM key at $MINI_STATE/api_tokens.yml; is bin/up.sh running?"
q=$(http_code "http://127.0.0.1:$QWEN_PORT/v1/models")
m=$(http_code "http://127.0.0.1:$MINI_PORT/v1/models" "Authorization: Bearer $MINI_KEY")
[[ "$q" == 200 && "$m" == 200 ]] || die "servers not ready (qwen http=$q, minicpm http=$m); run bin/up.sh first"
rc=0
O="$LOG_DIR/results-$(date +%Y%m%d-%H%M%S)"; mkdir -p "$O"; export OUT_DIR="$O"
want="${*:-tools decode concurrency hermes longctx}"
for t in $want; do
  say "test: $t"
  case $t in
    tools)       python3 "$ROOT/tests/tools_conformance.py" qwen mini | tee "$O/tools.txt" || rc=1 ;;
    decode)      python3 "$ROOT/tests/batch_decode.py" "$MINI_PORT" 1,4,8 minicpm | tee "$O/decode-minicpm.jsonl" || rc=1
                 python3 "$ROOT/tests/batch_decode.py" "$QWEN_PORT" 1 qwen | tee "$O/decode-qwen.jsonl" || rc=1 ;;
    concurrency) python3 "$ROOT/tests/conc_sweep.py" "$O/concurrency.json" 1,2,4,8 | tee "$O/concurrency.jsonl" || rc=1 ;;
    hermes)      bash "$ROOT/tests/hermes_fanout.sh" 4 8 | tee "$O/hermes.jsonl" || rc=1 ;;
    longctx)     python3 "$ROOT/tests/longctx_side.py" "$O/longctx.json" | tee "$O/longctx.jsonl" || rc=1 ;;
    *) die "unknown test $t" ;;
  esac
done
say "results: $O"
[[ $rc == 0 ]] && say "ALL PASSED" || say "SOME TESTS FAILED (see above)"
exit $rc
