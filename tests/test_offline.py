"""Offline checks: no GPU, servers or downloads needed."""
import json, os, re, subprocess, unittest
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]

def env_defaults():
    out = subprocess.run(["bash", "-c", f"source {ROOT/'bin/env.sh'}; echo $MINI_MAX_BATCH $QWEN_NGRAM_RAM $MINI_CACHE_SIZE $MINI_MAX_SEQ $QWEN_PORT $MINI_PORT"],
                         capture_output=True, text=True, env={k: v for k, v in os.environ.items() if not k.startswith(("MINI_", "QWEN_"))})
    return out.stdout.split()

class Shell(unittest.TestCase):
    def test_scripts_parse(self):
        for f in list((ROOT / "bin").glob("*.sh")) + list((ROOT / "tests").glob("*.sh")) + list((ROOT / "hermes").glob("*.sh")):
            self.assertEqual(subprocess.run(["bash", "-n", str(f)]).returncode, 0, f)
    def test_no_runtime_pins(self):
        for f in (ROOT / "bin").glob("*.sh"):
            t = f.read_text()
            self.assertNotRegex(t, r"(EXL3_REF|TABBY_REF)=[\"']?\$\{?[A-Z_]*:?-?[0-9a-f]{7,40}", f)
        self.assertIn("unset EXL3_REF TABBY_REF", (ROOT / "bin/setup.sh").read_text())
    def test_up_backgrounds_in_current_shell(self):
        # A "( ... & echo $! > pid )" subshell waits for the background server and up.sh never returns.
        t = (ROOT / "bin/up.sh").read_text()
        self.assertNotRegex(t, r"\(\s*cd [^)]*&\s*echo \$!", "server must be backgrounded in up.sh's own shell")
        self.assertEqual(t.count("setsid nohup"), 3)
    def test_mini_key_safe_under_set_e(self):
        # bin/up.sh polls mini_key under "set -e" before MiniCPM has written its key file.
        r = subprocess.run(["bash", "-c", f'set -euo pipefail; source {ROOT/"bin/env.sh"}; MINI_STATE=/nonexistent; K="$(mini_key)"; echo "reached[$K]"'],
                           capture_output=True, text=True)
        self.assertEqual((r.returncode, r.stdout.strip()), (0, "reached[]"))
    def test_run_all_preflight_and_exports(self):
        t = (ROOT / "tests/run_all.sh").read_text()
        self.assertRegex(t, r"export [^\n]*MINI_STATE"); self.assertIn("servers not ready", t); self.assertIn("exit $rc", t)
    def test_defaults(self):
        batch, ngram, cache, seq, qp, mp = env_defaults()
        self.assertEqual((ngram, qp, mp), ("false", "8899", "8898"))
        self.assertEqual(int(cache) % 256, 0); self.assertGreaterEqual(int(cache), int(seq))
        self.assertLessEqual(int(batch), 32)
    def test_no_secrets_or_private_paths(self):
        for f in ROOT.rglob("*"):
            if f.is_file() and f.name != "test_offline.py" and ".git" not in f.parts and f.suffix in (".sh", ".py", ".md", ".yaml", ".json"):
                t = f.read_text(errors="ignore")
                self.assertNotRegex(t, r"\b[0-9a-f]{64}\b(?!.*commit)" if f.suffix != ".json" else r"api_key\"\s*:\s*\"[0-9a-f]{32,}", f)
                for bad in ("/home/cruzspark", "sage-campaigns", "192.168.", "spark-gb10", "spark-724a", "W:/", "REXL3"):
                    self.assertNotIn(bad, t, f"{f}: {bad}")

