#!/usr/bin/env python3
"""Subagent concurrency on one Spark: N concurrent MiniCPM agent-style requests (system prompt + tool schemas +
~6K-token working context, 300 output tokens) while the Qwen main agent decodes one stream continuously.
Per N: per-request decode tok/s, aggregate MiniCPM tok/s, p50/p95 latency, TTFT, Qwen main-agent tok/s, errors,
MemAvailable minimum. Usage: conc_sweep.py OUT.json N1,N2,...  [--no-qwen]"""
import json, sys, time, threading, urllib.request, statistics as st, random, re
import os
QPORT = int(os.environ.get("QWEN_PORT", "8899")); MPORT = int(os.environ.get("MINI_PORT", "8898"))
KEY = os.environ.get("MINI_KEY") or __import__("json").load(open(os.path.expanduser(os.environ.get("MINI_STATE", "~/twomodel-onespark/minicpm-state")) + "/api_tokens.yml"))["api_key"]
OUT, NS = sys.argv[1], [int(x) for x in sys.argv[2].split(",")]
WITH_QWEN = "--no-qwen" not in sys.argv
TOOLS = [{"type": "function", "function": {"name": n, "description": d, "parameters": {"type": "object",
          "properties": {"path": {"type": "string"}, "command": {"type": "string"}, "pattern": {"type": "string"}}}}}
         for n, d in [("read_file", "Read a file"), ("terminal", "Run a shell command"), ("search_files", "Search files"),
                      ("write_file", "Write a file"), ("patch", "Edit a file"), ("web_search", "Search the web")]]
SYSTEM = ("You are a focused subagent. Complete the task using the provided context and tools, then return a "
          "structured summary: what you did, what you found, files modified, issues. " * 8)
def context_blob(seed, words=4200):
    rnd = random.Random(seed)
    vocab = ("def class return import self value config server request response error handler cache token "
             "worker queue thread memory buffer stream parse json yaml path file line index offset result").split()
    lines = []
    for i in range(words // 12):
        lines.append(f"{i:04d}: " + " ".join(rnd.choice(vocab) for _ in range(12)))
    return "\n".join(lines)
def agent_req(i, n, res):
    msgs = [{"role": "system", "content": SYSTEM},
            {"role": "user", "content": f"Task {i}: Below is a log excerpt from service #{i}. Summarize the main recurring "
             f"themes in a detailed technical paragraph (about 250 words). Do not call tools.\n\n" + context_blob(i * 7919 + n)}]
    body = {"model": "MiniCPM-V-4.7-35B-A3B-EXL3-SAGE-3.74bpw", "messages": msgs, "tools": TOOLS, "max_tokens": 300,
            "temperature": 0, "stream": True, "stream_options": {"include_usage": True},
            "chat_template_kwargs": {"enable_thinking": False}}
    t0 = time.time(); first = None; usage = {}; err = None
    try:
        r = urllib.request.urlopen(urllib.request.Request(f"http://127.0.0.1:{MPORT}/v1/chat/completions", json.dumps(body).encode(),
              {"Content-Type": "application/json", "Authorization": "Bearer " + KEY}), timeout=1800)
        for line in r:
            line = line.strip()
            if not line.startswith(b"data:") or line[5:].strip() == b"[DONE]": continue
            ev = json.loads(line[5:])
            if ev.get("usage"): usage = ev["usage"]
            for ch in ev.get("choices", []):
                if (ch.get("delta") or {}).get("content") and first is None: first = time.time()
    except Exception as e: err = repr(e)[:200]
    t1 = time.time()
    res.append({"i": i, "err": err, "ttft": (first - t0) if first else None, "lat": t1 - t0,
                "prompt_tokens": usage.get("prompt_tokens"), "completion_tokens": usage.get("completion_tokens"),
                "decode_tps": usage.get("completion_tokens_per_sec"), "t0": t0, "t1": t1})
QWEN = {"tps": [], "stop": False}
def qwen_loop():
    while not QWEN["stop"]:
        body = {"model": "Qwen3.8-Flash-Next-EXL3", "messages": [{"role": "user", "content":
                "Write a long, detailed essay on the history of compilers. No lists."}], "max_tokens": 400,
                "temperature": 0, "enable_thinking": False}
        try:
            d = json.load(urllib.request.urlopen(urllib.request.Request(f"http://127.0.0.1:{QPORT}/v1/chat/completions",
                    json.dumps(body).encode(), {"Content-Type": "application/json"}), timeout=900))
            QWEN["tps"].append((time.time(), d["usage"].get("completion_tokens_per_sec")))
        except Exception as e:
            QWEN["tps"].append((time.time(), None))
def memavail():
    return int(re.search(r"MemAvailable:\s+(\d+)", open("/proc/meminfo").read()).group(1)) // 1024
results = []
for n in NS:
    if WITH_QWEN:
        QWEN.update(tps=[], stop=False); qt = threading.Thread(target=qwen_loop, daemon=True); qt.start(); time.sleep(3)
    mem_min = [memavail()]; done = threading.Event()
    def memwatch():
        while not done.is_set(): mem_min[0] = min(mem_min[0], memavail()); time.sleep(0.5)
    mw = threading.Thread(target=memwatch, daemon=True); mw.start()
    res = []; T0 = time.time()
    ths = [threading.Thread(target=agent_req, args=(i, n, res)) for i in range(n)]
    [t.start() for t in ths]; [t.join() for t in ths]
    T1 = time.time(); done.set()
    if WITH_QWEN:
        QWEN["stop"] = True; qt.join(timeout=900)
    ok = [r for r in res if not r["err"]]
    toks = sum(r["completion_tokens"] or 0 for r in ok)
    qv = [v for (t, v) in QWEN["tps"] if v and t <= T1 + 1] if WITH_QWEN else []
    row = {"n": n, "ok": len(ok), "errors": [r["err"] for r in res if r["err"]][:3],
           "prompt_tokens_median": st.median([r["prompt_tokens"] for r in ok if r["prompt_tokens"]]) if ok else None,
           "per_req_decode_tps_median": round(st.median([r["decode_tps"] for r in ok if r["decode_tps"]]), 2) if ok else None,
           "aggregate_out_tps": round(toks / (T1 - T0), 1),
           "lat_p50_s": round(st.median([r["lat"] for r in ok]), 1) if ok else None,
           "lat_max_s": round(max(r["lat"] for r in ok), 1) if ok else None,
           "ttft_p50_s": round(st.median([r["ttft"] for r in ok if r["ttft"]]), 2) if ok else None,
           "ttft_max_s": round(max(r["ttft"] for r in ok if r["ttft"]), 2) if ok else None,
           "qwen_main_tps_median": round(st.median(qv), 1) if qv else None, "qwen_samples": len(qv),
           "memavail_min_mib": mem_min[0], "wall_s": round(T1 - T0, 1)}
    results.append(row); print(json.dumps(row), flush=True)
    json.dump({"with_qwen": WITH_QWEN, "rows": results}, open(OUT, "w"), indent=1)
    time.sleep(5)
print("SWEEP_DONE")
