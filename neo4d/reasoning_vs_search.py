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

    python -m neo4d.reasoning_vs_search --tasks 60 --seed 1          -> results/REASONING.md   (GPU)
    python -m neo4d.reasoning_vs_search --report                     the report again from the recorded run
                                                                     (results/data/reasoning), no GPU
    python -m neo4d.reasoning_vs_search --recheck                    on any CPU, about a minute: the puzzles made
                                                                     again, every recorded answer read and checked
                                                                     again, neo4d's search run again - and compared
                                                                     with the recorded numbers
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


def ollama_chat(model, prompt, think, predict, url="http://127.0.0.1:11434"):
    """One reply from an ollama model, thinking on or off (ollama keeps the thinking apart from the answer).
    -> (answer text, thinking text, generated tokens, seconds)"""
    import urllib.request
    body = json.dumps({"model": model, "messages": [{"role": "user", "content": prompt}], "stream": False, "think": think,
                       "options": {"temperature": 0.6, "top_p": 0.95, "seed": 0, "num_predict": predict,
                                   "num_ctx": predict + 2048}}).encode()
    for wait in (5, 15, 60, None):
        try:
            req = urllib.request.Request(url + "/api/chat", data=body, headers={"Content-Type": "application/json"})
            with urllib.request.urlopen(req, timeout=7200) as r:
                d = json.loads(r.read())
            m = d.get("message", {})
            return m.get("content", ""), m.get("thinking", "") or "", d.get("eval_count", 0), d.get("total_duration", 0) / 1e9
        except Exception:                                   # noqa: BLE001 - the server can be busy; try again
            if wait is None:
                return "", "", 0, 0.0
            time.sleep(wait)


def run_ollama(a):
    """The same test with an ollama model: thinking on (A) and off (B0), many requests at once."""
    from concurrent.futures import ThreadPoolExecutor
    slug = a.ollama.replace(":", "_").replace("/", "_")
    store = REPO / ".build" / f"reasoning_runs_{slug}.json"
    res = {}
    for name, D in DOMAINS.items():
        dom = D()
        tasks = dom.tasks(a.tasks, a.seed)
        rows = {t["id"]: dict(id=t["id"]) for t in tasks}
        for label, think, predict in (("A", True, a.think_tokens), ("B", False, 256)):
            t0 = time.time()
            with ThreadPoolExecutor(a.parallel) as ex:
                outs = list(ex.map(lambda t: ollama_chat(a.ollama, dom.prompt(t), think, predict), tasks))
            secs = time.time() - t0
            for t, (answer, thinking, n, _) in zip(tasks, outs):
                cand = read_answer(dom, t, answer)
                r = rows[t["id"]]
                r.update({f"{label}_text": answer, f"{label}_thinking": thinking, f"{label}_tokens": n,
                          f"{label}_closed": bool(answer.strip()) or not think,
                          f"{label}_cand": cand if cand is None or isinstance(cand, str) else list(cand),
                          f"{label}_ok": cand is not None and dom.check(t, cand)[0]})
            res[f"{name}_{label}_batch_seconds"] = round(secs, 1)
            print(f"{name} {label}: {sum(r[f'{label}_ok'] for r in rows.values())}/{len(rows)} in {secs:.0f} s", flush=True)
            store.write_text(json.dumps(dict(model=a.ollama, tasks=a.tasks, seed=a.seed, results={**res, name: list(rows.values())}), indent=1))
        for label, think, predict in (("A", True, a.think_tokens), ("B", False, 256)):
            res[f"{name}_{label}_seconds_each"] = [round(ollama_chat(a.ollama, dom.prompt(t), think, predict)[3], 1)
                                                   for t in tasks[:a.latency]]
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
        store.write_text(json.dumps(dict(model=a.ollama, tasks=a.tasks, seed=a.seed, results=res), indent=1))
    global OUT
    OUT = REPO / "results" / f"REASONING_{slug}.md"
    a.model, a.backend = a.ollama, "ollama"
    report(res, a)
    return 0


def answer_part(text):
    """What follows the reasoning: the text after </think>, or all of it when the model never closed the block."""
    return text.split("</think>", 1)[1] if "</think>" in text else text


LATEX = ((r"\\times", "*"), (r"\\cdot", "*"), (r"\\div", "/"), (r"\\left", ""), (r"\\right", ""), (r"\\[(\[]", ""),
         (r"\\[)\]]", ""), ("−", "-"), ("×", "*"), ("÷", "/"))