class Lifecycle(unittest.TestCase):
    """Run the real bin/up.sh, status.sh, run_all.sh preflight and down.sh against stub servers that take a
    few seconds to start (key file appears late, port refuses connections at first), like the real ones."""
    def test_up_status_down_with_slow_servers(self):
        import socket, tempfile
        if subprocess.run(["bash", "-c", "command -v curl"], capture_output=True).returncode:
            self.skipTest("curl not installed")
        def free_port():
            s = socket.socket(); s.bind(("127.0.0.1", 0)); p = s.getsockname()[1]; s.close(); return p
        with tempfile.TemporaryDirectory() as h:
            h = Path(h); qp, mp = free_port(), free_port()
            for name, port, key in (("qwen", qp, ""), ("minicpm", mp, f"{h}/minicpm-state/api_tokens.yml")):
                d = h / f"{name}-recipe/exllamav3-tabby"; d.mkdir(parents=True)
                (d / "serve.sh").write_text(f"exec python3 {ROOT/'tests/stub_server.py'} {port} 4 {key}\n")
                m = h / f"{name}-model"; m.mkdir(); (m / "config.json").write_text("{}")
            env = {**os.environ, "TWOMODEL_HOME": str(h), "QWEN_PORT": str(qp), "MINI_PORT": str(mp),
                   "QWEN_MODEL_DIR": str(h / "qwen-model"), "MINI_MODEL_DIR": str(h / "minicpm-model"),
                   "MEM_FLOOR_MIB": "1", "PATH": os.environ["PATH"]}
            run = lambda *a: subprocess.run(["bash", *a], capture_output=True, text=True, env=env, timeout=120)
            try:
                up = run(str(ROOT / "bin/up.sh"))
                self.assertEqual(up.returncode, 0, up.stderr[-1500:])
                self.assertIn("both servers ready", up.stderr)
                st = run(str(ROOT / "bin/status.sh"))
                self.assertIn(f":{qp}  http=200", st.stdout); self.assertIn(f":{mp}  http=200", st.stdout)
                pre = run("-c", f"source {ROOT/'bin/env.sh'}; MINI_KEY=$(mini_key); "
                                f"[[ $(http_code http://127.0.0.1:{mp}/v1/models \"Authorization: Bearer $MINI_KEY\") == 200 ]] && echo PREFLIGHT_OK")
                self.assertIn("PREFLIGHT_OK", pre.stdout)
            finally:
                run(str(ROOT / "bin/down.sh"))
            st = run(str(ROOT / "bin/status.sh"))
            self.assertIn(f":{qp}  http=000", st.stdout); self.assertIn(f":{mp}  http=000", st.stdout)
            # run_all.sh must refuse to run against stopped servers instead of reporting test failures.
            ra = run(str(ROOT / "tests/run_all.sh"), "tools")
            self.assertNotEqual(ra.returncode, 0); self.assertRegex(ra.stderr, "no MiniCPM key|servers not ready")

class Robustness(unittest.TestCase):
    """Failure paths found in review: no orphaned servers, floor checked before Qwen, PID reuse."""
    def _setup(self, h, qwen_cmd=None, mini_delay=2):
        import socket
        def free_port():
            s = socket.socket(); s.bind(("127.0.0.1", 0)); p = s.getsockname()[1]; s.close(); return p
        qp, mp = free_port(), free_port()
        for name, port, key, cmd in (("qwen", qp, "", qwen_cmd),
                                     ("minicpm", mp, f"{h}/minicpm-state/api_tokens.yml", None)):
            d = h / f"{name}-recipe/exllamav3-tabby"; d.mkdir(parents=True)
            (d / "serve.sh").write_text(cmd or f"exec python3 {ROOT/'tests/stub_server.py'} {port} {mini_delay} {key}\n")
            m = h / f"{name}-model"; m.mkdir(); (m / "config.json").write_text("{}")
        env = {**os.environ, "TWOMODEL_HOME": str(h), "QWEN_PORT": str(qp), "MINI_PORT": str(mp),
               "QWEN_MODEL_DIR": str(h / "qwen-model"), "MINI_MODEL_DIR": str(h / "minicpm-model"),
               "MEM_FLOOR_MIB": "1", "QWEN_NEED_MIB": "1"}
        return env, qp, mp
    def _run(self, env, *a):
        return subprocess.run(["bash", *a], capture_output=True, text=True, env=env, timeout=120)
    def _listening(self, port):
        import socket
        with socket.socket() as s:
            return s.connect_ex(("127.0.0.1", port)) == 0
    def test_failed_qwen_start_stops_minicpm(self):
        import tempfile
        with tempfile.TemporaryDirectory() as h:
            h = Path(h); env, qp, mp = self._setup(h, qwen_cmd="sleep 1; echo boom >&2; exit 3\n")
            up = self._run(env, str(ROOT / "bin/up.sh"))
            self.assertNotEqual(up.returncode, 0); self.assertIn("stopping servers started by this run", up.stderr)
            self.assertFalse(self._listening(mp), "MiniCPM left running after Qwen failed")
    def test_floor_checked_before_qwen_load(self):
        import tempfile
        with tempfile.TemporaryDirectory() as h:
            h = Path(h); env, qp, mp = self._setup(h)
            env["QWEN_NEED_MIB"] = str(10**9)     # pretend Qwen needs more than any machine has
            up = self._run(env, str(ROOT / "bin/up.sh"))
            self.assertNotEqual(up.returncode, 0); self.assertIn("Qwen needs", up.stderr)
            self.assertFalse((h / "logs/qwen.log").exists(), "Qwen was started despite the floor check")
            self.assertFalse(self._listening(mp))
    def test_down_ignores_reused_pid(self):
        import tempfile
        with tempfile.TemporaryDirectory() as h:
            h = Path(h); env, *_ = self._setup(h); (h / "logs").mkdir()
            victim = subprocess.Popen(["sleep", "60"])
            ours = subprocess.Popen(["sleep", "60"])
            try:
                # A bare PID (no start-time proof) and a wrong start time both mean "not ours".
                (h / "logs/qwen.pid").write_text(f"{victim.pid}\n")
                start = open(f"/proc/{ours.pid}/stat").read().split()[21]
                (h / "logs/minicpm.pid").write_text(f"{ours.pid} {start}\n")
                self._run(env, str(ROOT / "bin/down.sh"))
                self.assertIsNone(victim.poll(), "down.sh signalled a process it did not start")
                ours.wait(timeout=10)   # the correctly recorded process is still stopped
            finally:
                victim.kill(); ours.kill()

