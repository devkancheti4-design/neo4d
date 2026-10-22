"""A local model with neo4d as its brain - does neo4d improve it?

THE TASKS. The 31 QuixBugs programs whose tests are JSON cases. Each correct program is broken on one line by the
mutation teacher (neo4d/domain_mutation.py); a broken program is a task only if its own tests catch it. The tasks
arrive as one stream, in a seeded order. A task is fixed when the program passes all its tests again.

THE SOLVERS, on the same stream:

    model alone        the local model sees the buggy function and one failing test, and writes the corrected line;
                       one attempt
    model + tests      the same, up to 3 attempts (later ones sampled), keeping the first that passes - the usual way
                       a model is used with tests
    neo4d + model      neo4d's memory first: its active patterns propose fixes, the tests check them, and a single
                       passing fix ships with no model call. Otherwise the model writes (as above). Every shipped fix
                       becomes a lesson: its literal edit and anchored relation are neurons, and the RELATE v2 law sets
                       their strength. The model reads and writes; neo4d and the tests decide.

    python -m neo4d.local_model [--model phi4-mini] [--per-program 6]   -> results/LOCAL_MODEL.md

THE COMPARISON. Claude answered the first 30 tasks of the same stream, from the same prompt the local model sees (one
answer each, no test feedback). --compare scores those answers and the local model on the same 30 tasks, and runs
neo4d with each of them as its writer.

    python -m neo4d.local_model --compare results/claude_answers.json   -> results/LOCAL_MODEL_VS_CLAUDE.md
"""
from __future__ import annotations

import ast
import copy
import difflib
import json
import multiprocessing as mp
import random
import re
import statistics
import sys
import time
import urllib.request
from collections import defaultdict
from pathlib import Path

from neo4d import KERNELS, REPO
from neo4d import domain_mutation as D
from neo4d import relate_live as RL
from neo4d import relations as R

QB = REPO / "bench" / "QuixBugs"
OLLAMA = "http://localhost:11434/api/generate"
PY_SPELL = {"TRUE": "True", "FALSE": "False", "NULL": "None", "AND": "and", "OR": "or", "NOT": "not"}
CTX = mp.get_context("fork")


# ------------------------------------------------------------------------------------------------- the oracle

def json_programs():
    out = {}
    for t in sorted((QB / "python_testcases").glob("test_*.py")):
        src = t.read_text()
        if "load_json_testcases" not in src:
            continue
        name = t.stem[5:]
        m = re.search(r"^\s+assert (.+)$", src, re.M)
        out[name] = m.group(1)
    return out


def _child(conn, src, expr, cases):
    try:
        ns = {}
        exec(compile(src, "<candidate>", "exec"), ns)
        tree = ast.parse(expr, mode="eval").body
        left = compile(ast.Expression(tree.left), "<l>", "eval")
        approx = "approx" in expr
        for inp, exp in cases:
            ns["input_data"], ns["expected"] = copy.deepcopy(inp), exp
            got = eval(left, ns)
            if approx:
                ok = abs(got - exp) <= inp[-1]
            else:
                ok = json.loads(json.dumps(got, default=list)) == exp
            if not ok:
                conn.send((False, inp, exp, repr(got)[:120]))
                return
        conn.send((True, None, None, None))
    except BaseException as e:                       # noqa: BLE001 - a broken candidate fails, whatever it raises
        conn.send((False, None, None, f"{type(e).__name__}: {e}"[:120]))


def run(src, expr, cases, timeout=2.0):
    """(passes, failing input, expected, got) - in a forked child, killed after `timeout` seconds."""
    a, b = CTX.Pipe(duplex=False)
    p = CTX.Process(target=_child, args=(b, src, expr, cases))
    p.start()
    p.join(timeout)
    if p.is_alive():
        p.kill()
        p.join()
        return False, None, None, "timed out"
    return a.recv() if a.poll() else (False, None, None, "crashed")


# -------------------------------------------------------------------------------------------------- the tasks

def code_lines(src):
    tree = ast.parse(src)
    drop = set()
    for n in ast.walk(tree):
        if isinstance(n, ast.Expr) and isinstance(n.value, ast.Constant) and isinstance(n.value.value, str):
            drop.update(range(n.lineno, n.end_lineno + 1))
    lines = src.split("\n")
    return [i for i, l in enumerate(lines) if (i + 1) not in drop and l.strip() and not l.strip().startswith("#")]


