"""ARC on neo4d's core: the small model proposes, neo4d's search mutates programs, the training pairs check them, and
each task's hidden test output scores what is submitted.

    methods   grid      the model writes the test output grid directly - the usual way a language model is run on ARC
              program   the model writes a program (sample-and-filter: up to 4 tries, the first that fits every training
                        pair; else its first program)
              core      neo4d: memory first, then up to 4 model programs, each searched around by neo4d
              search    neo4d's search alone, from the empty program, no model
    budget    4 model calls and CHECKS checker calls per task, for every method that uses them
    scored    the hidden test output(s) of each task; a "false fit" reproduces every training pair but not the test

    python -m neo4d.arc_experiment --search training,evaluation          (no model; every task)
    python -m neo4d.arc_experiment --models phi4-mini --tasks 40         (a seeded sample of the evaluation set)
"""
from __future__ import annotations

import json
import random
import re
import statistics
import sys
import time
from collections import defaultdict

from neo4d import KERNELS, REPO
from neo4d import core as C
from neo4d import relate_live as RL
from neo4d.domains.arc import Arc, grid_text, load

CHECKS = 2000
STORE = REPO / ".build" / "arc_runs.json"
OUT = REPO / "results" / "ARC.md"


def grid_method(dom, task, model, seed):
    stats = defaultdict(int)
    pairs = "\n\n".join(f"Example {k + 1} input:\n{grid_text(i)}\nExample {k + 1} output:\n{grid_text(o)}"
                        for k, (i, o) in enumerate(task["train"]))
    ok = True
    for ti, to in task["test"]:
        reply = C.generate(model, f"Each example turns an input grid (digits are colours) into an output grid by the same "
                           f"rule.\n\n{pairs}\n\nTest input:\n{grid_text(ti)}\n\nReply with only the test output grid, one "
                           "row of digits per line.", 0.0, seed, stats, predict=1200)
        rows = [tuple(int(c) for c in l.strip()) for l in (reply or "").split("\n") if re.fullmatch(r"\s*\d+\s*", l)]
        ok = ok and tuple(rows) == to
    return dict(id=task["id"], test=ok, fit=None, calls=stats["calls"], checks=0, how="model" if ok else None)


def run_method(dom, tasks, model, method, seed, law):
    rows = []
    mem = C.Memory(law) if method == "core" else None
    for t in tasks:
        if method == "grid":
            rows.append(grid_method(dom, t, model, seed))
            continue
        m = {"program": "sample"}.get(method, method)
        r = C.solve(dom, t, model, m, mem, calls=4, checks=CHECKS, seed=seed)
        prog = r["solution"] if r["solution"] is not None else r.get("first")
        rows.append(dict(id=t["id"], test=dom.solves_test(t, prog), fit=r["solved"], calls=r["calls"], checks=r["checks"],
                         how=r["how"]))
    return rows


def table(rows_by_method, n):
    out = ["| method | solved (hidden test) | fits every training pair | false fits | model calls per task | checks per task |",
           "|---|---|---|---|---|---|"]
    for m, rows in rows_by_method.items():
        solved = sum(r["test"] for r in rows)
        fit = sum(bool(r["fit"]) for r in rows) if rows and rows[0]["fit"] is not None else None
        false = sum(bool(r["fit"]) and not r["test"] for r in rows) if fit is not None else None
        out.append(f"| {'**' + m + '**' if m == 'core' else m} | **{solved}/{n}** ({solved / n:.1%}) | "
                   f"{'-' if fit is None else fit} | {'-' if false is None else false} | "
                   f"{statistics.mean(r['calls'] for r in rows):.2f} | {statistics.mean(r['checks'] for r in rows):.0f} |")
    return out


def main() -> int:
    args = sys.argv[1:]
    law = RL.load_law(str(KERNELS / "relate_v2.c"))
    dom = Arc()
    done = json.loads(STORE.read_text()) if STORE.exists() else {}
    sections = []
    if "--search" in args:
        for split in args[args.index("--search") + 1].split(","):
            key = f"search|{split}|{CHECKS}"
            if key not in done:
                t0 = time.time()
                done[key] = run_method(dom, load(split), None, "search", 0, law)
                STORE.write_text(json.dumps(done))
                print(f"  search {split}: {sum(r['test'] for r in done[key])}/{len(done[key])} ({time.time() - t0:.0f}s)", flush=True)
            n = len(done[key])
            sections.append((f"neo4d's search alone, no model - ARC {split} ({n} tasks)",
                             [f"Every task of the {split} set; search from the empty program, at most {CHECKS} checker "
                              "calls (each runs a program on the training pairs).", ""] + table({"search": done[key]}, n)))
    if "--models" in args:
        models = args[args.index("--models") + 1].split(",")
        k = int(args[args.index("--tasks") + 1]) if "--tasks" in args else 40
        tasks = random.Random(2026).sample(load("evaluation"), k)
        for model in models:
            by = {}
            for method in ("grid", "program", "core", "search"):
                key = f"{method}|{model if method != 'search' else '-'}|eval{k}|{CHECKS}"
                if key not in done:
                    t0 = time.time()
                    done[key] = run_method(dom, tasks, model, method, 0, law)
                    STORE.write_text(json.dumps(done))
                    print(f"  {model} {method}: {sum(r['test'] for r in done[key])}/{k} ({time.time() - t0:.0f}s)", flush=True)
                by[method] = done[key]
            sections.append((f"A small model with and without neo4d - {model}, {k} evaluation tasks",
                             [f"A seeded sample of {k} tasks of the evaluation set. 4 model calls per task at most; "
                              f"{CHECKS} checker calls for the methods that search.", ""] + table(by, k)))
    parts = OUT.read_text().rstrip("\n").split("\n## ") if OUT.exists() else [
        "# ARC on neo4d's core\n\nGenerated by `neo4d/arc_experiment.py`. ARC-AGI (the original corpus: 400 training and 400 "
        "evaluation tasks). The same domain-free core as `results/CORE.md`; the ARC adapter (`neo4d/domains/arc.py`) "
        "supplies a small set of grid operations, programs of at most 3 steps, and a checker that runs a program on a "
        "task's training pairs. Every task is scored on its hidden test output, which no solver sees."]
    for title, body in sections:
        parts = [x for x in parts if not x.startswith(title)] + ["\n".join([title, ""] + body)]
    OUT.write_text("\n\n## ".join(x.strip("\n") for x in parts) + "\n")
    print("\n".join("\n".join([t, ""] + b) for t, b in sections))
    return 0


if __name__ == "__main__":
    sys.exit(main())
