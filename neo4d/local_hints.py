"""Bugs a small model has never solved: neo4d mutates the code, runs the tests, and gives the model what it found.

neo4d cannot reason, but it can experiment. On a broken program it tries every single-token change its mutation
operators know (the domain teacher's), runs the tests on each, and reports: which changes make failing tests pass,
which lines move the failing tests at all, what the closest near-fixes are. The model gets that evidence with the bug,
in its prompt - nothing is trained - and writes the fix.

THE BUGS. The real QuixBugs bugs (written by people, not by our operators): the 31 programs whose tests are JSON
cases, each with its buggy version and the tests that the correct version passes. A bug that neo4d's mutations fix on
their own is counted for neo4d and set apart; the test that matters is on the rest.

THE SOLVERS, each allowed at most 3 model calls a bug except the one-try ones
    model alone                  the buggy program and its first failing test; writes the corrected program, one try
    model + tests                up to 3 tries (later ones sampled), the first that passes
    model + neo4d's data         the same prompt plus neo4d's evidence, one try
    model + neo4d's data + tests up to 3 tries
    exchange                     a continual exchange, up to 3 rounds: the model gives a candidate - data and a direction,
                                 even when wrong; neo4d mutates the candidate (every single-token change it knows), runs
                                 the tests on each and ships any variant that passes; otherwise it reports back what the
                                 candidate and its best variants pass and what still fails, and the model goes again

    python -m neo4d.local_hints [--models phi4-mini,qwen3.5:4b,gemma3:4b]   -> results/LOCAL_HINTS.md
"""
from __future__ import annotations

import ast
import copy
import difflib
import io
import json
import re
import sys
import time
import urllib.error
import urllib.request
from collections import defaultdict

from neo4d import REPO
from neo4d import domain_mutation as D
from neo4d import relations as R
from neo4d import local_model as LM

ATTEMPTS = 3


# --------------------------------------------------------------------------------------------- running the tests

def _child_all(conn, src, expr, cases):
    """Every case, pass or fail, and what the program returned."""
    sys.stdout = io.StringIO()                               # a candidate's own prints are not the result
    try:
        ns = {}
        exec(compile(src, "<candidate>", "exec"), ns)
        tree = ast.parse(expr, mode="eval").body
        left = compile(ast.Expression(tree.left), "<l>", "eval")
        approx = "approx" in expr
        out = []
        for inp, exp in cases:
            ns["input_data"], ns["expected"] = copy.deepcopy(inp), exp
            try:
                got = eval(left, ns)
                ok = abs(got - exp) <= inp[-1] if approx else json.loads(json.dumps(got, default=list)) == exp
                out.append((bool(ok), repr(got)[:80]))
            except BaseException as e:                       # noqa: BLE001 - a case that raises fails
                out.append((False, f"{type(e).__name__}"))
        conn.send(out)
    except BaseException as e:                               # noqa: BLE001
        conn.send([(False, f"{type(e).__name__}")] * len(cases))


def run_all(src, expr, cases, timeout=3.0):
    a, b = LM.CTX.Pipe(duplex=False)
    p = LM.CTX.Process(target=_child_all, args=(b, src, expr, cases))
    p.start()
    p.join(timeout)
    if p.is_alive():
        p.kill()
        p.join()
        return [(False, "timed out")] * len(cases)
    return a.recv() if a.poll() else [(False, "crashed")] * len(cases)


# ---------------------------------------------------------------------------------------------------- the bugs

def bugs():
    out = []
    for name, expr in LM.json_programs().items():
        good_src = (LM.QB / "correct_python_programs" / f"{name}.py").read_text()
        bad_src = (LM.QB / "python_programs" / f"{name}.py").read_text()
        cases = [json.loads(l) for l in (LM.QB / "json_testcases" / f"{name}.json").read_text().splitlines() if l.strip()]
        good = [c for c in cases if LM.run(good_src, expr, [c], 1.5)[0]]
        if len(good) < 2:
            continue
        res = run_all(bad_src, expr, good)
        if all(ok for ok, _ in res):
            continue
        out.append(dict(name=name, expr=expr, src=bad_src, cases=good, base=res))
    return out


# ------------------------------------------------------------------------------------------------ neo4d's data

def mutate(bug):
    """Every single-token change neo4d's operators make, run against the tests."""
    lines = bug["src"].split("\n")
    fail = [i for i, (ok, _) in enumerate(bug["base"]) if not ok]
    seen, found = set(), []
    for li in LM.code_lines(bug["src"]):
        for m in D.mutants(R.toks(lines[li])):
            new = LM.to_text(lines[li], list(m))
            if new == lines[li] or (li, new) in seen:
                continue
            seen.add((li, new))
            prog = "\n".join(lines[:li] + [new] + lines[li + 1:])
            try:
                ast.parse(prog)
            except SyntaxError:
                continue
            res = run_all(prog, bug["expr"], bug["cases"])
            fixed = sum(res[i][0] for i in fail)
            broken = sum(not res[i][0] for i in range(len(res)) if i not in fail)
            moved = sum(res[i][1] != bug["base"][i][1] for i in fail)
            found.append(dict(line=li, old=lines[li].strip(), new=new.strip(), prog=prog, fixed=fixed, broken=broken,
                              moved=moved, all=all(ok for ok, _ in res)))
    return found, len(fail)