def spans(line):
    return [(R.canon(m.group(0)), m.start(), m.end()) for m in R.RF.TOK.finditer(line)]


def to_text(line, m_tokens):
    """Write a mutant token list back into the line's own text, touching only the changed span."""
    sp = spans(line)
    a = [t for t, _, _ in sp]
    m = [t for t in m_tokens if t != "^"]
    i = 0
    while i < min(len(a), len(m)) and a[i] == m[i]:
        i += 1
    j = 0
    while j < min(len(a), len(m)) - i and a[-1 - j] == m[-1 - j]:
        j += 1
    new = " ".join(PY_SPELL.get(t, t) for t in m[i:len(m) - j])
    if i < len(a) - j:
        start, end = sp[i][1], sp[len(a) - j - 1][2]
    else:
        start = end = sp[i][1] if i < len(sp) else len(line)
        new = new + " " if i < len(sp) else " " + new
    out = line[:start] + new + line[end:]
    return re.sub(r"(?<=\S)  +", " ", out) if not new else out


def make_tasks(per_program, seed):
    progs = json_programs()
    rng = random.Random(seed)
    tasks, kept = [], {}
    for name, expr in progs.items():
        src = (QB / "correct_python_programs" / f"{name}.py").read_text()
        cases = [json.loads(l) for l in (QB / "json_testcases" / f"{name}.json").read_text().splitlines() if l.strip()]
        good = [c for c in cases if run(src, expr, [c], 1.5)[0]]
        if len(good) < 2:
            continue
        kept[name] = (src, expr, good)
        lines = src.split("\n")
        cands = []
        for li in code_lines(src):
            for m in D.mutants(R.toks(lines[li])):
                cands.append((li, to_text(lines[li], list(m))))
        rng.shuffle(cands)
        n = 0
        for li, bad in cands:
            if n >= per_program or bad == lines[li]:
                continue
            buggy = "\n".join(lines[:li] + [bad] + lines[li + 1:])
            try:
                ast.parse(buggy)
            except SyntaxError:
                continue
            ok, inp, exp, got = run(buggy, expr, good)
            if not ok:
                tasks.append(dict(prog=name, line=li, bad=bad, good=lines[li], buggy=buggy, fail=(inp, exp, got)))
                n += 1
    rng.shuffle(tasks)
    for n, t in enumerate(tasks):
        t["id"] = n
    return tasks, kept


# -------------------------------------------------------------------------------------------------- the model

def prompt_of(task, kept):
    src, expr, good = kept[task["prog"]]
    lines = task["buggy"].split("\n")
    shown = "\n".join(lines[i] for i in code_lines(task["buggy"]))
    inp, exp, got = task["fail"]
    fn = re.search(r"([A-Za-z_]\w*)\(", expr).group(1)
    test = (f"Calling {fn}({', '.join(map(repr, inp))}) should return {exp!r}, but it returned {got}."
            if inp is not None else f"The tests fail: {got}.")
    prompt = ("This Python function has exactly one buggy line. " + test + "\n"
              "Reply with only the corrected line of code, exactly as it should appear in the file, and nothing else."
              f"\n\n```python\n{shown}\n```")
    return prompt


def ask_model(model, task, kept, temperature, seed):
    body = json.dumps({"model": model, "prompt": prompt_of(task, kept), "stream": False,
                       "options": {"temperature": temperature, "num_predict": 120, "seed": seed}}).encode()
    req = urllib.request.Request(OLLAMA, data=body, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=300) as r:
        reply = json.loads(r.read())["response"]
    return apply_reply(task["buggy"], reply)


def apply_reply(buggy, reply):
    """Place the model's corrected line over the program line it most resembles (keeping that line's indent)."""
    lines = buggy.split("\n")
    idx = code_lines(buggy)
    best = None
    for r in reply.split("\n"):
        r = r.strip().strip("`")
        if not r or r.lower() in ("python",):
            continue
        for i in idx:
            ratio = difflib.SequenceMatcher(None, r, lines[i].strip()).ratio()
            if ratio < 1.0 and (best is None or ratio > best[0]):
                best = (ratio, i, r)
    if best is None or best[0] < 0.5:
        return None
    _, i, r = best
    indent = lines[i][:len(lines[i]) - len(lines[i].lstrip())]
    return "\n".join(lines[:i] + [indent + r] + lines[i + 1:])


