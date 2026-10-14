# TWOMODELS-ONESPARK: Qwen3.8-Flash-Next + MiniCPM-V 4.7 on one DGX Spark

Run **Qwen3.8-Flash-Next EXL3 3.05 bpw** as a main agent and **MiniCPM-V 4.7 35B-A3B SAGE EXL3 3.74 bpw**
as its subagents on **one** DGX Spark, both at full **262,144-token** context, through
[ExLlamaV3](https://github.com/vcruz305/exllamav3) and [TabbyAPI](https://github.com/vcruz305/tabbyAPI).
Includes a tested [Hermes Agent](https://github.com/NousResearch/hermes-agent) configuration where every
`delegate_task` subagent runs on MiniCPM.

| One DGX Spark, both models loaded | Qwen (main) | MiniCPM (subagents) |
|---|---:|---:|
| Memory | 55.7 GB | 18.0–26.0 GB |
| Free memory left (worst case measured) | 22.4 GB | |
| Decode, other model idle (400 tok) | 88.6 code / 55.9 prose tok/s | 69.8 tok/s |
| Decode, both generating | 35.3 / 28.7 tok/s | 40.0 / 38.1 tok/s |
| Cold 128K prompt, other model loaded | 206 s to first token, 90 tok/s decode | 90 s, 55 tok/s |
| Needle retrieval at 128K | 2/2 | 2/2 |
| Tool calling (14 checks each) | 7/7 · 7/7 stream | 7/7 · 7/7 stream |
| Hermes fan-out, every subagent's own answer correct (shipped setup) | — | 60/60 subagents |

## Models

| Role | Quantized checkpoint (what runs) | Base model |
|---|---|---|
| Main agent | [turboderp/Qwen3.8-Flash-Next-exl3](https://huggingface.co/turboderp/Qwen3.8-Flash-Next-exl3/tree/3.05bpw_h5_ng5), branch `3.05bpw_h5_ng5` (EXL3 3.05 bpw, 5-bit head, 5-bit n-gram table) | [Qwen/Qwen3.8-Flash-Next](https://huggingface.co/Qwen/Qwen3.8-Flash-Next) |
| Subagents | [vcruz305/MiniCPM-V-4.7-35B-A3B-EXL3-SAGE-3.74bpw](https://huggingface.co/vcruz305/MiniCPM-V-4.7-35B-A3B-EXL3-SAGE-3.74bpw) (SAGE EXL3 3.74 bpw) | [openbmb/MiniCPM-V-4.7-35B-A3B](https://huggingface.co/openbmb/MiniCPM-V-4.7-35B-A3B) |

`bin/download.sh` fetches these two checkpoints, plus the dSparK drafter that the MiniCPM recipe downloads alongside its checkpoint (downloads resume if interrupted).

This repo contains only orchestration, configuration and tests. It reuses the two single-model recipes,
which both track the **latest** `vcruz305/exllamav3` master and `vcruz305/tabbyAPI` main: nothing is pinned.

- [Qwen3.8-Flash-Next-EXL3-DGX-Spark-recipe](https://github.com/vcruz305/Qwen3.8-Flash-Next-EXL3-DGX-Spark-recipe)
- [MiniCPM-V-4.7-35B-A3B-EXL3-DGX-Spark-recipe](https://github.com/vcruz305/MiniCPM-V-4.7-35B-A3B-EXL3-DGX-Spark-recipe)

## Quick start

On the Spark, with CUDA 13 (`/usr/local/cuda-13.0`) and a CUDA PyTorch environment:

```bash
git clone https://github.com/vcruz305/TWOMODELS-ONESPARK-Qwen3.8-Flash-Next-and-MiniCPM-V-4.7-EXL3.git
cd TWOMODELS-ONESPARK-Qwen3.8-Flash-Next-and-MiniCPM-V-4.7-EXL3

BASE_PYTHON=/path/to/cuda-venv/bin/python bash bin/setup.sh   # both runtimes, latest fork commits (~8 min)
bash bin/download.sh                                           # ~81 GB Qwen + ~18 GB MiniCPM
bash bin/up.sh                                                 # MiniCPM :8898, then Qwen :8899
bash bin/status.sh
bash bin/down.sh
```

Point `QWEN_MODEL_DIR` / `MINI_MODEL_DIR` at packs you already have to skip the download. `bin/setup.sh`
can be re-run any time to pick up new fork commits; it never touches running servers.

## How the two models share the Spark

| | Qwen3.8-Flash-Next (main agent) | MiniCPM-V 4.7 (subagents) |
|---|---|---|
| Port | 8899 (localhost, no key) | 8898 (localhost, API key) |
| Context per request | 262,144 | 262,144 max; Hermes caps subagents at 131,072 |
| KV cache | Q8, 262,144 pool, 1 job | Q4, 1,048,576 shared pool, 8 concurrent jobs |
| Speculative decoding | MTP (5 draft tokens, dynamic) | off (dSparK only helps short prompts) |
| N-gram embedding table (31 GB) | streamed from NVMe | — |

- **Stream Qwen's n-gram table from NVMe** (`QWEN_NGRAM_RAM=false`, the default here). Loading it into RAM
  costs ~30 GB that the two-model setup needs. Short requests read only 27–36 MB from disk; a cold 128K
  prompt reads ~3 GB, which is why its first token takes ~3.5 minutes. Later turns reuse the prompt cache.
- **Start MiniCPM first.** Its KV pool is reserved at load, so memory use is close to its maximum from the
  start. After MiniCPM is up, `bin/up.sh` only loads Qwen if ~56 GB plus the `MEM_FLOOR_MIB` floor
  (6 GiB) is still free, and checks the floor again once both are loaded. If any step fails, it stops
  the servers it started.
- **Low-memory guard.** `bin/up.sh` starts `bin/guard.sh`, which stops both servers cleanly if free memory
  drops below the floor. It never tripped in testing (minimum observed 22.4 GB free).

Overrides (all in [bin/env.sh](bin/env.sh)): `QWEN_PORT`, `MINI_PORT`, `MINI_MAX_BATCH`, `MINI_CACHE_SIZE`,
`MINI_MAX_SEQ`, `QWEN_PROFILE`, `QWEN_NGRAM_RAM`, `QWEN_MODEL_DIR`, `MINI_MODEL_DIR`, `MEM_FLOOR_MIB`,
`TWOMODEL_HOME`, `LOG_DIR`, `BASE_PYTHON`, `CUDA_HOME`.

## Hermes: Qwen main agent, MiniCPM subagents

[hermes/config.yaml](hermes/config.yaml) defines both servers as
[named custom providers](https://hermes-agent.nousresearch.com/docs/integrations/providers) and points
[delegation](https://hermes-agent.nousresearch.com/docs/user-guide/features/delegation) at MiniCPM:

```yaml
model:     {provider: qwen-spark, default: Qwen3.8-Flash-Next-EXL3, context_length: 262144}
providers:
  qwen-spark:    {api: http://127.0.0.1:8899/v1, transport: chat_completions}
  minicpm-spark: {api: http://127.0.0.1:8898/v1, key_env: MINICPM_API_KEY, transport: chat_completions}
delegation:
  provider: minicpm-spark
  model: MiniCPM-V-4.7-35B-A3B-EXL3-SAGE-3.74bpw
  max_concurrent_children: 8        # = MINI_MAX_BATCH; larger delegate_task batches get a tool error
  oneshot_max_children: 0           # default 2 would cap one-shot runs at two subagents
  compression_threshold_tokens: 65536
```

Install it into a dedicated Hermes profile (your main `~/.hermes` is not touched) and run:

```bash
bash bin/up.sh
bash hermes/patch_hermes.sh               # upstream fix NousResearch/hermes-agent#135354 (see below)
bash hermes/install.sh                    # -> ~/.hermes-twomodel: config, MINICPM_API_KEY, delegation guidance
HERMES_HOME=~/.hermes-twomodel hermes
```

`hermes/install.sh` also adds [hermes/delegation-guidance.md](hermes/delegation-guidance.md) to the
profile's `SOUL.md` (between markers, so re-running replaces it and your own text is kept). It tells
Qwen to give subagents exact paths, to have them compute anything exact with the terminal or
`execute_code` tool rather than in their reply, and to check their results. The config also turns on
`delegation.worktree_isolation`, so inside a git repo each subagent works in its own worktree.

Concurrency is dynamic up to a cap. One `delegate_task` call may carry up to `max_concurrent_children`
tasks; Hermes rejects a larger call with a tool error telling the agent to split it, and the agent then
delegates in batches. MiniCPM batches whatever is active up to `MINI_MAX_BATCH`.

**Verified routing.** In a 16-subagent fan-out, Hermes's own session database recorded 44 subagent
sessions, all on MiniCPM, and 5 parent sessions, all on Qwen, with nothing cross-routed. The two
servers' request logs agreed.

## Subagent concurrency

### Subagent accuracy: what was wrong, and the fix

Each fan-out has Qwen delegate N file-summing tasks to MiniCPM. The test reads **every subagent's own
final answer** from Hermes's session database and checks it against the true sum. An earlier version of
this table only checked Qwen's summary, which hid wrong subagents whenever Qwen recomputed the files itself.

Reading every failed subagent's session turned up three causes, none of them MiniCPM's ability to do the task:

1. **Hermes output-schema retry starts from an empty conversation.** When Qwen attaches an
   `output_schema` and a subagent first answers in prose, Hermes runs one correction turn, but without
   the subagent's task, tool results or answer ([NousResearch/hermes-agent#135354](https://github.com/NousResearch/hermes-agent/pull/135354),
   open). Subagents that had already computed the right sum with `awk` then guessed: `0`, a sibling's
   `sum.json`, the sum of every file. `hermes/patch_hermes.sh` applies that PR until it is merged.
2. **Mental arithmetic.** About a quarter of subagents summed 61 numbers in their reply instead of
   running a command, and some of those were off by hundreds. The delegation guidance tells Qwen to
   have subagents compute exact values with a tool.
3. **No sampler fallbacks on MiniCPM.** Hermes sends no sampler values, and TabbyAPI then samples from the
   full ~248K vocabulary (top_k 0, top_p 1.0). The MiniCPM recipe now falls back to the model's own
   `generation_config.json` values (temperature 1.0, top_k 20, top_p 0.95), as the Qwen recipe already did.

Controlled runs, 14 Oct, one Spark, same servers and prompts. "Forced schema" tells Qwen to attach an
`output_schema` to every task, which exercises cause 1 on purpose:

| Setup | Fan-outs | Subagents correct |
|---|---|---:|
| Sampler fix only, stock Hermes | 3 × 8 | 18/24 |
| Hermes fix only (no sampler fix, no guidance) | 3 × 8 | 24/24 |
| Sampler + Hermes fix, no guidance | 8, 8, 8, 16, 4 | 40/44 (4 mental-arithmetic misses) |
| Forced schema, stock Hermes, sampler fix | 2 × 8 | 9/16 |
| Forced schema, Hermes fix, sampler fix | 8, 8, 8, 16 | 40/40 |
| **Shipped setup** (all three fixes), plain | 8, 8, 8, 16, 4 | **44/44** |
| **Shipped setup**, forced schema | 2 × 8 | **16/16** |

In the shipped-setup runs every subagent computed its sum with a tool, and the true sum appears in its
own terminal output (60/60). All subagents ran on MiniCPM and every parent turn on Qwen. The fan-out
test fails on any wrong subagent answer, not just a wrong final summary.

Subagents are still a smaller model: give them precise tasks and check what matters.

**Agent-sized prompts** (7.2K-token context with tool schemas, 300 tokens out) while Qwen keeps decoding:

| Concurrent subagents | Each, tok/s | Combined, tok/s | First token (p50) | Qwen meanwhile |
|---:|---:|---:|---:|---:|
| 1 | 35.0 | 18.2 | 7.9 s | 29.8 tok/s |
| 2 | 27.4 | 21.9 | 16.5 s | 28.0 tok/s |
| 4 | 18.3 | 24.6 | 33.0 s | 27.7 tok/s |
| 8 | 9.2 | 25.8 | 63.9 s | 26.2 tok/s |
| 12 | 2.5 | 18.6 | 68.4 s | 31.5 tok/s |

Short prompts without tools batch far better (69.7 / 166.8 / 217.3 tok/s combined at 1 / 4 / 8 requests,
Qwen idle). With tool-call grammar enabled and large prompts, combined throughput levels off at about
22–26 tok/s from 2 to 8 subagents, so **8 is the recommended cap**: more only queues work inside the
server instead of inside Hermes. During the slow sweep each server ran one CPU thread at 100% with the
rest of the machine idle; that single-threaded step is a likely bottleneck but has not been isolated yet.

## Long prompts side by side

| Run | Prompt | First token | Prefill | Decode | Needles |
|---|---:|---:|---:|---:|---:|
| Qwen, n-gram cache cleared, MiniCPM loaded | 128,578 | 206 s | 625 tok/s | 90.1 tok/s | 2/2 |
| MiniCPM, Qwen loaded | 128,578 | 90 s | 1,442 tok/s | 54.6 tok/s | 2/2 |
| Both at once: MiniCPM | 63,951 | 84 s | 769 tok/s | 26.4 tok/s | 1/1 |
| Both at once: Qwen | 63,951 | 148 s | 433 tok/s | 74.3 tok/s | 1/1 |

The Qwen decode in the concurrent row mostly ran after MiniCPM had finished its prefill, so it is not a
both-busy number; MiniCPM's 26.4 tok/s is.

## Tests

With both servers up:

```bash
bash tests/run_all.sh                      # tools decode concurrency hermes longctx
bash tests/run_all.sh tools hermes         # a subset
```

| Test | What it checks |
|---|---|
| `tools` | Required single call, auto zero calls, parallel calls (stream + non-stream), tool-result round trip, on both servers |
| `decode` | Batched MiniCPM decode at 1/4/8 requests; Qwen single stream |
| `concurrency` | 1–8 agent-sized MiniCPM requests while Qwen decodes; per-request and combined tok/s, TTFT, free memory |
| `hermes` | Real Hermes one-shot runs: Qwen fans 4 and 8 tasks out to MiniCPM, plus an 8-task run with a forced `output_schema`; every subagent's own answer and Qwen's summary are checked against ground truth, and requests are counted per server |
| `longctx` | Cold 128K on each model with the other loaded, then 64K on both at once, with planted needles (generated from the local CPython stdlib) |

The `hermes` test needs Hermes Agent installed (`hermes` on PATH), `hermes/patch_hermes.sh` and
`hermes/install.sh` run first. Offline checks (no GPU): `python3 -m unittest discover -s tests -p "test_*.py"`.

## How these numbers were measured

One DGX Spark, 13–14 Oct 2026, TabbyAPI over HTTP, server-reported timings, greedy decoding, thinking off.
MiniCPM ran ExLlamaV3 master `475461e9`. The side-by-side Qwen runs used the Qwen recipe's previous pinned
engine `24f0dece3`; on latest master `475461e9` Qwen decoded 94.0 / 56.4 / 93.8 tok/s (code / prose /
math) versus 89.0 / 55.5 / 89.3 on the pin, passed 7/7 tool checks, and passed the Qwen recipe's frozen
numerical gate with 0 core failures (4 investigate-only KL items). Hermes Agent `d97007c3` (v0.22.0).
Throughput and long-context numbers were measured before the MiniCPM sampler fallbacks were added (the
fallbacks change which tokens are sampled, not the work per token). Subagent accuracy numbers are from
the 14 Oct controlled runs above. Raw values: [results/measured-2026-10-13.json](results/measured-2026-10-13.json).

**Not yet measured:** a 24-hour or week-long run; behaviour when MiniCPM's shared KV pool fills;
concurrency above 12 in the synthetic sweep (Hermes fan-out was tested to 16).

## Credits

Qwen team: Qwen3.8-Flash-Next. OpenBMB: MiniCPM-V 4.7. turboderp: ExLlamaV3 and the Qwen EXL3 pack.
The Royal Lab: TabbyAPI. Nous Research: Hermes Agent. [r0b0tlab](https://github.com/r0b0tlab): MiniCPM-V 4.7
dSparK improvements in the fork. Victor Cruz: SAGE EXL3 MiniCPM pack, recipes and measurements.

Recipe code: MIT. Models and runtimes keep their own licenses.
