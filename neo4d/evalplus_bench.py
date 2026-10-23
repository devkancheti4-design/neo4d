"""HumanEval+ and MBPP+ (EvalPlus): a small model writes the function; does neo4d's mutation make it right more often?

FAIRNESS. A solver - and neo4d - may check a candidate only against what a solver is shown: the examples in a HumanEval
docstring (`>>> f(3.5)` / `0.5`, or `f(x) == y` lines) and the assert in an MBPP+ prompt. Scoring uses EvalPlus's hidden
inputs (base + plus, often hundreds per problem) with the reference solution's outputs, which no solver ever sees. A
problem with no visible example gets no search: every method falls back to the model's own answer there.

THE METHODS, each at most 5 model calls per problem; each submits the first candidate that passes the visible examples,
else the model's first (greedy) answer
    alone       one try
    sample      up to 5 independent tries (sample-and-filter)
    debug       up to 5 tries, each told which visible example failed and what it returned (self-debugging)
    neo4d       up to 5 tries; after each failing try neo4d mutates it (every single-token change on its code lines)
                and ships the first variant that passes the visible examples; otherwise the model hears what the best
                variant did

Reported: solved on the hidden tests; candidates that passed the visible examples but failed the hidden ones (false
fixes); fixes shipped by neo4d's mutation; model calls.

    python -m neo4d.evalplus_bench --design                                    (10 problems each, debugging)
    python -m neo4d.evalplus_bench --models phi4-mini,gemma3:4b --mbpp 200 --seeds 0   -> results/EVALPLUS.md
"""
from __future__ import annotations

import ast
import copy
import pickle
import doctest
import gzip
import io
import json
import math
import random
import re
import statistics
import sys
import time
from collections import defaultdict

from neo4d import REPO
from neo4d import core as C
from neo4d import domain_mutation as D
from neo4d import local_model as LM
from neo4d import relations as R
from neo4d.rigor import bootstrap, permutation_p

BENCH = REPO / "bench" / "evalplus"
STORE = REPO / ".build" / "evalplus_runs.json"
EXPECT = REPO / ".build" / "evalplus_expected.pkl"
OUT = REPO / "results" / "EVALPLUS.md"
CALLS, VARIANTS = 5, 150
METHODS = ("alone", "sample", "debug", "neo4d")


# ------------------------------------------------------------------------------------------------- the problems

def literal_call(src):
    """An example is usable only if it is one call with literal arguments (`is_happy(a)` - `a` meaning a letter - is not)."""
    try:
        node = ast.parse(src, mode="eval").body
        if not isinstance(node, ast.Call):
            return False
        for a in list(node.args) + [k.value for k in node.keywords]:
            ast.literal_eval(a)
        return True
    except (ValueError, SyntaxError, TypeError, MemoryError, RecursionError):
        return False


def visible_humaneval(prompt, entry):
    """The docstring's examples: doctest lines, then `f(...) == / -> / => / ➞ value` lines. -> [(call source, value)]"""
    out = []
    for ex in doctest.DocTestParser().get_examples(prompt):
        # a docstring's closing quotes right under an example are read by doctest as part of its output: drop them
        want = "\n".join(l for l in ex.want.split("\n") if l.strip() not in ('"""', "'''")).strip()
        try:
            if literal_call(ex.source.strip()):
                out.append((ex.source.strip(), ast.literal_eval(want)))
        except (ValueError, SyntaxError, TypeError, MemoryError, RecursionError):
            pass
    if out:
        return out
    for m in re.finditer(rf"({re.escape(entry)}\(.*?\))\s*(?:==|->|=>|➞|should return|returns?)\s*(.+)", prompt):
        try:
            if literal_call(m.group(1)):
                out.append((m.group(1), ast.literal_eval(m.group(2).strip().rstrip(".,"))))
        except (ValueError, SyntaxError, TypeError, MemoryError, RecursionError):
            pass
    return out


def visible_mbpp(prompt):
    """The prompt's asserts, kept as whole statements."""
    return [l.strip() for l in prompt.split("\n") if l.strip().startswith("assert ")]