def evidence(bug, found, n_fail):
    """What neo4d tells the model: near-fixes, and which lines move the failing tests."""
    out = [f"neo4d tried {len(found)} single-token changes to this code and ran the tests on each "
           f"({n_fail} of {len(bug['cases'])} tests fail now)."]
    near = sorted((f for f in found if f["fixed"]), key=lambda f: (-(f["fixed"] - f["broken"]), -f["fixed"], f["line"]))
    if near:
        out.append("Changes that make failing tests pass:")
        for f in near[:4]:
            out.append(f"- line {f['line'] + 1}: `{f['old']}` -> `{f['new']}` makes {f['fixed']} of the {n_fail} failing "
                       f"tests pass (and breaks {f['broken']} passing test{'s' if f['broken'] != 1 else ''})")
    else:
        out.append("No single-token change makes any failing test pass, so the fix is probably not one token.")
    by_line = defaultdict(int)
    for f in found:
        by_line[f["line"]] += f["moved"]
    hot = [li for li, v in sorted(by_line.items(), key=lambda kv: -kv[1]) if v][:3]
    lines = bug["src"].split("\n")
    if hot:
        out.append("Lines where changes alter the failing tests' results most: "
                   + "; ".join(f"line {li + 1} `{lines[li].strip()}`" for li in hot) + ".")
    return "\n".join(out)


# -------------------------------------------------------------------------------------------------- the model

def first_failure(bug):
    i = next(i for i, (ok, _) in enumerate(bug["base"]) if not ok)
    inp, exp = bug["cases"][i]
    fn = re.search(r"([A-Za-z_]\w*)\(", bug["expr"]).group(1)
    return f"Calling {fn}({', '.join(map(repr, inp))}) should return {exp!r}, but it returned {bug['base'][i][1]}."


def suspects(bug, k=2):
    """The lines neo4d's mutations point to, read from its evidence: near-fix lines first, then the lines that move the
    failing tests most."""
    out = []
    for m in re.finditer(r"line (\d+)", bug["data"]):
        li = int(m.group(1)) - 1
        if li not in out:
            out.append(li)
    return out[:k]


MARK = "# <-- neo4d: changing this line changes the failing tests"


def ask(model, bug, data, temperature, seed, stats, last=None, marks=()):
    numbered = "\n".join(f"{n + 1:3d}  {l}" + (f"    {MARK}" if n in marks else "")
                          for n, l in enumerate(bug["src"].split("\n")))
    prompt = (f"This Python program has a bug. {first_failure(bug)}\n\n```\n{numbered}\n```\n\n"
              + (f"{data}\n\n" if data else "")
              + (f"Your previous attempt:\n```python\n{last[0]}\n```\n{last[1]}\n\n" if last else "")
              + "Reply with the complete corrected program (without line numbers) in one ```python code block.")
    body = json.dumps({"model": model, "prompt": prompt, "stream": False,
                       "options": {"temperature": temperature, "seed": seed, "num_predict": 900, "num_ctx": 8192}}).encode()
    stats["calls"] += 1
    for wait in (2, 5, 10, None):
        try:
            req = urllib.request.Request(LM.OLLAMA, data=body, headers={"Content-Type": "application/json"})
            with urllib.request.urlopen(req, timeout=600) as r:
                reply = json.loads(r.read())["response"]
            break
        except (urllib.error.URLError, TimeoutError, ConnectionError):
            if wait is None:
                return None
            time.sleep(wait)
    m = re.findall(r"```(?:python)?\n(.*?)```", reply, re.S)
    return max(m, key=len) if m else None


def explore(bug, prog):
    """neo4d mutates the model's candidate: every single-token change on its code lines, the lines the model changed
    first. -> (a variant that passes every test or None, the candidate's results, the variants sorted best first)"""
    try:
        code = LM.code_lines(prog)
    except SyntaxError:
        return None, None, []
    base = run_all(prog, bug["expr"], bug["cases"])
    lines, old = prog.split("\n"), bug["src"].split("\n")
    sm = difflib.SequenceMatcher(None, old, lines)
    changed = {j for tag, _, _, j1, j2 in sm.get_opcodes() if tag != "equal" for j in range(j1, j2)}
    order = sorted(code, key=lambda li: (min(abs(li - c) for c in changed) if changed else 0, li))
    tried, seen = [], set()
    for li in order:
        for m in D.mutants(R.toks(lines[li])):
            new = LM.to_text(lines[li], list(m))
            if new == lines[li] or (li, new) in seen:
                continue
            seen.add((li, new))
            var = "\n".join(lines[:li] + [new] + lines[li + 1:])
            try:
                ast.parse(var)
            except SyntaxError:
                continue
            res = run_all(var, bug["expr"], bug["cases"])
            if all(ok for ok, _ in res):
                return var, base, tried
            tried.append((sum(ok for ok, _ in res), li, lines[li].strip(), new.strip(), res))
    tried.sort(key=lambda t: (-t[0], t[1]))
    return None, base, tried


