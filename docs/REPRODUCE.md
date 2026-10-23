# Reproducing the results

Every number in `results/` comes from a command in this repository. This guide gives, for each result, a check
anyone can run on a laptop in minutes (from the data recorded in `results/data/`), and the full rerun on a GPU.

## 1. The headline, in one minute, on any computer (no GPU)

> **Where answers can be checked exactly, neo4d's model-free search outperforms a reasoning model by an order of
> magnitude (51 vs 5 and 49 vs 1 of 60 puzzles) at zero model tokens.**

```bash
git clone https://github.com/devkancheti4-design/neo4d.git
cd neo4d
python3 -m venv .venv && . .venv/bin/activate
pip install -e .
python -m neo4d.reasoning_vs_search --recheck
```

It makes the 120 puzzles again from their seed, reads and checks again every reply the reasoning model gave (kept in
`results/data/reasoning/reasoning_runs.json.gz`), runs neo4d's search again, and compares each number with the
recorded one. Expected output:

```
countdown (60 puzzles, seed 1)
  A reasoning                      recorded  5/60  now  5/60  same
  B0 instant guess                 recorded  3/60  now  3/60  same
  B guess + search, 100 checks     recorded 40/60  now 40/60  same
  B guess + search, 400 checks     recorded 51/60  now 51/60  same
  S search alone, 100 checks       recorded 44/60  now 44/60  same
  S search alone, 400 checks       recorded 51/60  now 51/60  same

blocks (60 puzzles, seed 1)
  A reasoning                      recorded  1/60  now  1/60  same
  B0 instant guess                 recorded  1/60  now  1/60  same
  B guess + search, 100 checks     recorded  8/60  now  8/60  same
  B guess + search, 400 checks     recorded 25/60  now 25/60  same
  S search alone, 100 checks       recorded 48/60  now 48/60  same
  S search alone, 400 checks       recorded 49/60  now 49/60  same

Every number reproduced.
```

The search is deterministic; the whole check takes under a second. To read the replies yourself:
`python -c "import gzip,json; d=json.loads(gzip.open('results/data/reasoning/reasoning_runs.json.gz').read()); print(d['results']['countdown'][0]['A_text'][-500:])"`.

## 2. The headline from scratch, on a GPU (about 1.5 hours)

What we used: one NVIDIA L4 (24 GB), driver 570.133 (CUDA 12.8), Ubuntu 24.04, Python 3.12 - an E2E Networks node
at ₹49 an hour; any 24 GB GPU works.

```bash
python3 -m venv ~/venv-vllm
~/venv-vllm/bin/pip install -r requirements/gpu-vllm.txt     # the exact versions that ran (vLLM 0.11.0, PyTorch 2.8.0)
~/venv-vllm/bin/pip install -e .
~/venv-vllm/bin/python -m neo4d.reasoning_vs_search --tasks 60 --seed 1
```

It downloads DeepSeek-R1-Distill-Llama-8B (about 15 GB) from Hugging Face, runs the four configurations on 60
Countdown and 60 Blocks World puzzles, and writes `results/REASONING.md` and `.build/reasoning_runs.json`.

- With the same versions and GPU the numbers should come out as recorded; the reasoning model samples (temperature
  0.6, seed 0), so another GPU or vLLM version can change a few of its answers. neo4d's search does not sample.
- PyTorch 2.13 and later (and vLLM 0.32) need a CUDA 13 driver (580+). On such a machine newer versions work, but use
  the pinned ones to compare like with like.
- The seconds-per-problem column is timed on 5 problems per domain, one at a time.

## 3. Every other result

| result | from the recorded data, no GPU | full rerun | time |
|---|---|---|---|
| reasoning vs search (`results/REASONING.md`) | `python -m neo4d.reasoning_vs_search --recheck` (or `--report`) | section 2 | 1 s / 1.5 h on an L4 |
| public repositories, Claude (`results/PUBLIC_AGENT.md`) | `python -m neo4d.public_agent --fetch` then `python -m neo4d.public_agent --agent-score sonnet,haiku` - every working copy is rebuilt by replaying its recorded trace (`results/data/public_runs/`) and judged by the repository's own test suite | Claude Code subagents with the prompt in `docs/SUBAGENT_PROMPTS.md` section 5, then the same scoring | 10 min / about 20 min per model |
| public repositories, an open model (`results/PUBLIC_AGENT.md`) | - | ollama with `qwen2.5-coder:32b` (one slot, flash attention, 8-bit KV cache to fit 24 GB), then `python -m neo4d.public_agent --model qwen2.5-coder:32b --solver "model alone"`, `--solver "neo4d + model"`, `--report qwen2.5-coder:32b` | hours on an L4 |
| training on neo4d's data (`results/DECISIVE.md`) | `python -m neo4d.decisive restore`, then `report`, `report_free`, `decontam` (`pip install evalplus` for the last) | `scripts/run_decisive.sh`, then `scripts/run_decisive_free.sh`, with `requirements/gpu-vllm.txt` in `/root/venv-vllm` and `requirements/gpu-train.txt` (`--extra-index-url https://download.pytorch.org/whl/cu128`) in `/root/venv-train` | seconds / about 2 h each |
| scaling over puzzle and model size (`results/SCALING.md`; in progress on 2026-10-23) | `python -m neo4d.scaling --search` (neo4d's side, about 1 minute), `--report` | `python -m neo4d.scaling --model deepseek-ai/DeepSeek-R1-Distill-Qwen-1.5B`, `...-Llama-8B`, `...-Qwen-14B --quant fp8` | 1 min / about 2 h |
| SWE-bench Lite pilot (`results/SWEBENCH_PILOT.md`, stopped) | the runs in `results/data/swebench_2026-10-22/runs.tar.gz` | `docs/SWEBENCH.md` (Docker, x86-64), commits on the branch `swebench-pilot-2026-10-22` | hours |
| everything before 2026-10-22 | `AGENTS.md` section 4 | `AGENTS.md` section 4 | `AGENTS.md` section 4 |

## 4. What can trip a rerun

`AGENTS.md` section 7 lists every pitfall met: the CUDA 12.8 driver and the versions it allows, swebench 5 against
4.1.0, MBPP's near-duplicate problems, E2E's one-GPU limit and that powering a node off does not stop its billing.