def problems(name, sample=None, seed=2026):
    f = BENCH / ("HumanEvalPlus.jsonl.gz" if name == "humaneval" else "MbppPlus.jsonl.gz")
    rows = [json.loads(l) for l in gzip.open(f, "rt")]
    out = []
    for r in rows:
        if name == "humaneval":
            vis = [("ex", s, v) for s, v in visible_humaneval(r["prompt"], r["entry_point"])]
        else:
            vis = [("assert", a, None) for a in visible_mbpp(r["prompt"])]
        out.append(dict(id=r["task_id"], bench=name, prompt=r["prompt"], entry=r["entry_point"], visible=vis,
                        inputs=r["base_input"] + (r["plus_input"] if isinstance(r["plus_input"], list) else []), atol=r["atol"] or 0, reference=r["canonical_solution"]))
    if sample and sample < len(out):
        out = random.Random(seed).sample(out, sample)
        out.sort(key=lambda p: p["id"])
    return out


def full_source(p, code):
    """A candidate as a module: the prompt's imports, and the prompt itself if the model wrote only the body."""
    imports = "\n".join(l for l in p["prompt"].split("\n") if l.startswith(("import ", "from ")))
    if re.search(rf"def\s+{re.escape(p['entry'])}\s*\(", code):
        return (imports + "\n" + code).strip() + "\n"
    if p["bench"] == "humaneval":
        return p["prompt"] + code
    return code


# -------------------------------------------------------------------------------------------------- running code

def _child(conn, src, entry, calls, mode):
    sys.stdout = io.StringIO()
    out = []
    try:
        ns = {}
        exec(compile(src, "<candidate>", "exec"), ns)
        for c in calls:
            try:
                if mode == "inputs":
                    out.append(("ok", portable(ns[entry](*copy.deepcopy(c)))))
                elif mode == "ex":
                    out.append(("ok", portable(eval(c, ns))))
                else:
                    exec(c, ns)
                    out.append(("ok", None))
            except BaseException as e:                      # noqa: BLE001
                out.append(("err", f"{type(e).__name__}: {e}"[:120]))
    except BaseException as e:                              # noqa: BLE001
        out = [("err", f"{type(e).__name__}: {e}"[:120])] * len(calls)
    conn.send(out)


class Unpicklable(str):
    """An output that cannot cross the process boundary: compared by its text."""


def portable(v):
    try:
        pickle.dumps(v)
        return v
    except Exception:                                       # noqa: BLE001
        return Unpicklable(repr(v)[:2000])


def run(src, entry, calls, mode, timeout):
    a, b = LM.CTX.Pipe(duplex=False)
    pr = LM.CTX.Process(target=_child, args=(b, src, entry, calls, mode))
    pr.start()
    b.close()
    # read while the child runs: a large result fills the pipe, and a child blocked on send never finishes
    if a.poll(timeout):
        try:
            res = a.recv()
        except EOFError:
            res = [("err", "crashed")] * len(calls)
    else:
        res = [("err", "timed out")] * len(calls)
    if pr.is_alive():
        pr.kill()
    pr.join()
    return res


def equal(g, w, atol):
    """As EvalPlus compares: Python equality, floats within the problem's tolerance (elementwise in sequences)."""
    if atol and isinstance(g, float) and isinstance(w, (int, float)) and not isinstance(w, bool):
        return math.isclose(g, w, abs_tol=atol, rel_tol=0)
    if atol and type(g) is type(w) and isinstance(g, (list, tuple)) and len(g) == len(w):
        return all(equal(x, y, atol) for x, y in zip(g, w))
    try:
        return bool(g == w)
    except Exception:                                       # noqa: BLE001
        return False


def same(got, want, atol):
    return got[0] == "ok" and want[0] == "ok" and equal(got[1], want[1], atol)


def expected(p, cache):
    """The reference solution's outputs on the hidden inputs (computed once, cached)."""
    if p["id"] not in cache:
        src = full_source(p, p["prompt"] + p["reference"]) if p["bench"] == "humaneval" else p["reference"]
        t = time.time()
        res = run(src, p["entry"], p["inputs"], "inputs", 120)
        cache[p["id"]] = dict(out=res, secs=time.time() - t)
    return cache[p["id"]]


def hidden_pass(p, src, cache):
    exp = expected(p, cache)
    got = run(src, p["entry"], p["inputs"], "inputs", max(10.0, 20 * exp["secs"]))
    return all(same(g, w, p["atol"]) for g, w in zip(got, exp["out"]))