def report_back(bug, base, tried):
    """What neo4d tells the model after exploring its candidate."""
    n = len(bug["cases"])
    if base is None:
        return "That attempt was not valid Python."
    out = [f"It passes {sum(ok for ok, _ in base)} of {n} tests."]
    i = next((i for i, (ok, _) in enumerate(base) if not ok), None)
    if i is not None:
        out.append(f"For input {bug['cases'][i][0]!r} it returned {base[i][1]}, expected {bug['cases'][i][1]!r}.")
    if tried:
        out.append(f"neo4d tried {len(tried)} single-token changes to it; the best:")
        for passes, li, o, nw, _ in tried[:3]:
            out.append(f"- line {li + 1}: `{o}` -> `{nw}` passes {passes} of {n}")
    return "\n".join(out)


def exchange(model, bug, rounds, stats):
    """-> (fixed, how): 'model' when the model's own candidate passes, 'neo4d' when a mutation of it does."""
    last = None
    for r in range(rounds):
        prog = ask(model, bug, bug["data"], 0.0 if r == 0 else 0.8, 1000 + r, stats, last)
        if not prog:
            continue
        var, base, tried = explore(bug, prog)
        if base is not None and all(ok for ok, _ in base):
            return True, "model"
        if var:
            return True, "neo4d"
        last = (prog, report_back(bug, base, tried))
    return False, None


def solve(model, bug, data, attempts, stats, marks=()):
    for k in range(attempts):
        prog = ask(model, bug, data, 0.0 if k == 0 else 0.8, 1000 + k, stats, marks=marks)
        if prog and all(ok for ok, _ in run_all(prog, bug["expr"], bug["cases"])):
            return True
    return False


# ------------------------------------------------------------------------- a large model in the exchange, by command

HINTS = REPO / ".build" / "hints"


def hard_bugs(seed=2026):
    """Bugs no model can recall: each correct program obfuscated (hash-named variables, no docstrings or comments)
    and its function renamed to an opaque name, then broken by TWO faults on two lines - each fault alone fails the
    tests, and no single-token change fixes the pair, so neo4d alone cannot."""
    import hashlib
    import random
    from neo4d import obfuscate as O
    O.DEAD = 0
    rng = random.Random(seed)
    out = []
    for name, expr in LM.json_programs().items():
        good_src = (LM.QB / "correct_python_programs" / f"{name}.py").read_text()
        cases = [json.loads(l) for l in (LM.QB / "json_testcases" / f"{name}.json").read_text().splitlines() if l.strip()]
        good = [c for c in cases if LM.run(good_src, expr, [c], 1.5)[0]]
        if len(good) < 2:
            continue
        new = "f_" + hashlib.sha256(name.encode()).hexdigest()[:6]
        src = re.sub(rf"\b{name}\b", new, O.obfuscate(good_src)[0])
        ex = re.sub(rf"\b{name}\b", new, expr)
        if not all(ok for ok, _ in run_all(src, ex, good)):
            continue
        lines = src.split("\n")
        singles = []
        for li in LM.code_lines(src):
            for m in D.mutants(R.toks(lines[li])):
                t = LM.to_text(lines[li], list(m))
                if t != lines[li]:
                    singles.append((li, t))
        rng.shuffle(singles)
        killed = []
        for li, t in singles[:60]:
            prog = "\n".join(lines[:li] + [t] + lines[li + 1:])
            try:
                ast.parse(prog)
            except SyntaxError:
                continue
            if not all(ok for ok, _ in run_all(prog, ex, good)):
                killed.append((li, t))
        pairs = [(a, b) for i, a in enumerate(killed) for b in killed[i + 1:] if a[0] != b[0]]
        rng.shuffle(pairs)
        for (l1, t1), (l2, t2) in pairs[:12]:
            two = list(lines)
            two[l1], two[l2] = t1, t2
            prog = "\n".join(two)
            base = run_all(prog, ex, good)
            if all(ok for ok, _ in base):
                continue
            bug = dict(name=name, expr=ex, src=prog, cases=good, base=base)
            found, n_fail = mutate(bug)
            if any(f["all"] for f in found):
                continue
            bug.update(data=evidence(bug, found, n_fail), neo=False, faults=[l1, l2])
            out.append(bug)
            break
    return out


