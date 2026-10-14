# Agent instructions

Orchestration-only recipe: two TabbyAPI + ExLlamaV3 servers on one DGX Spark (Qwen3.8-Flash-Next main
agent :8899, MiniCPM-V 4.7 subagents :8898) plus a Hermes Agent profile that routes delegation to MiniCPM.

- **Never pin runtime versions.** Both sub-recipes track the latest `vcruz305/exllamav3` master and
  `vcruz305/tabbyAPI` main; `bin/setup.sh` unsets `EXL3_REF`/`TABBY_REF`. Record measured commits in
  `results/`, never as defaults.
- Start order is MiniCPM then Qwen; keep the low-memory guard. Do not load Qwen's n-gram table into RAM
  (`QWEN_NGRAM_RAM=true`) alongside MiniCPM without re-measuring headroom.
- Keep `delegation.max_concurrent_children` equal to `MINI_MAX_BATCH` (default 8).
- Subagent accuracy depends on three things together: MiniCPM sampler fallbacks (sub-recipe), the Hermes
  schema-retry fix (`hermes/patch_hermes.sh`, NousResearch/hermes-agent#135354) and the delegation guidance
  that `hermes/install.sh` puts in SOUL.md. Score fan-outs by each subagent's own answer, never only by the
  main agent's summary.
- Never write secrets into the repo. The MiniCPM key lives in the sub-recipe's `api_tokens.yml` and the
  Hermes profile's `.env` only.
- Do not kill processes you did not start; `bin/down.sh` only stops PIDs recorded by `bin/up.sh`.
- Never invent results. Numbers in README come from `results/measured-*.json`.

## Tests
python3 -m unittest discover -s tests -p "test_*.py" -v   # offline, no GPU
bash tests/run_all.sh                                        # live, both servers up
