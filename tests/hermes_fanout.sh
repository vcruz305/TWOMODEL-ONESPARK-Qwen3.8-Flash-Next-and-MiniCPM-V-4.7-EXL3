#!/usr/bin/env bash
# Real Hermes fan-out: Qwen main agent delegates N parallel file tasks to MiniCPM subagents.
# usage: hermes_fanout.sh N1 N2 ...    (sets delegation.max_concurrent_children = max N)
set -u
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"; source "$ROOT/bin/env.sh"
export HERMES_HOME="${HERMES_HOME:-$HOME/.hermes-twomodel}"
HERMES_BIN="${HERMES_BIN:-$(command -v hermes)}"
[[ -x "$HERMES_BIN" ]] || die "hermes not found; install Hermes Agent first (README)"
MAXN=0; for n in "$@"; do [ $n -gt $MAXN ] && MAXN=$n; done
grep -n "max_concurrent_children" $HERMES_HOME/config.yaml >&2
R="${OUT_DIR:-$LOG_DIR}/hermes-fanout-$(date +%H%M%S)"; mkdir -p "$R"; echo "OUT $R" >&2
bad=0
for N in "$@"; do
  W=$R/n$N; mkdir -p $W; cd $W
  files=""; for i in $(seq 1 $N); do
    seq $((i*1000)) $((i*1000+60)) | awk -v k=$i '{print "row", $1, "v", ($1*k+7)%101}' > d$i.txt; files="$files d$i.txt"; done
  q0=$(grep -c "chat/completions" "$LOG_DIR/qwen.log"); m0=$(grep -c "chat/completions" "$LOG_DIR/minicpm.log")
  P="Use the delegate_task tool exactly once, with a tasks array containing exactly $N tasks, one per file, for these files in $W:$files. Each subagent must read its one file and return the sum of the last column as a number. Do not read the files yourself. After all results return, reply with exactly one line per file in the form 'dK.txt: SUM' and nothing else."
  t0=$(date +%s.%N)
  timeout 1800 "$HERMES_BIN" chat -q "$P" --oneshot -Q --yolo -t terminal,file,delegation > out.txt 2> err.txt; rc=$?
  t1=$(date +%s.%N)
  q1=$(grep -c "chat/completions" "$LOG_DIR/qwen.log"); m1=$(grep -c "chat/completions" "$LOG_DIR/minicpm.log")
  python3 - "$N" "$rc" "$t0" "$t1" "$((q1-q0))" "$((m1-m0))" <<'EOF' | tee -a $R/summary.jsonl
import json, re, sys, glob
N, rc, t0, t1, qreq, mreq = int(sys.argv[1]), int(sys.argv[2]), float(sys.argv[3]), float(sys.argv[4]), int(sys.argv[5]), int(sys.argv[6])
truth = {f"d{i}.txt": sum(int(l.split()[-1]) for l in open(f"d{i}.txt")) for i in range(1, N + 1)}
out = open("out.txt", errors="ignore").read()
got = {m.group(1): int(m.group(2)) for m in re.finditer(r"(d\d+\.txt)\W+(\d+)", out)}
child_s = [float(x) for x in re.findall(r"✓ \[set \d+ · \d+/\d+\][^\n(]*\((\d+\.\d+)s\)", out)]
fails = len(re.findall(r"✗|⚠️ Subagent failed", out))
print(json.dumps({"n": N, "rc": rc, "wall_s": round(t1 - t0, 1), "correct": sum(got.get(k) == v for k, v in truth.items()),
                  "children_ok": len(child_s), "children_failed": fails,
                  "child_s_max": max(child_s) if child_s else None, "child_s_median": sorted(child_s)[len(child_s)//2] if child_s else None,
                  "qwen_requests": qreq, "minicpm_requests": mreq}))
for k, v in truth.items():
    if got.get(k) != v:
        print(f"WRONG {k}: subagent answered {got.get(k)}, correct sum is {v}", file=sys.stderr)
ok = rc == 0 and all(got.get(k) == v for k, v in truth.items()) and qreq > 0 and mreq > 0
sys.exit(0 if ok else 1)
EOF
  [[ ${PIPESTATUS[0]} == 0 ]] || bad=1
done
echo FANOUT_DONE >&2
exit $bad