def hints_cli(args):
    """A large model (a subagent) in the exchange, one submission per command.

    --hints-prepare               the bugs and neo4d's evidence, computed once
    --hints-start RUN NAME        prints the bug (with neo4d's evidence when RUN is an exchange run)
    --hints-submit RUN NAME       a complete corrected program on stdin; at most 3 per bug. In an exchange run neo4d
                                  mutates it and ships any variant that passes, else reports back; otherwise the reply
                                  is the test results only
    --hints-score RUN[,RUN]       the table
    """
    if "--hints-prepare-hard" in args:
        bs = hard_bugs()
        HINTS.mkdir(parents=True, exist_ok=True)
        (HINTS / "bugs_hard.json").write_text(json.dumps(bs))
        print(f"{len(bs)} hard bugs prepared: " + " ".join(b["name"] for b in bs))
        return 0
    if "--hints-prepare" in args:
        bs = bugs()
        for b in bs:
            b["found"], b["n_fail"] = mutate(b)
            b["data"] = evidence(b, b["found"], b["n_fail"])
            b["neo"] = any(f["all"] for f in b["found"])
            del b["found"]
        HINTS.mkdir(parents=True, exist_ok=True)
        (HINTS / "bugs.json").write_text(json.dumps(bs))
        print(f"{len(bs)} bugs prepared: " + " ".join(b["name"] for b in bs))
        return 0
    runs = args[args.index("--hints-score") + 1].split(",") if "--hints-score" in args else []
    hard = "hard" in (runs[0] if runs else args[args.index("--hints-start" if "--hints-start" in args else "--hints-submit") + 1])
    loaded = json.loads((HINTS / ("bugs_hard.json" if hard else "bugs.json")).read_text())
    # a hard bug is known only by its opaque function name: the program's real name would let a model recall it
    by = {(re.search(r"f_[0-9a-f]{6}", b["expr"]).group(0) if hard else b["name"]): b for b in loaded}
    if runs:
        return hints_score(runs, by)
    flag = "--hints-start" if "--hints-start" in args else "--hints-submit"
    i = args.index(flag)
    run, name = args[i + 1], args[i + 2]
    bug, ex = by[name], "exchange" in run
    state = HINTS / run / f"{name}.json"
    if flag == "--hints-start":
        state.parent.mkdir(parents=True, exist_ok=True)
        state.write_text(json.dumps(dict(subs=[], how=None)))
        numbered = "\n".join(f"{n + 1:3d}  {l}" for n, l in enumerate(bug["src"].split("\n")))
        print(f"Bug `{name}`. This Python program has a bug. {first_failure(bug)}\n\n```\n{numbered}\n```\n\n"
              + (f"{bug['data']}\n\n" if ex else "")
              + "Submit the complete corrected program (without line numbers). At most 3 submissions.")
        return 0
    st = json.loads(state.read_text())
    if st["how"] or len(st["subs"]) >= ATTEMPTS:
        print("This bug is closed.")
        return 0
    prog = sys.stdin.read()
    m = re.findall(r"```(?:python)?\n(.*?)```", prog, re.S)
    prog = max(m, key=len) if m else prog
    st["subs"].append(prog)
    n = len(bug["cases"])
    base = run_all(prog, bug["expr"], bug["cases"])
    if all(ok for ok, _ in base):
        st["how"] = "model"
        msg = f"FIXED: all {n} tests pass."
    elif ex:
        var, base, tried = explore(bug, prog)
        if var:
            st["how"] = "neo4d"
            line = next(l for a, l in zip(prog.split("\n"), var.split("\n")) if a != l)
            msg = f"FIXED by neo4d: one single-token change to your program passes all {n} tests: `{line.strip()}`"
        else:
            msg = report_back(bug, base, tried)
    else:
        i = next((i for i, (ok, _) in enumerate(base) if not ok), None)
        msg = (f"It passes {sum(ok for ok, _ in base)} of {n} tests."
               + (f" For input {bug['cases'][i][0]!r} it returned {base[i][1]}, expected {bug['cases'][i][1]!r}." if i is not None else ""))
    if not st["how"] and len(st["subs"]) >= ATTEMPTS:
        msg += "\nNo submissions left: this bug is closed."
    state.write_text(json.dumps(st))
    print(msg)
    return 0


