"""Reasoning tokens against neo4d's search: does an instant guess plus neo4d match a reasoning model that thinks?

THE MODEL. DeepSeek-R1-Distill-Llama-8B (vLLM, on a GPU) - a reasoning model that writes a <think> ... </think> block
before its answer.

THE TASKS. The core experiment's two domains, unchanged (neo4d/domains): Countdown (make the target from the numbers)
and Blocks World (a plan of moves), checked exactly by each domain's checker.

THE CONFIGURATIONS - the same model, the same prompt (the domain's own), the same sampling (temperature 0.6, seed 0)
    A  reasoning      the model thinks as long as it likes (up to 6,000 tokens), then answers; one try
    B  neo4d          thinking off: the reply is pre-filled with an empty <think></think>, so the model answers at once
                      (up to 256 tokens); neo4d's search (core.search, depth 4) then works from that guess, up to the
                      check budget; no further model call
    B0 guess only     B's guess, checked, without the search - what the search adds
    S  search only    no model: neo4d's search from the domain's fixed start, the same check budget
Reported: solved, tokens the model generated, GPU seconds (batched), seconds per problem one at a time (a sample),
checker calls; check budgets 100 and 400.

    python -m neo4d.reasoning_vs_search --tasks 60 --seed 1          -> results/REASONING.md
"""
from __future__ import annotations

import argparse
import json
import re
import time
from collections import defaultdict

from neo4d import REPO
from neo4d import core as C
from neo4d.domains.blocks import Blocks
from neo4d.domains.countdown import Countdown

MODEL = "deepseek-ai/DeepSeek-R1-Distill-Llama-8B"
DOMAINS = {"countdown": Countdown, "blocks": Blocks}
STORE = REPO / ".build" / "reasoning_runs.json"
OUT = REPO / "results" / "REASONING.md"


def answer_part(text):
    """What follows the reasoning: the text after </think>, or all of it when the model never closed the block."""
    return text.split("</think>", 1)[1] if "</think>" in text else text


def search_from(dom, task, cand, budget):
    stats = defaultdict(int)
    start = cand if cand is not None else dom.start(task)
    if cand is not None:
        stats["checks"] += 1
        if dom.check(task, cand)[0]:
            return True, "guess", stats["checks"]
    found, _ = C.search(dom, task, [start], budget, stats, depth=4)
    return found is not None, ("neo4d" if found is not None else None), stats["checks"]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--tasks", type=int, default=60)
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--model", default=MODEL)
    ap.add_argument("--latency", type=int, default=5, help="problems per domain timed one at a time")
    a = ap.parse_args()
    from transformers import AutoTokenizer
    from vllm import LLM, SamplingParams
    tok = AutoTokenizer.from_pretrained(a.model)
    llm = LLM(model=a.model, seed=0, gpu_memory_utilization=0.9, max_model_len=8192)
    think = SamplingParams(temperature=0.6, top_p=0.95, max_tokens=6000, seed=0)
    quick = SamplingParams(temperature=0.6, top_p=0.95, max_tokens=256, seed=0)

    def prompts(dom, tasks, thinking):
        out = []
        for t in tasks:
            p = tok.apply_chat_template([{"role": "user", "content": dom.prompt(t)}], tokenize=False,
                                        add_generation_prompt=True)
            if not thinking:                       # an empty reasoning block: the model goes straight to its answer
                p = p + ("\n</think>\n\n" if p.rstrip().endswith("<think>") else "<think>\n\n</think>\n\n")
            out.append(p)
        return out

    res = {}
    for name, D in DOMAINS.items():
        dom = D()
        tasks = dom.tasks(a.tasks, a.seed)
        rows = {t["id"]: dict(id=t["id"]) for t in tasks}
        for label, thinking, sp in (("A", True, think), ("B", False, quick)):
            ps = prompts(dom, tasks, thinking)
            t0 = time.time()
            outs = llm.generate(ps, sp)
            secs = time.time() - t0
            for t, o in zip(tasks, outs):
                text = o.outputs[0].text
                cand = dom.parse(t, answer_part(text))
                r = rows[t["id"]]
                r[f"{label}_tokens"] = len(o.outputs[0].token_ids)
                r[f"{label}_closed"] = (not thinking) or ("</think>" in text)
                r[f"{label}_cand"] = cand if cand is None or isinstance(cand, str) else list(cand)
                r[f"{label}_ok"] = cand is not None and dom.check(t, cand)[0]
            res[f"{name}_{label}_batch_seconds"] = round(secs, 1)
        # sequential latency on a sample: one problem at a time, as an interactive user would wait
        for label, thinking, sp in (("A", True, think), ("B", False, quick)):
            lat = []
            for t in tasks[:a.latency]:
                p = prompts(dom, [t], thinking)
                t0 = time.time()
                llm.generate(p, sp, use_tqdm=False)
                lat.append(time.time() - t0)
            res[f"{name}_{label}_seconds_each"] = [round(x, 1) for x in lat]
        for budget in (100, 400):
            for t in tasks:
                r = rows[t["id"]]
                cand = r["B_cand"] if r["B_cand"] is None or isinstance(r["B_cand"], str) else tuple(map(tuple, r["B_cand"]))
                t0 = time.time()
                ok, how, checks = search_from(dom, t, cand, budget)
                r[f"B_{budget}"] = dict(ok=ok, how=how, checks=checks, seconds=round(time.time() - t0, 3))
                ok, how, checks = search_from(dom, t, None, budget)
                r[f"S_{budget}"] = dict(ok=ok, checks=checks)
        res[name] = list(rows.values())
    STORE.write_text(json.dumps(dict(model=a.model, tasks=a.tasks, seed=a.seed, results=res), indent=1))
    report(res, a)
    return 0