def visible_check(p, src):
    """-> (passes every visible example, a note on the first failure, partial score)"""
    if not p["visible"]:
        return None, "no visible example", 0.0
    if p["bench"] == "humaneval":
        res = run(src, p["entry"], [s for _, s, _ in p["visible"]], "ex", 5)
        ok = [r[0] == "ok" and equal(r[1], v, p["atol"] or 1e-6) for r, (_, _, v) in zip(res, p["visible"])]
        bad = next((i for i, o in enumerate(ok) if not o), None)
        note = "" if bad is None else (f"{p['visible'][bad][1]} returned {res[bad][1]!r}, expected {p['visible'][bad][2]!r}")
    else:
        res = run(src, p["entry"], [s for _, s, _ in p["visible"]], "assert", 5)
        ok = [r[0] == "ok" for r in res]
        bad = next((i for i, o in enumerate(ok) if not o), None)
        note = "" if bad is None else f"`{p['visible'][bad][1]}` fails: {res[bad][1]}"
    return all(ok), note, sum(ok) / len(ok)


# -------------------------------------------------------------------------------------------------- the solvers

def ask(model, p, feedback, temperature, seed, stats):
    if p["bench"] == "humaneval":
        q = ("Complete the following Python function. Reply with the complete function, including its def line, in one "
             f"```python code block.\n\n```python\n{p['prompt']}```")
    else:
        q = (f"{p['prompt'].strip().strip(chr(34)).strip()}\n\nWrite the Python function. Reply with the complete code in "
             "one ```python code block.")
    if feedback:
        q += f"\n\n{feedback}"
    reply = C.generate(model, q, temperature, seed, stats, predict=700)
    m = re.findall(r"```(?:python)?\n(.*?)```", reply or "", re.S)
    code = max(m, key=len) if m else (reply or "")
    return full_source(p, code)


def mutate(p, src):
    """neo4d: every single-token change on the candidate's code lines; the first that passes the visible examples."""
    lines = src.split("\n")
    try:
        code = LM.code_lines(src)
    except SyntaxError:
        return None, 0
    tried = 0
    for li in code:
        for m in D.mutants(R.toks(lines[li])):
            new = LM.to_text(lines[li], list(m))
            if new == lines[li]:
                continue
            var = "\n".join(lines[:li] + [new] + lines[li + 1:])
            try:
                ast.parse(var)
            except SyntaxError:
                continue
            tried += 1
            if visible_check(p, var)[0]:
                return var, tried
            if tried >= VARIANTS:
                return None, tried
    return None, tried


def solve(p, model, method, seed):
    stats = defaultdict(int)
    first, submit, how, tried = None, None, None, 0
    feedback = None
    n = 1 if method == "alone" else CALLS
    for k in range(n):
        src = ask(model, p, feedback if method in ("debug", "neo4d") else None, 0.0 if k == 0 else 0.8, seed * 1000 + k, stats)
        first = first or src
        ok, note, _ = visible_check(p, src)
        if ok is None:                                       # nothing visible to check against: keep the first answer
            break
        if ok:
            submit, how = src, "model"
            break
        if method == "neo4d":
            var, t = mutate(p, src)
            tried += t
            if var is not None:
                submit, how = var, "neo4d"
                break
            feedback = (f"Your function fails a given example: {note}. neo4d tried {t} single-token changes to it; none "
                        "passes every example. Write a corrected version.")
        elif method == "debug":
            feedback = f"Your function fails a given example: {note}. Write a corrected version."
    submit = submit or first
    return dict(id=p["id"], how=how, calls=stats["calls"], variants=tried,
                visible=bool(visible_check(p, submit)[0]), src=submit)


def experiment(benches, models, seeds, mbpp_sample, tag, limit=None):
    done = json.loads(STORE.read_text()) if STORE.exists() else {}
    cache = pickle.loads(EXPECT.read_bytes()) if EXPECT.exists() else {}
    t0 = time.time()
    for b in benches:
        ps = problems(b, mbpp_sample if b == "mbpp" else None)
        if limit:
            ps = ps[:limit]
        for p in ps:
            expected(p, cache)
        EXPECT.write_bytes(pickle.dumps(cache))
        print(f"  {b}: {len(ps)} problems, {sum(bool(p['visible']) for p in ps)} with visible examples, references run "
              f"({time.time() - t0:.0f}s)", flush=True)
        for seed in seeds:
            for model in models:
                for method in METHODS:
                    key = f"{tag}|{b}|{model}|{seed}|{method}"
                    if key in done:
                        continue
                    rows = []
                    for p in ps:
                        r = solve(p, model, method, seed)
                        r["hidden"] = hidden_pass(p, r.pop("src"), cache)
                        rows.append(r)
                    done[key] = rows
                    STORE.write_text(json.dumps(done))
                    print(f"  {tag} {b} {model} seed {seed} {method}: {sum(r['hidden'] for r in rows)}/{len(rows)} "
                          f"(neo4d fixes {sum(r['how'] == 'neo4d' for r in rows)}, false fixes "
                          f"{sum(r['visible'] and not r['hidden'] for r in rows)}, calls {sum(r['calls'] for r in rows)}) "
                          f"({time.time() - t0:.0f}s)", flush=True)
    return done