def hints_score(runs, by):
    rest = {k for k, b in by.items() if not b["neo"]}
    hard = "hard" in runs[0]
    head = "## A large model in the exchange" + (": bugs it cannot recall" if hard else "")
    out = [head, "",
           *(["Each correct program obfuscated (hash-named variables, no docstrings or comments), its function renamed "
              "to an opaque name, and broken by **two** faults on two lines: each fault alone fails the tests, and no "
              "single-token change fixes the pair, so neo4d alone fixes none. The model must reason from the code and "
              "the tests.", ""] if hard else []),
           "Claude Haiku, run as subagents, on the same bugs, at most 3 submissions a bug. **Haiku + tests**: after each "
           "submission it is told the test results only. **neo4d + Haiku exchange**: it starts with neo4d's evidence, and "
           "after each submission neo4d mutates the program, ships any variant that passes, or reports back what it "
           "found.", "",
           f"| solver | all {len(by)} bugs | the {len(rest)} neo4d cannot fix alone | fixed at the first submission | "
           "submissions (model calls) | fixed by neo4d mutating the model's program |", "|---|---|---|---|---|---|"]
    for run in runs:
        st = {k: json.loads((HINTS / run / f"{k}.json").read_text()) for k in by if (HINTS / run / f"{k}.json").exists()}
        fixed = {k for k, v in st.items() if v["how"]}
        first = {k for k, v in st.items() if v["how"] and len(v["subs"]) == 1}
        label = "**neo4d + Haiku exchange**" if "exchange" in run else "Haiku + tests"
        out.append(f"| {label} | {len(fixed)}/{len(st)} | {len(fixed & rest)}/{len(rest & set(st))} | {len(first)} | "
                   f"{sum(len(v['subs']) for v in st.values())} | {sum(v['how'] == 'neo4d' for v in st.values())} |")
    p = REPO / "results" / "LOCAL_HINTS.md"
    parts = p.read_text().rstrip("\n").split("\n## ") if p.exists() else ["# Bugs a small model never solved"]
    parts = [x for x in parts if not x.startswith(head[3:])] + ["\n".join(out)[3:]]
    p.write_text("\n\n## ".join(x.strip("\n") for x in parts) + "\n")
    print("\n".join(out))
    return 0


# ------------------------------------------------------- neo4d searches deep, the model only filters which way to go

SHOW, BEAM, LEVELS = 12, 3, 3


def expand(bug, prog, seen):
    """Every single-token change neo4d knows to one program, each run against the tests. -> [(passes, program, diff)]"""
    lines = prog.split("\n")
    out = []
    for li in LM.code_lines(prog):
        for m in D.mutants(R.toks(lines[li])):
            new = LM.to_text(lines[li], list(m))
            var = "\n".join(lines[:li] + [new] + lines[li + 1:])
            if new == lines[li] or var in seen:
                continue
            seen.add(var)
            try:
                ast.parse(var)
            except SyntaxError:
                continue
            res = run_all(var, bug["expr"], bug["cases"])
            out.append((sum(ok for ok, _ in res), var, f"line {li + 1}: `{lines[li].strip()}` -> `{new.strip()}`"))
    return out


def shortlist(cands, k=SHOW):
    """The candidates the filter is shown: the best by tests passed, at most two per changed line, so it sees variety."""
    per, out = defaultdict(int), []
    for c in sorted(cands, key=lambda c: -c[0]):
        line = c[2].split(":")[0]
        if per[line] < 2:
            per[line] += 1
            out.append(c)
        if len(out) == k:
            break
    return out


def blind_search(bug):
    """No model: at each level keep the BEAM candidates that pass the most tests, and go one change deeper."""
    seen, frontier, runs = {bug["src"]}, [(0, bug["src"], "")], 0
    for level in range(LEVELS + 1):
        new = []
        for _, prog, _ in frontier:
            new += expand(bug, prog, seen)
        runs += len(new)
        n = len(bug["cases"])
        if any(c[0] == n for c in new):
            return True, level + 1, runs
        frontier = shortlist(new)[:BEAM]
    return False, None, runs


def search_cli(args):
    """A large model as the filter, one decision per command.

    --search-start RUN ID          neo4d expands the buggy program one change deep and shows the best candidates
    --search-pick RUN ID "1 4 7"   neo4d expands the picked candidates one change deeper (at most 3 picks)
    """
    by = {re.search(r"f_[0-9a-f]{6}", b["expr"]).group(0): b for b in json.loads((HINTS / "bugs_hard.json").read_text())}
    flag = "--search-start" if "--search-start" in args else "--search-pick"
    i = args.index(flag)
    run, key = args[i + 1], args[i + 2]
    bug, n = by[key], len(by[key]["cases"])
    state = HINTS / run / f"{key}.json"
    if flag == "--search-start":
        state.parent.mkdir(parents=True, exist_ok=True)
        seen = {bug["src"]}
        cands = expand(bug, bug["src"], seen)
        st = dict(picks=[], how=None, runs=len(cands), seen=sorted(seen))
        numbered = "\n".join(f"{k + 1:3d}  {l}" for k, l in enumerate(bug["src"].split("\n")))
        msg = [f"Bug `{key}`. This Python program has a bug - possibly more than one fault. {first_failure(bug)}", "",
               "```", numbered, "```", ""]
    else:
        st = json.loads(state.read_text())
        if st["how"] or len(st["picks"]) >= LEVELS:
            print("This bug is closed.")
            return 0
        shown = st["shown"]
        picks = [int(x) for x in re.findall(r"\d+", args[i + 3] if len(args) > i + 3 else sys.stdin.read())][:BEAM]
        picks = [shown[k - 1] for k in picks if 1 <= k <= len(shown)]
        st["picks"].append(len(picks))
        seen = set(st["seen"])
        cands = []
        for c in picks:
            cands += [(p, v, c[2] + "; then " + d) for p, v, d in expand(bug, c[1], seen)]
        st["runs"] += len(cands)
        st["seen"] = sorted(seen)
        msg = []
    win = next((c for c in cands if c[0] == n), None)
    if win:
        st["how"] = "neo4d search"
        msg.append(f"FIXED: neo4d found a program that passes all {n} tests ({win[2]}).")
    else:
        top = shortlist(cands)
        st["shown"] = top
        if not top or len(st["picks"]) >= LEVELS:
            msg.append("No candidates left to explore: this bug is closed." if not top else
                       "That was the last level: this bug is closed.")
            st["how"] = st["how"] or None
            if len(st["picks"]) >= LEVELS or not top:
                st["picks"] += [0] * 0
        else:
            msg.append(f"neo4d tried {len(cands)} single-token changes and ran the tests on each. The most promising "
                       f"(tests passed, of {n}):")
            msg += [f"{k + 1}. passes {p} - {d}" for k, (p, _, d) in enumerate(top)]
            msg.append(f"Pick up to {BEAM} candidates for neo4d to explore one change deeper, e.g. --search-pick "
                       f"{run} {key} \"1 4 7\".")
    state.write_text(json.dumps(st))
    print("\n".join(msg))
    return 0


