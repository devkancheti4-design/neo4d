"""Is neo4d core-level? The same core (neo4d/core.py: the loop, the search, verified memory, RELATE v2), unchanged, on
two domains that are not code - only each domain's adapter differs (neo4d/domains/).

    domains   countdown (a numbers puzzle; the checker evaluates exactly) and blocks (planning; the checker simulates)
    methods   alone             the model, one try
              sample            sample-and-filter: up to 4 independent tries, the first the checker accepts
              debug             self-debugging: up to 4 tries, each told what the checker said
              core              neo4d: memory first, then up to 4 model tries, each searched around by neo4d
              core-no-memory    the same without memory
              core-no-mutation  memory, but no search around the model's tries
              core-no-law       the same as core, with every pattern trusted at first sight (no RELATE v2)
              search            no model: neo4d's search alone from a fixed start, the same check budget
    budget    at most 4 model calls per task; 100 checker calls per task (the main setting - checks are usually
              costly: tests, simulators), and 400 reported as well

    python -m neo4d.core_experiment --design                       (a design run: seed 99, 15 tasks, phi4-mini)
    python -m neo4d.core_experiment --models phi4-mini,gemma3:4b --tasks 60 --seeds 1,2   -> results/CORE.md
"""
from __future__ import annotations

import json
import statistics
import sys
import time

from neo4d import KERNELS, REPO
from neo4d import core as C
from neo4d import relate_live as RL
from neo4d.domains.blocks import Blocks
from neo4d.domains.countdown import Countdown
from neo4d.rigor import bootstrap, permutation_p

DOMAINS = {"countdown": Countdown, "blocks": Blocks}
METHODS = ("alone", "sample", "debug", "core", "core-no-memory", "core-no-mutation", "core-no-law", "search")
STORE = REPO / ".build" / "core_runs.json"
OUT = REPO / "results" / "CORE.md"


def run_stream(dom, tasks, model, method, seed, law, checks):
    if method == "search":
        return [C.solve(dom, t, None, "search", checks=checks, seed=seed) for t in tasks]
    mem = None
    if method in ("core", "core-no-mutation"):
        mem = C.Memory(law)
    elif method == "core-no-law":
        mem = C.Memory(C.trust_all)
    m = "core" if method == "core-no-law" else method
    rows = []
    for n, t in enumerate(tasks):
        rows.append(C.solve(dom, t, model, m, mem, checks=checks, seed=seed))
    return rows


MODEL_ONLY = ("alone", "sample", "debug")                 # these never use the checker beyond checking their answer


def experiment(domains, models, n_tasks, seeds, tag, checks=100):
    law = RL.load_law(str(KERNELS / "relate_v2.c"))
    done = json.loads(STORE.read_text()) if STORE.exists() else {}
    t0 = time.time()
    for dname in domains:
        dom = DOMAINS[dname]()
        for seed in seeds:
            tasks = dom.tasks(n_tasks, seed)
            for model in models:
                for method in METHODS:
                    budget = "" if method in MODEL_ONLY else f"|{checks}"
                    key = f"{tag}|{dname}|{model if method != 'search' else '-'}|{seed}|{method}{budget}"
                    if key in done:
                        continue
                    rows = run_stream(dom, tasks, model, method, seed, law, checks)
                    done[key] = rows
                    STORE.write_text(json.dumps(done))
                    print(f"  {tag} {dname} {model} seed {seed} {method}: {sum(r['solved'] for r in rows)}/{len(rows)} "
                          f"calls {sum(r['calls'] for r in rows)} checks {sum(r['checks'] for r in rows)} "
                          f"({time.time() - t0:.0f}s)", flush=True)
    return done


