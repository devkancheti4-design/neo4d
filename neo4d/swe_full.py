"""neo4d at full strength on SWE-bench - the condition `neo4d_full` of neo4d/swe_agent.py.

The `neo4d` condition mutates the lines the model's edit changed and ships the first variant that passes. Here neo4d
also does what its repair laws are for; the body measures, the laws decide:

    PICK       orders every mutation trial (kernels/pick.c): a line the reproduction never runs is vetoed, a variant a
               trusted pattern proposes ranks above any number of weak signals, the function the issue names next
    SHIP       decides every green candidate (kernels/ship.c): only a stable green with something to repair ships; two
               greens, or thin evidence (no regression tests behind the edit), go to the model as evidence instead
    RELATE v2  sets the strength of every pattern neo4d remembers (kernels/relate_v2.c, through local_model.Brain): it
               learns from every fix the agent verified, across issues, and its active patterns propose candidates
    marks      before the model's first try neo4d mutates the lines the reproduction runs; the lines its mutants point
               to are marked in the code the model is shown (results/LOCAL_HINTS.md, "attention marks")

Bits the SWE-bench setting cannot measure are fixed, and said so in the trajectory:
    PICK   NEW_SPAN 1 (each distinct variant is tried once), TRIED 0 (the same), MANY_TESTS 0 (no per-test coverage of
           the projects' suites)
    SHIP   PROVEN 0, REFUTED 0 (no class property for real projects), ROUTED 1 (every act is one of neo4d's operators
           or a learned relation, never a guess), THIN = no regression tests passed before the edit
The other laws (HARVEST, INDUCE, the routers) belong to neo4d's self-learning loop on correct code and its 4D core;
they are not used here.

No model calls are added: neo4d's evidence goes into the prompts the model gets anyway.
"""
from __future__ import annotations

import ast
import ctypes
import difflib
import json
import pickle
from collections import Counter, defaultdict
from pathlib import Path

from neo4d import KERNELS, build_kernel
from neo4d import domain_mutation as D
from neo4d import local_model as LM
from neo4d import relate_live as RL
from neo4d import relations as R

FL_CAP = 40                    # trials before the model's first try (fault localisation and early fixes)
MARK = "# <-- neo4d: changing this line changes what the reproduction does"
WAS_RED, GREEN, STABLE, UNIQUE, PROVEN, REFUTED, THIN, ROUTED = (1 << i for i in range(8))
REFUSE, ASK, SHIP, SHIP_PROVEN = range(4)


def _kernel(name):
    f = getattr(ctypes.CDLL(str(build_kernel(name))), name)
    f.argtypes, f.restype = [ctypes.c_int32], ctypes.c_int32
    table = [int(f(x)) for x in range(256)]
    return lambda x: table[x]


pick, ship = _kernel("pick"), _kernel("ship")


def relate_v2():
    return RL.load_law(str(KERNELS / "relate_v2.c"))


# --------------------------------------------------------------------------------------- measuring the repository

COVERAGE = r'''
import json, os, runpy, sys, threading
target, script, out = os.path.realpath(sys.argv[1]), sys.argv[2], sys.argv[3]
hits, seen = set(), {}
def local(frame, event, arg):
    if event == "line":
        hits.add(frame.f_lineno)
    return local
def outer(frame, event, arg):
    f = frame.f_code.co_filename
    if f not in seen:
        seen[f] = not f.startswith("<") and os.path.realpath(f) == target
    if seen[f]:
        hits.add(frame.f_lineno)
        return local
    return None
sys.argv = [script]
sys.settrace(outer); threading.settrace(outer)
try:
    runpy.run_path(script, run_name="__main__")
except BaseException:
    pass
finally:
    sys.settrace(None)
    json.dump(sorted(hits), open(out, "w"))
'''