def report(res, a):
    lines = ["# Reasoning tokens against neo4d's search", "",
             f"Generated by `neo4d/reasoning_vs_search.py`. Model `{a.model}` (vLLM, NVIDIA L4); {a.tasks} tasks per "
             f"domain, seed {a.seed}; temperature 0.6, seed 0, one try. A: the model reasons (up to 6,000 tokens). "
             "B: reasoning off (an empty <think></think> pre-filled), an instant guess, then neo4d's search from it. B0: "
             "the guess alone. S: neo4d's search alone, no model.", ""]
    for name in DOMAINS:
        rows = res[name]
        n = len(rows)
        mean = lambda k: sum(r[k] for r in rows) / n
        la, lb = res[f"{name}_A_seconds_each"], res[f"{name}_B_seconds_each"]
        lines += [f"## {name}", "",
                  "| configuration | solved | tokens generated per problem | GPU seconds for all (batched) | seconds per "
                  "problem, one at a time | checker calls per problem |", "|---|---|---|---|---|---|",
                  f"| A reasoning | **{sum(r['A_ok'] for r in rows)}/{n}** | {mean('A_tokens'):.0f} | "
                  f"{res[f'{name}_A_batch_seconds']} | {sum(la) / len(la):.1f} | 1 |",
                  f"| B0 instant guess only | {sum(r['B_ok'] for r in rows)}/{n} | {mean('B_tokens'):.0f} | "
                  f"{res[f'{name}_B_batch_seconds']} | {sum(lb) / len(lb):.1f} | 1 |"]
        for budget in (100, 400):
            b = [r[f"B_{budget}"] for r in rows]
            s = [r[f"S_{budget}"] for r in rows]
            lines.append(f"| **B guess + neo4d, {budget} checks** | **{sum(x['ok'] for x in b)}/{n}** "
                         f"({sum(x['how'] == 'neo4d' for x in b)} by the search) | {mean('B_tokens'):.0f} | "
                         f"{res[f'{name}_B_batch_seconds']} + search | {sum(lb) / len(lb):.1f} + "
                         f"{sum(x['seconds'] for x in b) / n:.2f} | {sum(x['checks'] for x in b) / n:.0f} |")
            lines.append(f"| S search alone, {budget} checks | {sum(x['ok'] for x in s)}/{n} | 0 | 0 | - | "
                         f"{sum(x['checks'] for x in s) / n:.0f} |")
        both = [(r["A_ok"], r["B_400"]["ok"]) for r in rows]
        lines += ["", f"A solved and B (400) did not: {sum(x and not y for x, y in both)}; B solved and A did not: "
                  f"{sum(y and not x for x, y in both)}. A's reasoning was cut off (no </think> within 6,000 tokens) on "
                  f"{sum(not r['A_closed'] for r in rows)} problems.", ""]
    OUT.write_text("\n".join(lines) + "\n")
    print("\n".join(lines))


if __name__ == "__main__":
    raise SystemExit(main())