class Hermes(unittest.TestCase):
    def cfg(self):
        import yaml
        return yaml.safe_load((ROOT / "hermes/config.yaml").read_text())
    def test_delegation_routes_to_minicpm(self):
        c = self.cfg()
        self.assertEqual(c["model"]["provider"], "qwen-spark")
        self.assertEqual(c["delegation"]["provider"], "minicpm-spark")
        self.assertIn("minicpm-spark", c["providers"]); self.assertIn("qwen-spark", c["providers"])
        self.assertEqual(c["delegation"]["oneshot_max_children"], 0)
    def test_children_match_server_batch(self):
        self.assertEqual(self.cfg()["delegation"]["max_concurrent_children"], int(env_defaults()[0]))
    def test_subagent_context_fits_pool(self):
        c = self.cfg(); batch, _, cache, *_ = env_defaults()
        ctx = c["providers"]["minicpm-spark"]["models"]["MiniCPM-V-4.7-35B-A3B-EXL3-SAGE-3.74bpw"]["context_length"]
        self.assertLessEqual(ctx * int(batch), int(cache))
    def test_worktree_isolation_on(self):
        self.assertIs(self.cfg()["delegation"]["worktree_isolation"], True)
    def test_titles_avoid_qwen_template(self):
        self.assertEqual(self.cfg()["auxiliary"]["title_generation"]["provider"], "minicpm-spark")
    def test_fanout_fails_on_wrong_answer(self):
        t = (ROOT / "tests/hermes_fanout.sh").read_text()
        self.assertIn("sys.exit(0 if ok else 1)", t); self.assertIn("exit $bad", t)
    def test_key_not_inline(self):
        self.assertNotIn("api_key", (ROOT / "hermes/config.yaml").read_text())

class Results(unittest.TestCase):
    def test_readme_numbers_come_from_results(self):
        r = json.loads((ROOT / "results/measured-2026-10-13.json").read_text())
        t = (ROOT / "README.md").read_text()
        ok = sum(int(x["correct"].split("/")[0]) for x in r["hermes_fanout"]); n = sum(int(x["correct"].split("/")[1]) for x in r["hermes_fanout"])
        self.assertEqual(f"{ok}/{n}", r["hermes_fanout_total_correct"]); self.assertIn(f"{ok}/{n} subagents", t)
        for v in ("16/16", "206 s", "1,442", "25.8", "22.4 GB", "94.0"): self.assertIn(v, t)
        self.assertEqual(r["hermes_routing_check"]["cross_routed"], 0)

if __name__ == "__main__": unittest.main()