def coverage(env, path):
    """The lines of `path` the reproduction executes (1-based), from one traced run."""
    env.write("/tmp/neo4d_cov.py", COVERAGE)
    target = path if path.startswith("/") else f"{getattr(env, 'root', '/testbed')}/{path}"
    py = getattr(env, "python", "python")
    _, out = env.run(f"rm -f /tmp/neo4d_cov.json; {py} /tmp/neo4d_cov.py {json.dumps(str(target))} {env.repro} "
                     f"/tmp/neo4d_cov.json > /dev/null 2>&1; cat /tmp/neo4d_cov.json", timeout=180)
    try:
        return set(json.loads(out.strip().splitlines()[-1]))
    except (ValueError, IndexError):
        return set()


def statements(text):
    """For each line (0-based): (the start line of its innermost statement (1-based), that statement's node type,
    the name of the function holding it or None)."""
    tree = ast.parse(text)
    best = {}
    funcs = []
    for n in ast.walk(tree):
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)):
            funcs.append((n.lineno, n.end_lineno, n.name))
        if isinstance(n, ast.stmt):
            for ln in range(n.lineno, (n.end_lineno or n.lineno) + 1):
                cur = best.get(ln)
                if cur is None or (n.end_lineno - n.lineno) < (cur[1] - cur[0]):
                    best[ln] = (n.lineno, n.end_lineno, type(n).__name__)
    out = {}
    for ln, (s, _, kind) in best.items():
        holder = [f for f in funcs if f[0] <= ln <= f[1]]
        name = min(holder, key=lambda f: f[1] - f[0])[2] if holder else None
        out[ln - 1] = (s, kind, name)
    return out


HEADERS = ("FunctionDef", "AsyncFunctionDef", "ClassDef", "Import", "ImportFrom")


def executed_lines(text, hits):
    """Code lines (0-based) whose innermost statement the reproduction ran - not def/class headers or imports, which
    run at import whatever the issue is."""
    try:
        st, code = statements(text), set(LM.code_lines(text))
    except SyntaxError:
        return set()
    return {i for i in code if i in st and st[i][1] not in HEADERS and st[i][0] in hits}


def signature(code, out):
    """What a reproduction run did: did it pass, and its last line of output."""
    last = [l for l in (out or "").strip().splitlines() if l.strip()]
    return code == 0, (last[-1][:200] if last else "")


# ------------------------------------------------------------------------------------------------- the memory

class Memory(LM.Brain):
    """local_model's Brain - patterns as neurons, the RELATE v2 law setting every strength - over files of real
    repositories: it proposes on chosen lines only, and learns from single-line fixes the agent verified."""

    def propose_on(self, text, lines):
        lines_t = text.split("\n")
        idx = D.Index(self.active())
        out, fired = defaultdict(list), defaultdict(int)
        for i in sorted(lines):
            a = ["^"] + R.toks(lines_t[i])
            x = {"a": a, "keys": set(a) | ({"$INT"} if any(R.is_int(t) for t in a) else set())
                 | ({"$ID"} if any(R.is_ident(t) for t in a) else set())}
            scope = lines_t[max(0, i - 3):i + 4]
            for k in idx.on(x):
                c = set(R.generate(k[1], a, scope, cap=200))
                c.discard(tuple(a))
                if c:
                    fired[k] += 1
                for m in c:
                    out["\n".join(lines_t[:i] + [LM.to_text(lines_t[i], list(m))] + lines_t[i + 1:])].append(k)
        return out, fired

    def learn_fix(self, net, before, after):
        """Learn one verified fix if it changed exactly one line (the edits the patterns represent). -> learned?"""
        b, a = before.split("\n"), after.split("\n")
        diff = [i for i in range(min(len(b), len(a))) if b[i] != a[i]]
        if len(b) != len(a) or len(diff) != 1:
            return False
        try:
            proposals, fired = self.propose_on(before, set(LM.code_lines(before)) & {diff[0]})
        except SyntaxError:
            return False
        self.learn({"buggy": before, "prog": net}, after, proposals, fired)
        return True

    def save(self, path):
        law, self.law = self.law, None
        Path(path).write_bytes(pickle.dumps(self))
        self.law = law

    @staticmethod
    def load(path):
        if Path(path).exists():
            m = pickle.loads(Path(path).read_bytes())
            m.law = relate_v2()
            return m
        return Memory(relate_v2())


# --------------------------------------------------------------------------------------------- trials and search