def search_score(run):
    """neo4d's deep search, blind and with a large model as the filter, on the hard bugs."""
    import hashlib
    from neo4d import obfuscate as O
    O.DEAD = 0
    bs = json.loads((HINTS / "bugs_hard.json").read_text())
    reach = {}
    for b in bs:                                 # can neo4d's operators undo both faults? (the original line is a mutant)
        good = (LM.QB / "correct_python_programs" / f"{b['name']}.py").read_text()
        key = "f_" + hashlib.sha256(b["name"].encode()).hexdigest()[:6]
        src = re.sub(rf"\b{b['name']}\b", key, O.obfuscate(good)[0]).split("\n")
        bad = b["src"].split("\n")
        reach[key] = all(src[l].strip() in {LM.to_text(bad[l], list(m)).strip() for m in D.mutants(R.toks(bad[l]))}
                         for l in b["faults"])
    blind = json.loads((HINTS / "blind.json").read_text())
    st = {k: json.loads((HINTS / run / f"{k}.json").read_text()) for k in reach if (HINTS / run / f"{k}.json").exists()}
    r = {k for k, v in reach.items() if v}
    rows = (("neo4d deep search, blind (keeps the 3 that pass most tests, each level)", {k for k, v in blind.items() if v[0]},
             0, sum(v[2] for v in blind.values())),
            ("**neo4d deep search + Claude Haiku as the filter**", {k for k, v in st.items() if v["how"]},
             sum(len(v["picks"]) for v in st.values()), sum(v["runs"] for v in st.values())))
    out = ["## neo4d searches deep, the model only filters", "",
           f"On the {len(reach)} hard bugs (two faults each, obfuscated, renamed). neo4d generates and tests every "
           f"program: one change deep, then deeper from the candidates kept, up to {LEVELS + 1} changes. **Blind**: it "
           f"keeps the {BEAM} that pass the most tests. **Haiku as the filter**: at each level Haiku is shown the "
           f"{SHOW} most promising candidates and picks up to {BEAM} to go deeper - it never writes code. "
           f"{len(r)} bugs are reachable by neo4d's operators (each fault is one of its changes undone); for the other "
           f"{len(reach) - len(r)}, a fault is outside what it can change, and no search over its changes can fix them.", "",
           f"| solver | fixed | reachable ({len(r)}) | unreachable ({len(reach) - len(r)}) | model calls | test runs |",
           "|---|---|---|---|---|---|"]
    for label, fixed, calls, runs in rows:
        out.append(f"| {label} | **{len(fixed)}/{len(reach)}** | {len(fixed & r)} | {len(fixed - r)} | {calls} | {runs:,} |")
    p = REPO / "results" / "LOCAL_HINTS.md"
    parts = p.read_text().rstrip("\n").split("\n## ") if p.exists() else ["# Bugs a small model never solved"]
    parts = [x for x in parts if not x.startswith(out[0][3:])] + ["\n".join(out)[3:]]
    p.write_text("\n\n## ".join(x.strip("\n") for x in parts) + "\n")
    print("\n".join(out))
    return 0


# ----------------------------------------------- the loop that repeats until it answers: model data -> neo4d mutates

ROUNDS = 10


def tests_feedback(bug, base):
    n = len(bug["cases"])
    if base is None:
        return "That attempt was not valid Python."
    i = next((i for i, (ok, _) in enumerate(base) if not ok), None)
    return (f"It passes {sum(ok for ok, _ in base)} of {n} tests."
            + (f" For input {bug['cases'][i][0]!r} it returned {base[i][1]}, expected {bug['cases'][i][1]!r}." if i is not None else ""))


