"""Scaling: reasoning models against neo4d's search as the puzzles grow and the models grow.

THE PUZZLES - the core's two domains (neo4d/domains), their prompts, parsers and checkers unchanged, at three sizes
    Countdown     S: 4 numbers, target from 2-3 of them   M: 6 numbers, 3-4   L: 8 numbers, 4-5   (targets 10-999)
    Blocks World  S: 4 blocks                             M: 6 blocks          L: 8 blocks
THE REASONING MODELS - DeepSeek-R1-Distill at three sizes: Qwen-1.5B, Llama-8B, Qwen-14B (8-bit weights to fit an L4);
    each thinks up to 6,000 tokens, temperature 0.6, seed 0, one try (vLLM)
NEO4D - its search alone (core.search: beam 3, every one-step variant ranked by the checker's partial score), from the
    domain's fixed start, no model; limited only by its check budget (100, 400, 2,000) - not by depth, so a large
    puzzle is reachable at all
Reported per cell (20 puzzles): solved; model tokens and GPU seconds per problem; checks and CPU seconds per problem.

    python -m neo4d.scaling --search                                  neo4d's side (CPU)
    python -m neo4d.scaling --model deepseek-ai/DeepSeek-R1-Distill-Qwen-1.5B   a model's side (GPU)
    python -m neo4d.scaling --report                                  -> results/SCALING.md, results/scaling.png
"""
from __future__ import annotations

import argparse
import ast
import json
import random
import time
from collections import defaultdict

from neo4d import REPO
from neo4d import core as C
from neo4d.domains import blocks as BW
from neo4d.domains import countdown as CD
from neo4d.reasoning_vs_search import read_answer

N, SEED = 20, 7
SIZES = {"countdown": {"S": (4, 2, 3), "M": (6, 3, 4), "L": (8, 4, 5)}, "blocks": {"S": 4, "M": 6, "L": 8}}
BUDGETS = (100, 400, 2000)
MODELS = ("deepseek-ai/DeepSeek-R1-Distill-Qwen-1.5B", "deepseek-ai/DeepSeek-R1-Distill-Llama-8B",
          "deepseek-ai/DeepSeek-R1-Distill-Qwen-14B")
STORE = REPO / ".build" / "scaling.json"
DATA = REPO / "results" / "data" / "scaling.json"


def countdown_tasks(n, seed, k, lo, hi):
    """Countdown.tasks with the number of numbers and the expression's size as parameters."""
    rng = random.Random(seed)
    out = []
    while len(out) < n:
        nums = rng.sample(CD.LARGE, 1 if k <= 5 else 2) + rng.sample(CD.SMALL, k - (1 if k <= 5 else 2))
        rng.shuffle(nums)
        use = rng.sample(nums, rng.randint(lo, hi))
        expr = str(use[0])
        for x in use[1:]:
            expr = f"({expr} {rng.choice('+-*')} {x})"
        t = CD.value(ast.parse(expr, mode="eval").body)
        if t.denominator == 1 and 10 <= t <= 999 and int(t) not in nums:
            out.append(dict(id=f"cd{k}-{seed}-{len(out)}", numbers=nums, target=int(t), _witness=expr))
    return out