def candidates(text, lines, memory):
    """Every variant of `text` on `lines`: neo4d's single-token operators, and the memory's active patterns.
    -> [dict(text, line, kind, trusted)] without duplicates (syntax is checked when a variant is chosen)."""
    t = text.split("\n")
    out, seen = [], {text}
    trusted = defaultdict(set)
    if memory is not None and memory.active():
        props, _ = memory.propose_on(text, lines)
        for var, ks in props.items():
            trusted[var] |= {memory.level[k] for k in ks}
    for var in sorted(trusted):
        i = next(n for n in range(len(t)) if var.split("\n")[n] != t[n])
        out.append(dict(text=var, line=i, kind="memory", trusted=True))
        seen.add(var)
    for i in sorted(lines):
        for m, op in D.mutants(R.toks(t[i])).items():
            new = LM.to_text(t[i], list(m))
            var = "\n".join(t[:i] + [new] + t[i + 1:])
            if new == t[i] or var in seen:
                continue
            seen.add(var)
            out.append(dict(text=var, line=i, kind=op, trusted=False))
    return out


def pick_word(c, executed, named, cold):
    return (1 | int(c["line"] in executed) << 1 | int(c["trusted"]) << 3 | int(c["line"] in named) << 5
            | int(cold[c["kind"]] >= 2) << 6)


def search(env, path, base, lines, executed, order, regress, base_ok, base_sig, memory, named, cap, traj, stage):
    """Trials on `lines` of `base`, PICK choosing each next one, up to `cap` runs. The file is left as `base`.
    -> (greens [dict], moved Counter line -> trials that changed the reproduction's result, trials run)"""
    cands = candidates(base, lines, memory)
    rank_line = {li: k for k, li in enumerate(order)}
    cold = Counter()
    greens, moved, tried = [], Counter(), 0
    left = list(cands)
    while left and tried < cap:
        scored = [(pick(pick_word(c, executed, named, cold)), c) for c in left]
        scored = [(r, c) for r, c in scored if r > 0]
        if not scored:
            break
        r, c = min(scored, key=lambda rc: (-rc[0], rank_line.get(rc[1]["line"], 10 ** 6), rc[1]["line"]))
        left.remove(c)
        try:
            ast.parse(c["text"])
        except SyntaxError:
            continue
        env.write(path, c["text"])
        code, out = env.py(env.repro)
        tried += 1
        sig = signature(code, out)
        if sig != base_sig:
            moved[c["line"]] += 1
        if code == 0:
            still = env.run(regress, timeout=900)[0] == 0 if (regress and base_ok) else None
            stable = env.py(env.repro)[0] == 0
            greens.append(dict(c, regression=still, stable=stable))
        elif sig == base_sig:
            cold[c["kind"]] += 1
    env.write(path, base)
    traj.append(dict(kind="neo4d_search", stage=stage, candidates=len(cands), executed_lines=len(executed),
                     tried=tried, greens=len(greens), moved_lines=len(moved)))
    return greens, moved, tried


def decide(greens, base_ok):
    """SHIP on every green candidate. -> (the one to ship or None, [candidates to put to the model])"""
    distinct = {g["text"] for g in greens if g["stable"] and g["regression"] is not False}
    verdicts = []
    for g in greens:
        green = g["regression"] is not False
        x = (WAS_RED | GREEN * green | STABLE * g["stable"] | UNIQUE * (green and g["stable"] and len(distinct) == 1)
             | THIN * (not base_ok) | ROUTED)
        verdicts.append((ship(x), x, g))
    shipped = next((g for v, _, g in verdicts if v in (SHIP, SHIP_PROVEN)), None)
    asked = [g for v, _, g in verdicts if v == ASK]
    return shipped, asked, [(v, x) for v, x, _ in verdicts]


def describe(base, gs, k=4):
    t = base.split("\n")
    return "\n".join(f"- line {g['line'] + 1}: `{t[g['line']].strip()}` -> `{g['text'].split(chr(10))[g['line']].strip()}`"
                     for g in gs[:k])


