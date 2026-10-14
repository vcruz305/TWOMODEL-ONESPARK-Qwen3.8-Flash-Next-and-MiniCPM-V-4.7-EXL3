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
                self.assertNotIn("/home/cruzspark", t, f); self.assertNotIn("sage-campaigns", t, f)

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
    def test_key_not_inline(self):
        self.assertNotIn("api_key", (ROOT / "hermes/config.yaml").read_text())

class Results(unittest.TestCase):
    def test_readme_numbers_come_from_results(self):
        r = json.loads((ROOT / "results/measured-2026-10-13.json").read_text())
        t = (ROOT / "README.md").read_text()
        self.assertEqual(len(r["hermes_fanout"]), 4); self.assertTrue(all(x["correct"].split("/")[0] == x["correct"].split("/")[1] for x in r["hermes_fanout"]))
        for v in ("16/16", "206 s", "1,442", "25.8", "22.4 GB", "94.0"): self.assertIn(v, t)
        self.assertEqual(r["hermes_routing_check"]["cross_routed"], 0)

if __name__ == "__main__": unittest.main()