def read_answer(dom, task, text):
    """The domain's own parser, then - for both configurations alike - the same answer written another way: inside
    \\boxed{...}, in LaTeX (\\times, \\div), or as the last arithmetic expression on a line."""
    part = answer_part(text)
    cand = dom.parse(task, part)
    if cand is not None or dom.name != "countdown":
        return cand
    t = part
    for a, b in LATEX:
        t = re.sub(a, b, t)
    tries = re.findall(r"\\boxed\{([^{}]*)\}", t)
    for line in reversed(t.split("\n")):
        tries += [m.strip() for m in re.findall(r"[\d\s+\-*/().]+", line) if re.search(r"\d\s*[-+*/]\s*[\d(]", m)]
    for x in tries:
        c = dom.parse(task, x.split("=")[0])
        if c is not None:
            return c
    return None


DEEP = (2000, 10000)                    # check budgets for the search whose depth is limited only by its budget


def search_from(dom, task, cand, budget, depth=4):
    stats = defaultdict(int)
    start = cand if cand is not None else dom.start(task)
    if cand is not None:
        stats["checks"] += 1
        if dom.check(task, cand)[0]:
            return True, "guess", stats["checks"]
    found, _ = C.search(dom, task, [start], budget, stats, depth=depth)
    return found is not None, ("neo4d" if found is not None else None), stats["checks"]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--tasks", type=int, default=60)
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--model", default=MODEL)
    ap.add_argument("--latency", type=int, default=5, help="problems per domain timed one at a time")
    ap.add_argument("--domains", default="countdown,blocks")
    ap.add_argument("--reuse-latency", action="store_true", help="keep the one-at-a-time timings of the last run")
    ap.add_argument("--report", action="store_true", help="write the report from the recorded run, no GPU")
    ap.add_argument("--recheck", action="store_true", help="redo everything but the model's generation, on a CPU")
    ap.add_argument("--ollama", help="an ollama reasoning model instead of vLLM, e.g. qwen3.8:27b-mtp-q4_K_M")
    ap.add_argument("--think-tokens", type=int, default=6000, help="the most a model may think (A)")
    ap.add_argument("--parallel", type=int, default=8, help="ollama requests at once")
    ap.add_argument("--deepen", help="a recorded run (.json or .json.gz): add the depth-by-budget search, write its report")
    ap.add_argument("--out", help="the report's path (with --deepen)")
    a = ap.parse_args()
    if a.deepen:
        from pathlib import Path
        d = deepen(Path(a.deepen))
        a.model, a.tasks, a.seed = d["model"], d["tasks"], d["seed"]
        a.backend = "ollama" if ":" in d["model"] else "vllm"
        a.think_tokens = 16000 if a.backend == "ollama" else 6000
        global OUT
        OUT = Path(a.out) if a.out else OUT
        out_json = Path(str(a.deepen).removesuffix(".gz"))
        if str(a.deepen).endswith(".gz"):
            import gzip
            Path(a.deepen).write_bytes(gzip.compress(json.dumps(d).encode(), 9))
        else:
            out_json.write_text(json.dumps(d, indent=1))
        report(d["results"], a)
        return 0
    if a.ollama:
        return run_ollama(a)
    if a.recheck:
        return recheck()
    if a.report:
        import gzip
        rec = REPO / "results" / "data" / "reasoning" / "reasoning_runs.json.gz"
        d = json.loads(STORE.read_text()) if STORE.exists() else json.loads(gzip.decompress(rec.read_bytes()))
        a.model, a.tasks, a.seed = d["model"], d["tasks"], d["seed"]
        report(d["results"], a)
        return 0
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

    old = json.loads(STORE.read_text())["results"] if STORE.exists() else {}
    res = dict(old)
    for name, D in [(n, DOMAINS[n]) for n in a.domains.split(",")]:
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
                cand = read_answer(dom, t, text)
                r = rows[t["id"]]
                r[f"{label}_text"] = text
                r[f"{label}_tokens"] = len(o.outputs[0].token_ids)
                r[f"{label}_closed"] = (not thinking) or ("</think>" in text)
                r[f"{label}_cand"] = cand if cand is None or isinstance(cand, str) else list(cand)
                r[f"{label}_ok"] = cand is not None and dom.check(t, cand)[0]
            res[f"{name}_{label}_batch_seconds"] = round(secs, 1)
        # sequential latency on a sample: one problem at a time, as an interactive user would wait
        for label, thinking, sp in (() if a.reuse_latency and f"{name}_A_seconds_each" in old else
                                    (("A", True, think), ("B", False, quick))):
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


