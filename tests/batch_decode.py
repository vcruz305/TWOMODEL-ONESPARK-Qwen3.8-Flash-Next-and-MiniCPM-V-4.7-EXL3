#!/usr/bin/env python3
"""Batched decode scaling through TabbyAPI: N concurrent short prompts (~60 tokens), 256 tokens out, greedy.
Reports aggregate decode tok/s during the overlapped decode window. usage: batch_decode.py PORT N1,N2,.. [label]"""
import json, sys, time, threading, urllib.request, statistics as st
PORT = int(sys.argv[1]); NS = [int(x) for x in sys.argv[2].split(",")]; LABEL = sys.argv[3] if len(sys.argv) > 3 else ""
import os
QPORT = int(os.environ.get("QWEN_PORT", "8899")); MPORT = int(os.environ.get("MINI_PORT", "8898"))
KEY = os.environ.get("MINI_KEY") or __import__("json").load(open(os.path.expanduser(os.environ.get("MINI_STATE", "~/twomodel-onespark/minicpm-state")) + "/api_tokens.yml"))["api_key"]
IS_MINI = PORT == MPORT
KEY = KEY if IS_MINI else None
MODEL = "MiniCPM-V-4.7-35B-A3B-EXL3-SAGE-3.74bpw" if IS_MINI else "Qwen3.8-Flash-Next-EXL3"
TOPICS = ["rivers", "compilers", "volcanoes", "bridges", "satellites", "glaciers", "printing presses", "railways",
          "lighthouses", "deserts", "coral reefs", "telescopes", "windmills", "canals", "forests", "harbors"]
def one(i, out):
    body = {"model": MODEL, "messages": [{"role": "user", "content": f"Write a long flowing essay about {TOPICS[i % 16]} (variant {i}). No lists."}],
            "max_tokens": 256, "temperature": 0, "stream": True, "stream_options": {"include_usage": True}}
    if IS_MINI: body["chat_template_kwargs"] = {"enable_thinking": False}
    else: body["enable_thinking"] = False
    h = {"Content-Type": "application/json"}
    if KEY: h["Authorization"] = "Bearer " + KEY
    t0 = time.time(); first = None; last = None; u = {}
    r = urllib.request.urlopen(urllib.request.Request(f"http://127.0.0.1:{PORT}/v1/chat/completions", json.dumps(body).encode(), h), timeout=1800)
    for line in r:
        line = line.strip()
        if not line.startswith(b"data:") or line[5:].strip() == b"[DONE]": continue
        ev = json.loads(line[5:])
        if ev.get("usage"): u = ev["usage"]
        for ch in ev.get("choices", []):
            if (ch.get("delta") or {}).get("content"):
                last = time.time(); first = first or last
    out.append({"first": first, "last": last, "t0": t0, "ct": u.get("completion_tokens", 0), "tps": u.get("completion_tokens_per_sec")})
for n in NS:
    out = []; ths = [threading.Thread(target=one, args=(i, out)) for i in range(n)]
    [t.start() for t in ths]; [t.join() for t in ths]
    lo = max(o["first"] for o in out); hi = min(o["last"] for o in out)   # window where all n are decoding
    toks = sum(o["ct"] for o in out); span = max(o["last"] for o in out) - min(o["first"] for o in out)
    print(json.dumps({"label": LABEL, "n": n, "per_req_tps_median": round(st.median(o["tps"] for o in out), 2),
                      "aggregate_tps": round(toks / span, 1), "all_decoding_window_s": round(hi - lo, 1),
                      "tokens": toks}), flush=True)
    time.sleep(2)
