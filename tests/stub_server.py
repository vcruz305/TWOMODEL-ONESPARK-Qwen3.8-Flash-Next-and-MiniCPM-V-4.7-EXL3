"""Stand-in for a TabbyAPI server in offline lifecycle tests: waits, optionally writes a key file, then serves /v1/models."""
import http.server, json, os, sys, time
port, delay, keyfile = int(sys.argv[1]), float(sys.argv[2]), (sys.argv[3] if len(sys.argv) > 3 else "")
time.sleep(delay / 2)
if keyfile:
    os.makedirs(os.path.dirname(keyfile), exist_ok=True)
    json.dump({"api_key": "stub-key", "admin_key": "stub-admin"}, open(keyfile, "w"))
time.sleep(delay / 2)
class H(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        ok = self.path == "/v1/models" and (not keyfile or self.headers.get("Authorization") == "Bearer stub-key")
        self.send_response(200 if ok else 401); self.end_headers(); self.wfile.write(b'{"data":[]}')
    def log_message(self, *a): pass
http.server.ThreadingHTTPServer(("127.0.0.1", port), H).serve_forever()