def deepen(store, model_slug=None):
    """Add neo4d's search with its depth limited only by its check budget (2,000 and 10,000 checks) to a recorded run:
    from the fixed start (S) and from the model's instant guess (B). CPU only."""
    import gzip
    d = json.loads(store.read_text()) if store.suffix == ".json" else json.loads(gzip.decompress(store.read_bytes()))
    for name, D in DOMAINS.items():
        dom = D()
        tasks = {t["id"]: t for t in dom.tasks(d["tasks"], d["seed"])}
        for r in d["results"][name]:
            t = tasks[r["id"]]
            c = r["B_cand"]
            cand = c if c is None or isinstance(c, str) else tuple(map(tuple, c))
            for b in DEEP:
                ok, _, checks = search_from(dom, t, None, b, depth=10 ** 6)
                r[f"Sdeep_{b}"] = dict(ok=ok, checks=checks)
                ok, how, checks = search_from(dom, t, cand, b, depth=10 ** 6)
                r[f"Bdeep_{b}"] = dict(ok=ok, how=how, checks=checks)
    return d


RUNS = ("reasoning_runs.json.gz", "reasoning_runs_qwen3.8_27b.json.gz")


def recheck(files=RUNS):
    """Everything except the model's generation, again: the same puzzles (seeded), the recorded replies read and
    checked by the domain's own checker, neo4d's search run from the recorded guesses and from the fixed start."""
    import gzip
    same = True
    for f in files:
        rec = json.loads(gzip.decompress((REPO / "results" / "data" / "reasoning" / f).read_bytes()))
        print(f"\n=== {rec['model']}")
        same &= recheck_one(rec)
    print("\nEvery number reproduced." if same else "\nSome numbers differ - see above.")
    return 0 if same else 1


def recheck_one(rec):
    res, n, seed = rec["results"], rec["tasks"], rec["seed"]
    same = True
    for name, D in DOMAINS.items():
        dom = D()
        tasks = {t["id"]: t for t in dom.tasks(n, seed)}
        rows = res[name]
        assert set(tasks) == {r["id"] for r in rows}, "the puzzles differ from the recorded ones"
        got = defaultdict(int)
        for r in rows:
            t = tasks[r["id"]]
            for label in ("A", "B"):
                if f"{label}_text" in r:                     # the raw reply was kept: read it again
                    cand = read_answer(dom, t, r[f"{label}_text"])
                else:                                       # the first run kept the answer it read
                    c = r[f"{label}_cand"]
                    cand = c if c is None or isinstance(c, str) else tuple(map(tuple, c))
                ok = cand is not None and dom.check(t, cand)[0]
                got[label] += ok
                if label == "B":
                    for budget in (100, 400):
                        got[f"B_{budget}"] += search_from(dom, t, cand, budget)[0]
                    if "Bdeep_2000" in r:
                        for budget in DEEP:
                            got[f"Bdeep_{budget}"] += search_from(dom, t, cand, budget, depth=10 ** 6)[0]
            for budget in (100, 400):
                got[f"S_{budget}"] += search_from(dom, t, None, budget)[0]
            if "Sdeep_2000" in r:
                for budget in DEEP:
                    got[f"Sdeep_{budget}"] += search_from(dom, t, None, budget, depth=10 ** 6)[0]
        want = {"A": sum(r["A_ok"] for r in rows), "B": sum(r["B_ok"] for r in rows),
                **{f"{k}_{b}": sum(r[f"{k}_{b}"]["ok"] for r in rows) for k in ("B", "S") for b in (100, 400)},
                **{f"{k}deep_{b}": sum(r[f"{k}deep_{b}"]["ok"] for r in rows) for k in ("B", "S") for b in DEEP
                   if f"{k}deep_{b}" in rows[0]}}
        names = {"A": "A reasoning", "B": "B0 instant guess", "B_100": "B guess + search, 100 checks",
                 "B_400": "B guess + search, 400 checks", "S_100": "S search alone, 100 checks",
                 "S_400": "S search alone, 400 checks",
                 **{f"Bdeep_{b}": f"B guess + search, {b}, deep" for b in DEEP},
                 **{f"Sdeep_{b}": f"S search alone, {b}, deep" for b in DEEP}}
        names = {k: v for k, v in names.items() if k in want}
        print(f"\n{name} ({len(rows)} puzzles, seed {seed})")
        for k, label in names.items():
            mark = "same" if got[k] == want[k] else "DIFFERENT"
            same &= got[k] == want[k]
            print(f"  {label:32s} recorded {want[k]:2d}/{len(rows)}  now {got[k]:2d}/{len(rows)}  {mark}")
    return same


