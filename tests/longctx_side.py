#!/usr/bin/env python3
"""Long cold prompts side by side. Uses the 262K needle fixture (CPython stdlib + license texts, 4 codes).
A) Qwen ~128K cold, n-gram table evicted first, MiniCPM loaded idle.
B) MiniCPM ~128K cold while Qwen loaded idle.
C) both ~64K cold prompts at the same time.
Reports prefill tok/s, TTFT, decode, needle hits, NVMe read volume during prefill."""
import json, os, re, sys, time, threading, urllib.request
import glob, random, sysconfig
import os
QPORT = int(os.environ.get("QWEN_PORT", "8899")); MPORT = int(os.environ.get("MINI_PORT", "8898"))
KEY = os.environ.get("MINI_KEY") or __import__("json").load(open(os.path.expanduser(os.environ.get("MINI_STATE", "~/twomodel-onespark/minicpm-state")) + "/api_tokens.yml"))["api_key"]
NG = os.path.join(os.path.expanduser(os.environ.get("QWEN_MODEL_DIR", "~/models/Qwen3.8-Flash-Next-EXL3")), "ngram_embedding.safetensors")
def build_doc(target_chars=1_000_000, seed=7):
    """Deterministic long document: CPython stdlib sources with four vault codes at 10/35/60/90% depth."""
    files = sorted(glob.glob(os.path.join(sysconfig.get_paths()["stdlib"], "*.py")))
    parts, n = [], 0
    for f in files:
        t = open(f, encoding="utf8", errors="ignore").read(); parts.append(f"\n# ===== FILE {os.path.basename(f)} =====\n" + t); n += len(t)
        if n > target_chars: break
    doc = "".join(parts)[:target_chars]
    rnd = random.Random(seed); codes = []
    for frac, name in ((0.10, "ALPHA"), (0.35, "BRAVO"), (0.60, "CHARLIE"), (0.90, "DELTA")):
        code = f"{rnd.randint(1000,9999)}-{rnd.choice(['KESTREL','MARIGOLD','OBSIDIAN','TAMARIND','JUNIPER'])}"
        i = doc.find("\n", int(len(doc) * frac)); doc = doc[:i] + f"\n# ARCHIVE NOTE: VAULT {name} access code is {code}.\n" + doc[i:]
        codes.append(code)
    return doc, codes
head, codes = build_doc()
def cut(frac):
    # keep needles: take the first `frac` of the document, then re-append the instruction
    body = head[: int(len(head) * frac)]
    present = [c for c in codes if c in body]
    q = ("\n\n===== END OF DOCUMENT =====\n\nList every VAULT code that appears in the document above, one per line "
         "in the form 'VAULT: CODE'. Output nothing else.")
    return body + q, present
def nvme(): return int(open("/sys/block/nvme0n1/stat").read().split()[2])
def evict():
    if not os.path.exists(NG): return
    fd = os.open(NG, os.O_RDONLY); os.posix_fadvise(fd, 0, 0, os.POSIX_FADV_DONTNEED); os.close(fd)
def req(who, prompt, present, tag, out):
    port, model = (QPORT, "Qwen3.8-Flash-Next-EXL3") if who == "qwen" else (MPORT, "MiniCPM-V-4.7-35B-A3B-EXL3-SAGE-3.74bpw")
    body = {"model": model, "messages": [{"role": "user", "content": prompt}], "max_tokens": 120, "temperature": 0,
            "stream": True, "stream_options": {"include_usage": True}}
    if who == "qwen": body["enable_thinking"] = False
    else: body["chat_template_kwargs"] = {"enable_thinking": False}
    h = {"Content-Type": "application/json"}
    if who == "mini": h["Authorization"] = "Bearer " + KEY
    s0 = nvme(); t0 = time.time(); first = None; txt = ""; u = {}
    r = urllib.request.urlopen(urllib.request.Request(f"http://127.0.0.1:{port}/v1/chat/completions", json.dumps(body).encode(), h), timeout=3600)
    for line in r:
        line = line.strip()
        if not line.startswith(b"data:") or line[5:].strip() == b"[DONE]": continue
        ev = json.loads(line[5:])
        if ev.get("usage"): u = ev["usage"]
        for ch in ev.get("choices", []):
            d = (ch.get("delta") or {}).get("content") or ""
            if d and first is None: first = time.time()
            txt += d
    row = {"tag": tag, "who": who, "prompt_tokens": u.get("prompt_tokens"), "cached": (u.get("prompt_tokens_details") or {}).get("cached_tokens"),
           "prefill_tps": u.get("prompt_tokens_per_sec"), "ttft_s": round(first - t0, 1) if first else None,
           "decode_tps": u.get("completion_tokens_per_sec"), "needles_present": len(present),
           "needles_found": sum(c in txt for c in present), "nvme_read_mb": round((nvme() - s0) * 512 / 1e6, 1)}
    out.append(row); print(json.dumps(row), flush=True)
rows = []
p128, n128 = cut(0.49); p64, n64 = cut(0.245)
evict(); req("qwen", p128, n128, "A_qwen_128k_cold_ngram_evicted", rows)
req("mini", p128, n128, "B_mini_128k_cold", rows)
evict()
# fresh prompts so nothing is prefix-cached: prepend a unique line
a = "Session A.\n" + p64; b = "Session B.\n" + p64
ts = [threading.Thread(target=req, args=("qwen", a, n64, "C_both_64k_concurrent", rows)),
      threading.Thread(target=req, args=("mini", b, n64, "C_both_64k_concurrent", rows))]
[t.start() for t in ts]; [t.join() for t in ts]
json.dump(rows, open(sys.argv[1] if len(sys.argv) > 1 else "longctx.json", "w"), indent=1)
print("LONGCTX_DONE")