def blocks_tasks(n, seed, size):
    """Blocks.tasks with a fixed number of blocks."""
    rng = random.Random(seed)
    out = []
    while len(out) < n:
        names = rng.sample(BW.NAMES, size)
        kind = rng.choice(("reverse", "unstack", "stack", "reorder", "scramble"))
        tower = lambda bs: {b: ("table" if i == 0 else bs[i - 1]) for i, b in enumerate(bs)}
        if kind == "reverse":
            init, goal = tower(names), tower(names[::-1])
        elif kind == "unstack":
            init, goal = tower(names), {b: "table" for b in names}
        elif kind == "stack":
            init, goal = {b: "table" for b in names}, tower(names)
        elif kind == "reorder":
            perm = names[:]
            while perm == names:
                rng.shuffle(perm)
            init, goal = tower(names), tower(perm)
        else:
            goal = tower(names[:size // 2 + 1]) | tower(names[size // 2 + 1:])
            init = dict(goal)
            for _ in range(rng.randint(2, size)):
                clear = [b for b in init if not any(v == b for v in init.values())]
                b = rng.choice(clear)
                d = rng.choice([x for x in clear if x != b] + ["table"])
                init[b] = d
            if init == goal:
                continue
        task = dict(id=f"bw{size}-{seed}-{len(out)}", kind=kind, init=init, goal=goal, order=names)
        task["_witness"] = BW.naive(task)
        out.append(task)
    return out


def cells():
    """-> [(domain name, size label, domain object, tasks)]"""
    out = []
    for size, (k, lo, hi) in SIZES["countdown"].items():
        out.append(("countdown", size, CD.Countdown(), countdown_tasks(N, SEED, k, lo, hi)))
    for size, b in SIZES["blocks"].items():
        out.append(("blocks", size, BW.Blocks(), blocks_tasks(N, SEED, b)))
    return out


def load():
    return json.loads(STORE.read_text()) if STORE.exists() else {}


def save(d):
    STORE.parent.mkdir(parents=True, exist_ok=True)
    STORE.write_text(json.dumps(d, indent=1))


def run_search():
    d = load()
    for dom_name, size, dom, tasks in cells():
        for budget in BUDGETS:
            rows = []
            for t in tasks:
                stats = defaultdict(int)
                t0 = time.time()
                found, _ = C.search(dom, t, [dom.start(t)], budget, stats, depth=10 ** 6)
                rows.append(dict(id=t["id"], ok=found is not None, checks=stats["checks"], seconds=time.time() - t0))
            d.setdefault("search", {})[f"{dom_name}/{size}/{budget}"] = rows
            print(f"search {dom_name} {size} {budget}: {sum(r['ok'] for r in rows)}/{len(rows)} "
                  f"({sum(r['seconds'] for r in rows) / len(rows):.2f} s each)", flush=True)
            save(d)


def run_model(model, quant):
    from transformers import AutoTokenizer
    from vllm import LLM, SamplingParams
    tok = AutoTokenizer.from_pretrained(model)
    llm = LLM(model=model, seed=0, gpu_memory_utilization=0.9, max_model_len=8192, quantization=quant)
    sp = SamplingParams(temperature=0.6, top_p=0.95, max_tokens=6000, seed=0)
    d = load()
    for dom_name in ("countdown", "blocks"):
        group = [c for c in cells() if c[0] == dom_name]
        prompts, where = [], []
        for _, size, dom, tasks in group:
            for t in tasks:
                prompts.append(tok.apply_chat_template([{"role": "user", "content": dom.prompt(t)}], tokenize=False,
                                                       add_generation_prompt=True))
                where.append((size, dom, t))
        t0 = time.time()
        outs = llm.generate(prompts, sp)
        secs = time.time() - t0
        by = defaultdict(list)
        for (size, dom, t), o in zip(where, outs):
            text = o.outputs[0].text
            cand = read_answer(dom, t, text)
            by[size].append(dict(id=t["id"], ok=cand is not None and dom.check(t, cand)[0], tokens=len(o.outputs[0].token_ids),
                                 closed="</think>" in text, read=cand is not None))
        for size, rows in by.items():
            d.setdefault("models", {})[f"{model}/{dom_name}/{size}"] = dict(rows=rows, batch_seconds_per_problem=secs / len(prompts))
        print(f"{model} {dom_name}: " + ", ".join(f"{s} {sum(r['ok'] for r in rows)}/{len(rows)}" for s, rows in by.items())
              + f" ({secs:.0f} s)", flush=True)
        save(d)


def report():
    d = load() if STORE.exists() else json.loads(DATA.read_text())
    short = lambda m: m.split("Distill-")[-1]
    lines = ["# Scaling: reasoning models against neo4d's search as puzzles and models grow", "",
             "Generated by `neo4d/scaling.py`. " + __doc__.split("\n\n")[1].replace("\n", " ").strip(), "",
             f"{N} puzzles per cell (seed {SEED}). Reasoning: DeepSeek-R1-Distill, up to 6,000 thinking tokens, one try. "
             "neo4d: search alone from a fixed start, no model, limited only by its check budget.", ""]
    for dom_name in ("countdown", "blocks"):
        lines += [f"## {dom_name}", "", "| solver | " + " | ".join(f"size {s}" for s in SIZES[dom_name])
                  + " | model tokens per problem (S / M / L) | seconds per problem (S / M / L) |",
                  "|---|" + "---|" * (len(SIZES[dom_name]) + 2)]
        for m in MODELS:
            cellsm = [d.get("models", {}).get(f"{m}/{dom_name}/{s}") for s in SIZES[dom_name]]
            if not any(cellsm):
                continue
            solved = [f"{sum(r['ok'] for r in c['rows'])}/{len(c['rows'])}" if c else "-" for c in cellsm]
            toks = [f"{sum(r['tokens'] for r in c['rows']) / len(c['rows']):.0f}" if c else "-" for c in cellsm]
            secs = [f"{c['batch_seconds_per_problem']:.1f}" if c else "-" for c in cellsm]
            lines.append(f"| {short(m)} reasoning | " + " | ".join(solved) + f" | {' / '.join(toks)} | {' / '.join(secs)} (GPU, batched) |")
        for b in BUDGETS:
            rs = [d.get("search", {}).get(f"{dom_name}/{s}/{b}") for s in SIZES[dom_name]]
            if not any(rs):
                continue
            solved = [f"{sum(r['ok'] for r in x)}/{len(x)}" if x else "-" for x in rs]
            secs = [f"{sum(r['seconds'] for r in x) / len(x):.2f}" if x else "-" for x in rs]
            lines.append(f"| **neo4d search, {b} checks** | " + " | ".join(f"**{x}**" for x in solved)
                         + f" | 0 / 0 / 0 | {' / '.join(secs)} (CPU) |")
        lines.append("")
    (REPO / "results" / "SCALING.md").write_text("\n".join(lines) + "\n")
    DATA.write_text(json.dumps(d))
    print("\n".join(lines))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--search", action="store_true")
    ap.add_argument("--model")
    ap.add_argument("--quant", default=None, help="vLLM quantization, e.g. fp8 for the 14B model on an L4")
    ap.add_argument("--report", action="store_true")
    a = ap.parse_args()
    if a.search:
        run_search()
    if a.model:
        run_model(a.model, a.quant)
    if a.report:
        report()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