def mark(excerpt_text, lines):
    """Add neo4d's mark to the numbered lines (0-based) of an excerpt."""
    want = {li + 1 for li in lines}
    out = []
    for l in excerpt_text.split("\n"):
        head = l[:5].strip()
        out.append(f"{l}    {MARK}" if head.isdigit() and int(head) in want else l)
    return "\n".join(out)


def keyword_order(text, kws):
    t = text.split("\n")
    return sorted(range(len(t)), key=lambda i: (-sum(w in t[i] for w in kws), i))


# ------------------------------------------------------------------------------------------- the two moments

def before_rounds(env, path, original, issue, kws, failing, regress, base_ok, memory, traj):
    """Before the model's first try: trials on every line the reproduction runs. -> (a text to ship or None,
    the lines to mark, evidence for the model)"""
    try:
        st = statements(original)
    except SyntaxError:
        return None, [], ""
    named = {i for i, (_, _, fn) in st.items() if fn and (fn in issue)}
    base_sig = signature(1, failing)
    executed = executed_lines(original, coverage(env, path))
    greens, moved, tried = search(env, path, original, executed, executed, keyword_order(original, kws), regress,
                                  base_ok, base_sig, memory, named, FL_CAP, traj, "before the model")
    shipped, asked, verdicts = decide(greens, base_ok)
    traj.append(dict(kind="neo4d_ship", stage="before the model", verdicts=verdicts,
                     shipped=None if shipped is None else f"line {shipped['line'] + 1}"))
    hot = [g["line"] for g in greens] + [li for li, _ in sorted(moved.items(), key=lambda kv: (-kv[1], kv[0]))]
    marks = list(dict.fromkeys(hot))[:2]
    evidence = ""
    if asked:
        evidence = ("neo4d found single-token edits that make the reproduction pass, but could not certify them "
                    "(more than one, or no tests behind them):\n" + describe(original, asked))
    traj.append(dict(kind="neo4d_marks", lines=[m + 1 for m in marks], tried=tried))
    return (shipped["text"] if shipped else None), marks, evidence


def after_edit(env, path, original, patched, issue, regress, base_ok, memory, traj, cap):
    """After a model edit that did not pass: trials around the lines it changed, PICK ordering, SHIP deciding.
    -> (a text to ship or None, notes for the model)"""
    old, new = original.split("\n"), patched.split("\n")
    sm = difflib.SequenceMatcher(None, old, new)
    changed = sorted({j for tag, _, _, j1, j2 in sm.get_opcodes() if tag != "equal" for j in range(j1, j2)})
    try:
        code = set(LM.code_lines(patched))
        st = statements(patched)
    except SyntaxError:
        return None, "the patched file is not valid Python"
    near = {j for c in changed for j in range(c - 2, c + 3)} & code
    order = sorted(near, key=lambda j: (min(abs(j - c) for c in changed), j))
    named = {i for i, (_, _, fn) in st.items() if fn and (fn in issue)}
    env.write(path, patched)
    code_, out = env.py(env.repro)
    executed = executed_lines(patched, coverage(env, path))
    greens, moved, tried = search(env, path, patched, near, executed, order, regress, base_ok, signature(code_, out),
                                  memory, named, cap, traj, "after the model's edit")
    shipped, asked, verdicts = decide(greens, base_ok)
    traj.append(dict(kind="neo4d_ship", stage="after the model's edit", verdicts=verdicts,
                     shipped=None if shipped is None else f"line {shipped['line'] + 1}"))
    if shipped:
        return shipped["text"], ""
    notes = []
    if asked:
        notes.append("neo4d found single-token changes to your edit that make the reproduction pass, but could not "
                      "certify them (more than one, or no tests behind them):\n" + describe(patched, asked))
    elif moved:
        p = patched.split("\n")
        notes.append("neo4d tried single-token changes around your edit; these lines changed the reproduction's "
                     "result: " + "; ".join(f"line {li + 1} `{p[li].strip()}`" for li, _ in moved.most_common(3)))
    else:
        notes.append(f"neo4d tried {tried} single-token changes around your edit; none changed the reproduction's "
                     "result" + ("" if tried else " (the reproduction never runs the lines you edited)") + ".")
    return None, "\n".join(notes)