def report(done, benches, models, seeds, tag, title):
    out = [f"## {title}", ""]
    for b in benches:
        for model in models:
            runs = {m: [done.get(f"{tag}|{b}|{model}|{s}|{m}") for s in seeds] for m in METHODS}
            runs = {m: r for m, r in runs.items() if all(r)}
            if not runs:
                continue
            n = len(next(iter(runs.values()))[0])
            out += [f"### {'HumanEval+' if b == 'humaneval' else 'MBPP+'}, {model} ({n} problems)", "",
                    "| method | solved on the hidden tests (per seed) | mean | 95% interval | false fixes | fixed by neo4d's mutation (all / right on hidden tests) | model calls per problem |",
                    "|---|---|---|---|---|---|---|"]
            rate = {}
            for m, rs in runs.items():
                per = [sum(r["hidden"] for r in x) for x in rs]
                rate[m] = [statistics.mean(x[i]["hidden"] for x in rs) for i in range(n)]
                lo, hi = bootstrap(rate[m])
                false = statistics.mean(sum(r["visible"] and not r["hidden"] for r in x) for x in rs)
                nf = statistics.mean(sum(r["how"] == "neo4d" for r in x) for x in rs)
                nf_ok = statistics.mean(sum(r["how"] == "neo4d" and r["hidden"] for r in x) for x in rs)
                out.append(f"| {'**neo4d**' if m == 'neo4d' else m} | {', '.join(map(str, per))} | {statistics.mean(per):.1f} "
                           f"({statistics.mean(per) / n:.1%}) | {lo:.0%}-{hi:.0%} | {false:.1f} | "
                           f"{f'{nf:.1f} / {nf_ok:.1f}' if m == 'neo4d' else '-'} | "
                           f"{statistics.mean(r['calls'] for x in rs for r in x):.2f} |")
            if "neo4d" in rate:
                out.append("")
                for m in ("alone", "sample", "debug"):
                    if m in rate:
                        d = [a - c for a, c in zip(rate["neo4d"], rate[m])]
                        out.append(f"neo4d against {m}: {statistics.mean(d) * n:+.1f} problems, paired permutation "
                                   f"p = {permutation_p(d):.3f}.  ")
            out.append("")
    parts = OUT.read_text().rstrip("\n").split("\n## ") if OUT.exists() else [
        "# HumanEval+ and MBPP+: does neo4d's mutation make a small model's code right?\n\nGenerated by "
        "`neo4d/evalplus_bench.py`. EvalPlus's HumanEval+ (164 problems) and MBPP+ (378) - the original problems with "
        "far more hidden tests. Solvers - and neo4d - check only against what the problem shows (HumanEval's docstring "
        "examples; MBPP+'s prompt assert); scoring uses the hidden inputs with the reference solution's outputs. Every "
        "method may use 5 model calls per problem and submits the first candidate that passes the visible examples, "
        "else the model's first answer. A *false fix* passes the visible examples but fails the hidden tests."]
    parts = [x for x in parts if not x.startswith(title)] + ["\n".join(out)[3:]]
    OUT.write_text("\n\n## ".join(x.strip("\n") for x in parts) + "\n")
    print("\n".join(out))


def main() -> int:
    args = sys.argv[1:]
    if "--design" in args:
        done = experiment(["humaneval", "mbpp"], ["phi4-mini"], [0], 200, "design", limit=10)
        report(done, ["humaneval", "mbpp"], ["phi4-mini"], [0], "design", "Design run (10 problems each; debugging - not a result)")
        return 0
    models = (args[args.index("--models") + 1] if "--models" in args else "phi4-mini").split(",")
    seeds = [int(s) for s in (args[args.index("--seeds") + 1] if "--seeds" in args else "0").split(",")]
    mb = int(args[args.index("--mbpp") + 1]) if "--mbpp" in args else 200
    benches = (args[args.index("--benches") + 1] if "--benches" in args else "humaneval,mbpp").split(",")
    done = experiment(benches, models, seeds, mb, "main")
    report(done, benches, models, seeds, "main", f"Results (seeds {', '.join(map(str, seeds))}; MBPP+: a seeded sample of {mb})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