def loop(model, bug, rounds, with_neo4d, stats):
    """Round after round until it answers: the model gives a program (data and a direction); without neo4d it is told
    the test results; with neo4d, neo4d also mutates that program, ships any variant that passes, and reports its best
    variants back. -> (round it was fixed in or None, 'model' / 'neo4d')"""
    last = None
    for r in range(rounds):
        prog = ask(model, bug, None, 0.0 if r == 0 else 0.8, 1000 + r, stats, last)
        if not prog:
            continue
        if with_neo4d:
            var, base, tried = explore(bug, prog)
            if base is not None and all(ok for ok, _ in base):
                return r + 1, "model"
            if var:
                return r + 1, "neo4d"
            last = (prog, report_back(bug, base, tried))
        else:
            try:
                ast.parse(prog)
                base = run_all(prog, bug["expr"], bug["cases"])
            except SyntaxError:
                base = None
            if base is not None and all(ok for ok, _ in base):
                return r + 1, "model"
            last = (prog, tests_feedback(bug, base))
    return None, None


def loop_main(models):
    bs = json.loads((HINTS / "bugs.json").read_text())
    rest = [b for b in bs if not b["neo"]]
    out = ["## Round after round until it answers", "",
           f"The loop: the model gives a program - data and a direction, even when wrong - and gets an answer back; up "
           f"to {ROUNDS} rounds a bug, stopping when every test passes. **Model + test feedback**: it is told what its "
           "program passes and the first failing test. **Model ⇄ neo4d**: the same, and neo4d mutates the model's "
           "program (every single-token change it knows), ships any variant that passes, and reports its best variants "
           "back - each round it expands what the model gave it. On all the real bugs; neo4d's evidence about the "
           "original bug is not given up front.", ""]
    marks = (1, 2, 3, 5, ROUNDS)
    for model in models:
        res = {}
        for label, neo in (("model + test feedback", False), ("**model ⇄ neo4d**", True)):
            stats = defaultdict(int)
            res[label] = ({b["name"]: loop(model, b, ROUNDS, neo, stats) for b in bs}, stats["calls"])
            got = res[label][0]
            print(f"  {model} {label}: {sum(v[0] is not None for v in got.values())}/{len(bs)} "
                  f"({stats['calls']} calls)", flush=True)
        out += [f"### {model}", "",
                "| loop | " + " | ".join(f"fixed by round {m}" for m in marks) + f" | the {len(rest)} neo4d cannot fix "
                "alone | model calls | fixed by neo4d mutating the model's program |", "|---|" + "---|" * (len(marks) + 3)]
        for label, (got, calls) in res.items():
            out.append(f"| {label} | " + " | ".join(str(sum(v[0] is not None and v[0] <= m for v in got.values()))
                                                  for m in marks)
                       + f" | {sum(got[b['name']][0] is not None for b in rest)} | {calls} | "
                       f"{sum(v[1] == 'neo4d' for v in got.values())} |")
        out.append("")
    p = REPO / "results" / "LOCAL_HINTS.md"
    parts = p.read_text().rstrip("\n").split("\n## ") if p.exists() else ["# Bugs a small model never solved"]
    parts = [x for x in parts if not x.startswith(out[0][3:])] + ["\n".join(out)[3:]]
    p.write_text("\n\n## ".join(x.strip("\n") for x in parts) + "\n")
    print("\n".join(out))
    return 0


def focus_main(models):
    """Clarity for the model's attention: the same bug shown three ways."""
    bs = json.loads((HINTS / "bugs.json").read_text())
    out = ["## Clarity for the model's attention", "",
           "The same bug shown three ways: **plain**; with **neo4d's evidence as a paragraph** (what its mutations found); "
           f"and with **neo4d's marks** - no paragraph, only the comment `{MARK}` on the one or two lines its mutations "
           "point to, so the model's attention goes there.", "",
           "Example (the lines marked for `" + bs[0]["name"] + "`): " + ", ".join(str(l + 1) for l in suspects(bs[0])) + ".", ""]
    for model in models:
        out += [f"### {model}", "", "| shown | fixed, one try | fixed, up to 3 tries | model calls |", "|---|---|---|---|"]
        for label, data, marks in (("plain", False, False), ("neo4d's evidence as a paragraph", True, False),
                                   ("**neo4d's marks on the suspect lines**", False, True)):
            row = []
            for att in (1, ATTEMPTS):
                stats = defaultdict(int)
                row.append((sum(solve(model, b, b["data"] if data else None, att, stats, suspects(b) if marks else ())
                                for b in bs), stats["calls"]))
            out.append(f"| {label} | {row[0][0]}/{len(bs)} | {row[1][0]}/{len(bs)} | {row[0][1] + row[1][1]} |")
            print(f"  {model} {label}: {row[0][0]} / {row[1][0]}", flush=True)
        out.append("")
    p = REPO / "results" / "LOCAL_HINTS.md"
    parts = p.read_text().rstrip("\n").split("\n## ") if p.exists() else ["# Bugs a small model never solved"]
    parts = [x for x in parts if not x.startswith(out[0][3:])] + ["\n".join(out)[3:]]
    p.write_text("\n\n## ".join(x.strip("\n") for x in parts) + "\n")
    print("\n".join(out))
    return 0