def model_writer(model, kept):
    return lambda task, temperature, seed: ask_model(model, task, kept, temperature, seed)


def answers_writer(answers):
    """Fixed answers, one per task id: the first attempt only."""
    return lambda task, temperature, seed: apply_reply(task["buggy"], answers[str(task["id"])]) if temperature == 0 else None


def model_fix(write, task, kept, attempts, stats):
    src, expr, good = kept[task["prog"]]
    for k in range(attempts):
        stats["model calls"] += 1
        prog = write(task, 0.0 if k == 0 else 0.8, 1000 + k)
        if prog is None:
            continue
        try:
            ast.parse(prog)
        except SyntaxError:
            continue
        stats["test runs"] += 1
        if run(prog, expr, good)[0]:
            return prog
    return None


# ------------------------------------------------------------------------------------------------ the brain

class Brain:
    """neo4d's memory of fixes: literal edits and anchored relations as neurons, the RELATE v2 law setting them."""

    def __init__(self, law):
        self.law = law
        self.level = defaultdict(int)
        self.nets = defaultdict(set)
        self.fires = defaultdict(int)
        self.good = defaultdict(int)
        self.cost = defaultdict(list)            # candidates per firing line, per task
        self.index = D.Index(())
        self.indexed = set()

    def active(self):
        return {k for k, v in self.level.items() if v >= 2}

    def propose(self, buggy):
        """{candidate program: [neurons that made it]} - every active pattern on every code line."""
        lines = buggy.split("\n")
        idx = D.Index(self.active())
        out = defaultdict(list)
        fired = defaultdict(int)
        for i in code_lines(buggy):
            a = ["^"] + R.toks(lines[i])
            x = {"a": a, "keys": set(a) | ({"$INT"} if any(R.is_int(t) for t in a) else set())
                 | ({"$ID"} if any(R.is_ident(t) for t in a) else set())}
            scope = lines[max(0, i - 3):i + 4]
            for k in idx.on(x):
                kind, (old, new) = k
                c = set(R.generate((old, new), a, scope, cap=200))
                c.discard(tuple(a))
                if c:
                    fired[k] += 1
                for m in c:
                    out["\n".join(lines[:i] + [to_text(lines[i], list(m))] + lines[i + 1:])].append(k)
        return out, fired

    def learn(self, task, fixed_prog, proposals, fired):
        lines_b, lines_f = task["buggy"].split("\n"), fixed_prog.split("\n")
        i = next((n for n in range(len(lines_b)) if lines_b[n] != lines_f[n]), None)
        if i is None:
            return
        a, m = ["^"] + R.toks(lines_b[i]), ["^"] + R.toks(lines_f[i])
        own = {k for k in D.neurons_of(a, tuple(m), lines_b[max(0, i - 3):i + 4]) if k[0] in ("lit", "ctx")}
        made_fix = set(proposals.get(fixed_prog, []))
        n_lines = max(1, len(code_lines(task["buggy"])))
        for k in own | set(fired):
            if fired.get(k):
                self.cost[k].append(len([p for p, ks in proposals.items() if k in ks]) / fired[k])
        for k in own | set(fired):
            L = self.level[k]
            if L >= 2 and fired.get(k):
                self.fires[k] += 1
                self.good[k] += k in made_fix
            fan = statistics.mean(self.cost[k]) if self.cost[k] else 1.0
            cheap, costly = fan <= RL.CHEAP[0], fan > RL.COSTLY[0] or fan * fired.get(k, 0) / n_lines > D.JUNK[1]
            FIRE = int(k in own)
            NEWNET = int(FIRE and task["prog"] not in self.nets[k])
            PRED = int(L >= 1 and k in made_fix)
            BAR = int(L >= 1 and self.fires[k] >= D.BARREN_FIRES and self.good[k] / self.fires[k] < RL.BARREN_YIELD)
            x = L | FIRE << 2 | NEWNET << 3 | PRED << 4 | int(cheap and not costly) << 5 | int(costly) << 6 | BAR << 7
            self.level[k] = self.law(x) & 3
            if FIRE:
                self.nets[k].add(task["prog"])