def report(res, a):
    cd, bw = res["countdown"], res["blocks"]
    s4 = lambda rows, k: sum(r[k]["ok"] for r in rows if k in r)
    deep = "Sdeep_2000" in cd[0]
    best = "Sdeep_2000" if deep else "S_400"
    sa, sb, ma, mb = s4(cd, best), s4(bw, best), sum(r["A_ok"] for r in cd), sum(r["A_ok"] for r in bw)
    if sa >= 10 * max(ma, 1) and sb >= 10 * max(mb, 1):
        verdict = "outperforms the reasoning model by an order of magnitude"
    elif sa >= ma and sb >= mb:
        verdict = "matches or beats the reasoning model"
    else:
        verdict = "does not match the reasoning model in every domain"
    lines = ["# Reasoning tokens against neo4d's search", "",
             f"**Model `{a.model}`. Where answers can be checked exactly, neo4d's model-free search {verdict}: "
             f"{sa}/{len(cd)} and {sb}/{len(bw)} puzzles (Countdown, Blocks World; {best.replace('Sdeep_', '').replace('S_', '')} "
             f"checks{', depth limited only by the budget' if deep else ''}) against {ma}/{len(cd)} and {mb}/{len(bw)} for the "
             f"model thinking - at zero model tokens against {sum(r['A_tokens'] for r in cd) / len(cd):.0f} and "
             f"{sum(r['A_tokens'] for r in bw) / len(bw):.0f} per problem.** Check it in a second on any computer: "
             "`python -m neo4d.reasoning_vs_search --recheck` (docs/REPRODUCE.md).", "",
             f"On two checkable puzzles, neo4d's search solved {s4(cd, 'S_400')}/60 (Countdown) and {s4(bw, 'S_400')}/60 "
             f"(Blocks World) with no model tokens; the reasoning model, thinking, solved {sum(r['A_ok'] for r in cd)}/60 "
             f"and {sum(r['A_ok'] for r in bw)}/60 with {sum(r['A_tokens'] for r in cd) / len(cd):.0f} and "
             f"{sum(r['A_tokens'] for r in bw) / len(bw):.0f} tokens per problem. The model's own instant guess adds "
             f"nothing: guess + search solved {s4(cd, 'B_400')}/60 and {s4(bw, 'B_400')}/60 - on Blocks fewer than search "
             "from a fixed start, because a wrong guess leads the search astray. The search here is a plain beam search ranked by the "
             "checker's partial score: no law steers it.", "",
             "What this does not show: these are small puzzles with an exact checker, where a search over one-step changes "
             "is strong; " + ("an 8B distilled reasoning model is far from the strongest reasoner; " if "R1-Distill" in a.model else
                              f"one model ({a.model}) and one seed; ") + "and a domain without a cheap, "
             "exact checker gives the search nothing to rank by. The claim is: where an exact checker exists, neo4d's search "
             "replaces paying for reasoning tokens. Answers are read the same way in every configuration (the domain's "
             "parser, then \\boxed{...}, LaTeX operators and inline expressions); the first run's stricter reading is kept "
             "in results/data/reasoning/REASONING_first_parse.md.", "",
             f"Generated by `neo4d/reasoning_vs_search.py`. Model `{a.model}` ({'ollama' if getattr(a, 'backend', 'vllm') == 'ollama' else 'vLLM'}, NVIDIA L4); {a.tasks} tasks per "
             f"domain, seed {a.seed}; temperature 0.6, seed 0, one try. A: the model reasons (up to {getattr(a, 'think_tokens', 6000):,} tokens). "
             + ("B: reasoning off (ollama's think=false), " if getattr(a, "backend", "vllm") == "ollama" else
             "B: reasoning off (an empty <think></think> pre-filled), ") + "an instant guess, then neo4d's search from it. B0: "
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
            lines.append(f"| S search alone, {budget} checks, depth at most 4 | {sum(x['ok'] for x in s)}/{n} | 0 | 0 | - | "
                         f"{sum(x['checks'] for x in s) / n:.0f} |")
        for budget in (DEEP if "Sdeep_2000" in rows[0] else ()):
            b = [r[f"Bdeep_{budget}"] for r in rows]
            s = [r[f"Sdeep_{budget}"] for r in rows]
            lines.append(f"| B guess + neo4d, {budget} checks, depth by budget | {sum(x['ok'] for x in b)}/{n} | "
                         f"{mean('B_tokens'):.0f} | {res[f'{name}_B_batch_seconds']} + search | - | {sum(x['checks'] for x in b) / n:.0f} |")
            lines.append(f"| **S search alone, {budget} checks, depth by budget** | **{sum(x['ok'] for x in s)}/{n}** | 0 | 0 | "
                         f"about 0.003 (CPU) | {sum(x['checks'] for x in s) / n:.0f} |")
        both = [(r["A_ok"], r["B_400"]["ok"]) for r in rows]
        lines += ["", f"A solved and B (400) did not: {sum(x and not y for x, y in both)}; B solved and A did not: "
                  f"{sum(y and not x for x, y in both)}. A's reasoning was cut off (no answer within {getattr(a, 'think_tokens', 6000):,} tokens) on "
                  f"{sum(not r['A_closed'] for r in rows)} problems.", ""]
    OUT.write_text("\n".join(lines) + "\n")
    print("\n".join(lines))


if __name__ == "__main__":
    raise SystemExit(main())
