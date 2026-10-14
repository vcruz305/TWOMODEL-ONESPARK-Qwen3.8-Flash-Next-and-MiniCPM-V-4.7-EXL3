#!/usr/bin/env python3
"""Tool-calling conformance for both servers (OpenAI chat.completions, non-stream + stream).
Cases: single required call, auto with zero calls, parallel calls, tool-result round trip."""
import json, sys, time, urllib.request
import os
QPORT = int(os.environ.get("QWEN_PORT", "8899")); MPORT = int(os.environ.get("MINI_PORT", "8898"))
KEY = os.environ.get("MINI_KEY") or __import__("json").load(open(os.path.join(os.path.expanduser(os.environ.get("MINI_STATE", "~/twomodel-onespark/minicpm-state")), "api_tokens.yml")))["api_key"]
EP = {"qwen": (f"http://127.0.0.1:{QPORT}/v1", None, "Qwen3.8-Flash-Next-EXL3"),
      "mini": (f"http://127.0.0.1:{MPORT}/v1", KEY, "MiniCPM-V-4.7-35B-A3B-EXL3-SAGE-3.74bpw")}
TOOLS = [
 {"type": "function", "function": {"name": "read_file", "description": "Read a text file",
   "parameters": {"type": "object", "properties": {"path": {"type": "string"}, "offset": {"type": "integer"}}, "required": ["path"]}}},
 {"type": "function", "function": {"name": "terminal", "description": "Run a shell command",
   "parameters": {"type": "object", "properties": {"command": {"type": "string"}, "timeout": {"type": "integer"}}, "required": ["command"]}}},
]
def call(who, messages, stream=False, **kw):
    base, key, model = EP[who]
    body = {"model": model, "messages": messages, "tools": TOOLS, "temperature": 0, "max_tokens": 600, "stream": stream, **kw}
    if who == "mini": body["chat_template_kwargs"] = {"enable_thinking": False}
    else: body["enable_thinking"] = False
    h = {"Content-Type": "application/json"}
    if key: h["Authorization"] = "Bearer " + key
    r = urllib.request.urlopen(urllib.request.Request(base + "/chat/completions", json.dumps(body).encode(), h), timeout=300)
    if not stream:
        d = json.load(r); m = d["choices"][0]["message"]
        return m.get("content"), m.get("tool_calls") or [], d["choices"][0]["finish_reason"]
    calls = {}; content = ""; finish = None
    for line in r:
        line = line.strip()
        if not line.startswith(b"data:") or line[5:].strip() == b"[DONE]": continue
        ev = json.loads(line[5:])
        for ch in ev.get("choices", []):
            dl = ch.get("delta") or {}
            content += dl.get("content") or ""
            for tc in dl.get("tool_calls") or []:
                c = calls.setdefault(tc.get("index", 0), {"id": None, "name": "", "arguments": ""})
                c["id"] = tc.get("id") or c["id"]
                f = tc.get("function") or {}
                c["name"] += f.get("name") or ""; c["arguments"] += f.get("arguments") or ""
            finish = ch.get("finish_reason") or finish
    return content, [{"id": c["id"], "function": {"name": c["name"], "arguments": c["arguments"]}} for c in calls.values()], finish
def check(name, cond, detail=""):
    print(("PASS " if cond else "FAIL ") + name + (" | " + detail if detail else ""), flush=True); return cond
results = {}
for who in sys.argv[1:] or ["qwen", "mini"]:
    ok = []
    for stream in (False, True):
        tag = f"{who}/{'stream' if stream else 'nonstream'}"
        c, tc, fin = call(who, [{"role": "user", "content": "Read the file /etc/hostname."}], stream, tool_choice="required")
        args = {}
        try: args = json.loads(tc[0]["function"]["arguments"]) if tc else {}
        except Exception: pass
        ok.append(check(f"{tag} required single call", len(tc) == 1 and tc[0]["function"]["name"] == "read_file" and args.get("path") == "/etc/hostname" and fin == "tool_calls", json.dumps(tc)[:160]))
        c, tc, fin = call(who, [{"role": "user", "content": "What is 2+2? Answer directly, no tools."}], stream)
        ok.append(check(f"{tag} auto zero calls", not tc and c and "4" in c and fin == "stop", repr(c)[:80]))
        c, tc, fin = call(who, [{"role": "user", "content": "In parallel: read /etc/hostname AND run the command `uptime`. Call both tools now."}], stream)
        names = sorted(t["function"]["name"] for t in tc)
        ok.append(check(f"{tag} parallel two calls", names == ["read_file", "terminal"], str(names)))
    # tool-result round trip
    c, tc, fin = call(who, [{"role": "user", "content": "Read the file /etc/hostname and tell me the hostname."}], False, tool_choice="required")
    msgs = [{"role": "user", "content": "Read the file /etc/hostname and tell me the hostname."},
            {"role": "assistant", "content": c or "", "tool_calls": [{"id": tc[0]["id"] or "call_0", "type": "function", "function": tc[0]["function"]}]} if tc else {"role": "assistant", "content": ""},
            {"role": "tool", "tool_call_id": (tc[0]["id"] if tc else "call_0") or "call_0", "content": "example-host-7f3a\n"}]
    c2, tc2, fin2 = call(who, msgs, False)
    ok.append(check(f"{who} tool-result round trip", bool(tc) and not tc2 and c2 and "example-host-7f3a" in c2, repr(c2)[:100]))
    results[who] = (sum(ok), len(ok))
print("SUMMARY", json.dumps(results))