def brain_fix(brain, write, task, kept, stats, cap=60, attempts=3):
    src, expr, good = kept[task["prog"]]
    proposals, fired = brain.propose(task["buggy"])
    greens = []
    for prog in list(proposals)[:cap]:
        stats["test runs"] += 1
        if run(prog, expr, good)[0]:
            greens.append(prog)
    if len(greens) == 1:
        stats["fixed from memory"] += 1
        return greens[0], proposals, fired, "memory"
    prog = model_fix(write, task, kept, attempts, stats)
    return prog, proposals, fired, ("model" if prog else None)


# ---------------------------------------------------------------------------------------------------- report

def ceiling(tasks, kept):
    """Tasks a perfect writer - one that always replies with the original line - fixes through apply_reply."""
    n = 0
    for t in tasks:
        prog = apply_reply(t["buggy"], t["good"].strip())
        n += prog is not None and run(prog, kept[t["prog"]][1], kept[t["prog"]][2])[0]
    return n


CEILING = ("The ceiling: a writer that always replies with the exact original line fixes **{c} of {n}** through this "
           "harness. The rest are bugs like `return x` -> `return None`, where the corrected line looks more like another "
           "line of the function and is placed there instead - every writer here loses those.")


def solve(label, tasks, kept, law, write, attempts, with_brain):
    stats = defaultdict(int)
    brain = Brain(law)
    rows = []
    t1 = time.time()
    for n, task in enumerate(tasks):
        if with_brain:
            prog, proposals, fired, how = brain_fix(brain, write, task, kept, stats, attempts=attempts)
            if prog:
                brain.learn(task, prog, proposals, fired)
        else:
            prog = model_fix(write, task, kept, attempts, stats)
            how = "model" if prog else None
        exact = bool(prog) and prog.split("\n")[task["line"]].strip() == task["good"].strip()
        rows.append(dict(id=task["id"], fixed=bool(prog), exact=exact, how=how, calls=stats["model calls"]))
        if (n + 1) % 25 == 0:
            print(f"  {label}: {n + 1}/{len(tasks)} fixed {sum(r['fixed'] for r in rows)} "
                  f"calls {stats['model calls']}", flush=True)
    return rows, dict(stats), time.time() - t1, len(brain.active())


def compare(path, model, per, law):
    answers = json.loads(Path(path).read_text())
    tasks, kept = make_tasks(per, 2026)
    tasks = tasks[:len(answers)]
    n = len(tasks)
    mw, cw = model_writer(model, kept), answers_writer(answers)
    runs = [(f"{model} alone", mw, 1, False), (f"{model} + tests (3 tries)", mw, 3, False),
            (f"neo4d + {model}", mw, 3, True), ("Claude alone (one answer)", cw, 1, False), ("neo4d + Claude", cw, 1, True)]
    res = {label: solve(label, tasks, kept, law, w, a, b) for label, w, a, b in runs}
    out = [f"# {model} with neo4d, against Claude", "",
           f"Generated by `neo4d/local_model.py --compare`. The first **{n} tasks** of the same stream as "
           "[LOCAL_MODEL.md](LOCAL_MODEL.md). Claude answered each from the same prompt the local model sees - the buggy "
           "function and one failing test - with one corrected line, and never saw the test results. neo4d starts each run "
           "with an empty memory, so over these first tasks it has had little to learn from.", "",
           "| solver | **fixed** | the original line exactly | writer calls | fixed from neo4d's memory |",
           "|---|---|---|---|---|"]
    for label, (rows, stats, _, _) in res.items():
        f = sum(r["fixed"] for r in rows)
        out.append(f"| {label} | **{f / n:.0%}** ({f}/{n}) | {sum(r['exact'] for r in rows) / n:.0%} | "
                   f"{stats.get('model calls', 0)} | {stats.get('fixed from memory', 0)} |")
    out += ["", CEILING.format(c=ceiling(tasks, kept), n=n)]
    fixed = {label: {r["id"] for r in rows if r["fixed"]} for label, (rows, *_) in res.items()}
    c, m, b = fixed["Claude alone (one answer)"], fixed[f"{model} alone"], fixed[f"neo4d + {model}"]
    out += ["", f"Tasks Claude fixed that {model} alone did not: **{len(c - m)}**; of those, neo4d + {model} fixed "
            f"**{len(b & (c - m))}**. Tasks {model} alone fixed that Claude did not: {len(m - c)}.", "",
            "| task | program | " + " | ".join(res) + " |", "|---|---|" + "---|" * len(res)]
    for t in tasks:
        out.append(f"| {t['id']} | {t['prog']} | " + " | ".join(
            ("✓" if t["id"] in fixed[label] else "·") for label in res) + " |")
    (REPO / "results" / "LOCAL_MODEL_VS_CLAUDE.md").write_text("\n".join(out) + "\n")
    print("\n".join(out))
    return 0