# ---------------------------------------------------------------------------------------------------- report

def main() -> int:
    args = sys.argv[1:]
    if any(x.startswith("--hints") for x in args):
        return hints_cli(args)
    if "--search-start" in args or "--search-pick" in args:
        return search_cli(args)
    if "--focus" in args:
        return focus_main(args[args.index("--focus") + 1].split(","))
    if "--loop" in args:
        return loop_main(args[args.index("--loop") + 1].split(","))
    if "--search-score" in args:
        return search_score(args[args.index("--search-score") + 1])
    if "--search-blind" in args:
        bs = json.loads((HINTS / "bugs_hard.json").read_text())
        res = {re.search(r"f_[0-9a-f]{6}", b["expr"]).group(0): blind_search(b) for b in bs}
        (HINTS / "blind.json").write_text(json.dumps(res))
        print(f"blind deep search: {sum(v[0] for v in res.values())}/{len(bs)} fixed, "
              f"{sum(v[2] for v in res.values())} test runs")
        return 0
    models = (args[args.index("--models") + 1] if "--models" in args else "phi4-mini").split(",")
    t0 = time.time()
    bs = bugs()
    for b in bs:
        b["found"], b["n_fail"] = mutate(b)
        b["data"] = evidence(b, b["found"], b["n_fail"])
        b["neo"] = any(f["all"] for f in b["found"])
    print(f"  {len(bs)} bugs, mutation analysis done ({time.time() - t0:.0f}s); neo4d alone fixes "
          f"{sum(b['neo'] for b in bs)}", flush=True)
    rest = [b for b in bs if not b["neo"]]
    out = ["# Bugs a small model never solved: neo4d mutates, the model reasons with the evidence", "",
           "Generated by `neo4d/local_hints.py`. The real QuixBugs bugs - written by people, not by neo4d's mutation "
           f"operators - in the {len(bs)} programs whose tests are JSON cases. neo4d tries every single-token change its "
           "operators know, runs the tests on each, and gives the model what it found (which changes make failing tests "
           "pass, which lines move the failing tests, the closest near-fixes) in the prompt; nothing is trained. A fix "
           "counts when every test passes.", "",
           f"**neo4d alone** (a mutation that passes every test): **{sum(b['neo'] for b in bs)} of {len(bs)}** bugs. The "
           f"other **{len(rest)}** are bugs its mutations cannot fix - the test that matters is there.", "",
           "Example of what the model is given, for `" + rest[0]["name"] + "`:" if rest else "", "",
           "```", rest[0]["data"] if rest else "", "```", ""]
    for model in models:
        rows, calls = {}, {}
        for label, data, att in (("model alone", False, 1), ("model + tests", False, ATTEMPTS),
                                 ("model + neo4d's data", True, 1), ("model + neo4d's data + tests", True, ATTEMPTS)):
            stats = defaultdict(int)
            rows[label] = {b["name"]: solve(model, b, b["data"] if data else None, att, stats) for b in bs}
            calls[label] = stats["calls"]
            print(f"  {model} {label}: {sum(rows[label].values())}/{len(bs)} ({time.time() - t0:.0f}s)", flush=True)
        stats = defaultdict(int)
        ex = {b["name"]: exchange(model, b, ATTEMPTS, stats) for b in bs}
        rows["**exchange: model ⇄ neo4d**"] = {k: v[0] for k, v in ex.items()}
        calls["**exchange: model ⇄ neo4d**"] = stats["calls"]
        print(f"  {model} exchange: {sum(v[0] for v in ex.values())}/{len(bs)} ({time.time() - t0:.0f}s)", flush=True)
        never = [b for b in rest if not rows["model alone"][b["name"]] and not rows["model + tests"][b["name"]]]
        out += [f"## {model}", "",
                f"| solver | all {len(bs)} bugs | the {len(rest)} neo4d cannot fix alone | the {len(never)} the model "
                "never solved, even with 3 tries | model calls |", "|---|---|---|---|---|"]
        for label, r in rows.items():
            out.append(f"| {label} | {sum(r.values())} | **{sum(r[b['name']] for b in rest)}** | "
                       f"**{sum(r[b['name']] for b in never)}** | {calls[label]} |")
        by_neo = [k for k, v in ex.items() if v[1] == "neo4d"]
        out += ["", f"In the exchange, **{len(by_neo)}** bugs were fixed by neo4d mutating the model's candidate - the "
                "model's attempt alone failed, and neo4d's mutations of the original code alone failed"
                + (": " + ", ".join(f"`{k}`" for k in by_neo) if by_neo else "") + ".", ""]
    out += ["**What this does not show.** QuixBugs is public, so a model may have seen these programs. The data comes "
            "from the tests, so it needs tests that fail on the bug - the same tests every solver here is judged by. "
            "31 bugs is a small sample."]
    (REPO / "results" / "LOCAL_HINTS.md").write_text("\n".join(out) + "\n")
    print("\n".join(out))
    return 0


if __name__ == "__main__":
    sys.exit(main())
