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
# FANOUT_SCHEMA=1: ask the main agent to attach an output_schema to every task, which makes Hermes run its
# output-contract correction turn whenever a subagent answers in prose (the path that broke subagents).
SCHEMA_HINT=""
[[ "${FANOUT_SCHEMA:-0}" == 1 ]] && SCHEMA_HINT=' Give EVERY task the output_schema {"type": "object", "properties": {"sum": {"type": "integer"}}, "required": ["sum"]}.'
echo "schema_mode=${FANOUT_SCHEMA:-0}" >&2
for N in "$@"; do
  W=$R/n$N; mkdir -p $W; cd $W
  files=""; for i in $(seq 1 $N); do
    seq $((i*1000)) $((i*1000+60)) | awk -v k=$i '{print "row", $1, "v", ($1*k+7)%101}' > d$i.txt; files="$files d$i.txt"; done
  q0=$(grep -c "chat/completions" "$LOG_DIR/qwen.log"); m0=$(grep -c "chat/completions" "$LOG_DIR/minicpm.log")
  P="Use the delegate_task tool exactly once, with a tasks array containing exactly $N tasks, one per file, for these files in $W:$files. Each subagent must read its one file and return the sum of the last column as a number. Do not read the files yourself.${SCHEMA_HINT} After all results return, reply with exactly one line per file in the form 'dK.txt: SUM' and nothing else."
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
# Score every SUBAGENT's own final answer from Hermes's session database, not only the main agent's
# reply: the main agent can paper over wrong subagent answers by recomputing them itself.
import os, sqlite3
def answer_value(text, fname):
    """The number a subagent gave as its final answer. In order: a JSON "sum" field; a bare number on the
    reply's last non-empty line; the last **bold** number; the number after the LAST 'sum/total ... is/=/:';
    otherwise the only distinct number in the reply. Numbers inside file names (d4.txt) or paths are never
    the answer. None if nothing qualifies."""
    t = text.replace(",", "")
    m = re.findall(r'"sum"\s*:\s*(-?\d+)', t)
    if m: return int(m[-1])
    lines = [l.strip(" *`.") for l in t.strip().splitlines() if l.strip()]
    if lines and re.fullmatch(r"-?\d+", lines[-1]): return int(lines[-1])
    m = re.findall(r"\*\*(-?\d+)\*\*", t)
    if m: return int(m[-1])
    m = re.findall(r"\b(?:sum|total)\b[^\n]{0,60}?(?:\bis\b|=|:)\s*\**(-?\d+)\b(?![^\n]*[=+])", t, flags=re.I)
    if m: return int(m[-1])
    stripped = re.sub(r"[\w./-]*d\d+\.txt", " ", t)
    nums = re.findall(r"(?<![\w.])-?\d+(?![\w.])", stripped)
    return int(nums[0]) if len(set(nums)) == 1 else None
sid = (re.findall(r"session_id:\s*(\S+)", out + open("err.txt", errors="ignore").read()) or [None])[-1]
child_answers, retries, own_work = {}, 0, False
db = os.path.join(os.environ["HERMES_HOME"], "state.db")
if sid and os.path.exists(db):
    cur = sqlite3.connect(db).cursor()
    for (kid,) in cur.execute("select id from sessions where parent_session_id=? order by started_at", (sid,)).fetchall():
        rows = cur.execute("select role, coalesce(content,'') from messages where session_id=? order by id", (kid,)).fetchall()
        task = next((c for r, c in rows if r == "user"), "")
        fname = (re.findall(r"(d\d+\.txt)", task) or [None])[0]
        final = next((c for r, c in reversed(rows) if r == "assistant" and c.strip()), "")
        retries += any(r == "user" and "output contract validator" in c for r, c in rows)
        if fname: child_answers[fname] = answer_value(final, fname)
    for (tc,) in cur.execute("select coalesce(tool_calls,'') from messages where session_id=? and role='assistant'", (sid,)):
        own_work |= ('"terminal"' in tc or '"read_file"' in tc)
child_correct = sum(child_answers.get(k) == v for k, v in truth.items())
print(json.dumps({"n": N, "rc": rc, "wall_s": round(t1 - t0, 1), "correct": sum(got.get(k) == v for k, v in truth.items()),
                  "child_correct": child_correct, "schema_retries": retries, "parent_did_the_work": own_work,
                  "children_ok": len(child_s), "children_failed": fails,
                  "child_s_max": max(child_s) if child_s else None, "child_s_median": sorted(child_s)[len(child_s)//2] if child_s else None,
                  "qwen_requests": qreq, "minicpm_requests": mreq}))
for k, v in truth.items():
    if got.get(k) != v:
        print(f"WRONG final {k}: main agent reported {got.get(k)}, correct sum is {v}", file=sys.stderr)
    if child_answers.get(k) != v:
        print(f"WRONG subagent {k}: subagent answered {child_answers.get(k)}, correct sum is {v}", file=sys.stderr)
if own_work:
    print("NOTE main agent read/computed the files itself instead of relying on its subagents", file=sys.stderr)
ok = (rc == 0 and all(got.get(k) == v for k, v in truth.items()) and child_correct == N
      and qreq > 0 and mreq > 0)
sys.exit(0 if ok else 1)
EOF
  [[ ${PIPESTATUS[0]} == 0 ]] || bad=1
done
echo FANOUT_DONE >&2
exit $bad