def main() -> int:
    args = sys.argv[1:]
    model = args[args.index("--model") + 1] if "--model" in args else "phi4-mini"
    per = int(args[args.index("--per-program") + 1]) if "--per-program" in args else 6
    law = RL.load_law(str(KERNELS / "relate_v2.c"))
    if "--compare" in args:
        return compare(args[args.index("--compare") + 1], model, per, law)
    t0 = time.time()
    tasks, kept = make_tasks(per, 2026)
    print(f"  {len(tasks)} tasks from {len(kept)} programs ({time.time() - t0:.0f}s)", flush=True)
    mw = model_writer(model, kept)
    res = {label: solve(label, tasks, kept, law, mw, a, b)
           for label, a, b in (("model alone", 1, False), ("model + tests", 3, False), ("neo4d + model", 3, True))}
    n = len(tasks)
    half = n // 2
    out = ["# A local model with neo4d as its brain", "",
           f"Generated by `neo4d/local_model.py`. Local model: **{model}** (ollama, on this machine). **{n} bug-fix "
           f"tasks** from {len(kept)} QuixBugs programs: each a correct program broken on one line by the mutation "
           "teacher, kept only if its own tests catch it, in one seeded stream. Fixed: every test passes again. "
           "neo4d's patterns are decided by the RELATE v2 law; the model reads and writes, neo4d and the tests decide.",
           "", "| solver | **fixed** | the original line exactly | model calls | calls per task | test runs | time |",
           "|---|---|---|---|---|---|---|"]
    for label, (rows, stats, secs, _) in res.items():
        f = sum(r["fixed"] for r in rows)
        e = sum(r["exact"] for r in rows)
        out.append(f"| {label} | **{f / n:.1%}** ({f}) | {e / n:.1%} | {stats.get('model calls', 0)} | "
                   f"{stats.get('model calls', 0) / n:.2f} | {stats.get('test runs', 0)} | {secs:.0f}s |")
    out += ["", CEILING.format(c=ceiling(tasks, kept), n=n)]
    rows, stats, secs, n_active = res["neo4d + model"]
    mem = [r for r in rows if r["how"] == "memory"]
    c1 = rows[half - 1]["calls"]
    c2 = rows[-1]["calls"] - c1
    m1 = sum(r["how"] == "memory" for r in rows[:half])
    m2 = sum(r["how"] == "memory" for r in rows[half:])
    out += ["", "## neo4d as it learns", "",
            "| | first half of the stream | second half |", "|---|---|---|",
            f"| fixed from neo4d's memory, no model call | {m1 / half:.1%} | **{m2 / (n - half):.1%}** |",
            f"| model calls | {c1} | **{c2}** |",
            f"| fixed (memory or model) | {sum(r['fixed'] for r in rows[:half]) / half:.1%} | "
            f"{sum(r['fixed'] for r in rows[half:]) / (n - half):.1%} |", "",
            f"Fixes from memory: {len(mem)}, of which {sum(r['exact'] for r in mem)} restore the original line exactly. "
            f"Active patterns at the end: {n_active}.", "",
            "**What this does not show.** The bugs are injected by the mutation teacher, so the stream is rich in "
            "repeats - a closed domain, where memory helps most. A fix that passes the tests but differs from the "
            "original line is counted as fixed; the tests are the judge, as they are for every solver here."]
    (REPO / "results" / "LOCAL_MODEL.md").write_text("\n".join(out) + "\n")
    print("\n".join(out))
    return 0


if __name__ == "__main__":
    sys.exit(main())