def report(done, domains, models, n_tasks, seeds, tag, title, intro, checks=100):
    out = [f"## {title}", "", intro, ""]
    for dname in domains:
        for model in models:
            rows = {}
            for method in METHODS:
                budget = "" if method in MODEL_ONLY else f"|{checks}"
                runs = [done.get(f"{tag}|{dname}|{model if method != 'search' else '-'}|{s}|{method}{budget}") for s in seeds]
                if all(runs):
                    rows[method] = runs
            if not rows:
                continue
            n = n_tasks
            out += [f"### {dname}, {model}", "",
                    f"| method | solved per seed (of {n}) | mean | 95% interval | model calls per task | checks per task | "
                    "second half of the stream | solved from memory |", "|---|---|---|---|---|---|---|---|"]
            rate = {}
            for method, runs in rows.items():
                per = [sum(r["solved"] for r in rs) for rs in runs]
                rate[method] = [statistics.mean(rs[i]["solved"] for rs in runs) for i in range(n)]
                lo, hi = bootstrap(rate[method])
                half = [statistics.mean(r["solved"] for r in rs[n // 2:]) for rs in runs]
                mem = sum(r["how"] == "memory" for rs in runs for r in rs) / len(runs)
                label = f"**{method}**" if method == "core" else method
                out.append(f"| {label} | {', '.join(map(str, per))} | {statistics.mean(per):.1f} | {lo:.0%}-{hi:.0%} | "
                           f"{statistics.mean(r['calls'] for rs in runs for r in rs):.2f} | "
                           f"{statistics.mean(r['checks'] for rs in runs for r in rs):.0f} | {statistics.mean(half):.0%} | "
                           f"{mem:.1f} |")
            base = [m for m in ("alone", "sample", "debug") if m in rate]
            if "core" in rate and base:
                best = max(base, key=lambda m: statistics.mean(rate[m]))
                d = [a - b for a, b in zip(rate["core"], rate[best])]
                out += ["", f"neo4d core against the best model-only method ({best}): {statistics.mean(d) * n:+.1f} tasks "
                        f"per stream, paired permutation p = {permutation_p(d):.3f}."]
            if "core" in rate and "search" in rate:
                d = [a - b for a, b in zip(rate["core"], rate["search"])]
                out.append(f"neo4d core against search alone (no model): {statistics.mean(d) * n:+.1f} tasks, "
                           f"p = {permutation_p(d):.3f}.")
            out.append("")
    parts = OUT.read_text().rstrip("\n").split("\n## ") if OUT.exists() else [
        "# Is neo4d core-level? The same core on domains that are not code\n\nGenerated by `neo4d/core_experiment.py`. "
        "The core (`neo4d/core.py`: the loop, the search, verified memory and the RELATE v2 law) is the same file for "
        "every domain; each domain (`neo4d/domains/`) supplies only how to ask a model, read its answer, check, vary and "
        "abstract a candidate. Every method may use at most 4 model calls and 400 checker calls per task. Intervals: "
        "95% bootstrap over tasks of the per-task success rate averaged over seeds; p: a paired sign-flip permutation "
        "test. The 4D routers are not used: these domains give them nothing to route yet."]
    parts = [p for p in parts if not p.startswith(title)] + ["\n".join(out)[3:]]
    OUT.write_text("\n\n## ".join(p.strip("\n") for p in parts) + "\n")
    print("\n".join(out))


DESIGN_NOTES = {
    98: "The second design run, after these changes made because of the first (seed 99, recorded in "
        "`.build/core_runs.json` under `design|`, with 5 numbers and up to 6 blocks): phi4-mini solved nothing on its own in "
        "either domain - its Countdown answers miscalculated (it wrote `(50 - 1) * 7 + 25 - 9 = 83`; that is 359) and its "
        "plans moved bottom blocks first and then repeated themselves for dozens of lines - so there was no near-miss "
        "for neo4d to repair, and neo4d's search alone did as well (8 of 15 in each domain). Changes: Countdown with 4 "
        "numbers and targets up to 200, the answer asked for without its value; Blocks with 3-5 blocks, the top blocks "
        "named in the prompt, replies read up to three moves per block, and a checker that skips an illegal move and "
        "penalises it instead of stopping at it; a check budget of 100 per task as the main setting. Every method gets "
        "the same prompt and checker. Run 98 was interrupted; it also showed that the core searched only two changes deep "
        "around each model attempt while search alone searched four - an inconsistency, fixed (four for both) before it was "
        "run again. For time, Blocks replies are cut at 160 tokens (the 15 moves read at most need about 100); this "
        "changes no outcome, since longer replies were already cut to 15 moves.",
}


def main() -> int:
    args = sys.argv[1:]
    if "--design" in args:
        seed = int(args[args.index("--design") + 1]) if len(args) > args.index("--design") + 1 else 98
        doms, models, n = list(DOMAINS), ["phi4-mini"], 15
        done = experiment(doms, models, n, [seed], f"design{seed}")
        report(done, doms, models, n, [seed], f"design{seed}", f"Design run, seed {seed} (15 tasks; for debugging - not a result)",
               DESIGN_NOTES.get(seed, ""))
        return 0
    doms = (args[args.index("--domains") + 1] if "--domains" in args else ",".join(DOMAINS)).split(",")
    models = (args[args.index("--models") + 1] if "--models" in args else "phi4-mini").split(",")
    n = int(args[args.index("--tasks") + 1]) if "--tasks" in args else 60
    seeds = [int(s) for s in (args[args.index("--seeds") + 1] if "--seeds" in args else "1,2").split(",")]
    for checks in (100, 400):
        done = experiment(doms, models, n, seeds, "main", checks)
        report(done, doms, models, n, seeds, "main", f"Results, {checks} checks per task ({n} tasks per seed, seeds "
               f"{', '.join(map(str, seeds))})", "The configuration was frozen after the design runs; these seeds were "
               "not looked at before.", checks)
    return 0


if __name__ == "__main__":
    sys.exit(main())
