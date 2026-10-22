"""A whole domain, taught: code mutation. Does the swarm generalise to code it never saw, cover most of the domain,
and grow with scale? The RELATE law (neo4d/kernels/relate_v1.c) decides every neuron, unchanged from the bug runs.

THE DOMAIN. The standard mutation operators of mutation-testing tools (mutmut, PIT, Major), applied to every code line
of the Python standard library on this machine (each top-level module or package is a net):

    ROR  a comparison becomes another (< <= > >= == !=)       ASR  += -= *= /= become one another
    AOR  binary + - * / % become one another                  LCR  and <-> or        BCR  True <-> False
    NEG  delete a `not`; negate a condition (if/elif/while -> ... not); `is` -> `is not`
    CRP  an integer n -> n + 1, and 0 <-> 1                    BRK  break <-> continue
    RET  `return <value>` -> `return None`

The reference mutator below is the domain's ground truth - the teacher. It gives every mutant of a line.

THE EXPERIMENT. A quarter of the nets are held out. The swarm is taught k lines from the others (k = 10 ... 10,000),
each with all its mutants (possibly none); every mutant is an event for its literal-edit neuron and its relation neuron
(neo4d/relations.py), and the law sets their strengths exactly as in neo4d/relate_live.py. Then, on a fixed sample of
lines from the held-out nets, the swarm's active neurons generate:

    coverage    the share of the held-out lines' real mutants generated exactly - did it learn the domain?
    precision   the share of generated candidates that are real mutants - does it mutate well, or spray?

    python -m neo4d.domain_mutation   -> results/DOMAIN_MUTATION.md
"""
from __future__ import annotations

import ast
import random
import re
import statistics
import sys
import sysconfig
from collections import Counter, defaultdict
from pathlib import Path

from neo4d import REPO
from neo4d import relations as R
from neo4d import relate_live as RL

ROR = ["<", "<=", ">", ">=", "==", "!="]
ROR_JS = ["<", "<=", ">", ">=", "==", "!=", "===", "!=="]     # JavaScript's strict equality joins the family
NUMTAIL = re.compile(r"^([xX][0-9a-fA-F]+|[bB][01]+|[eE]\d*|[oO][0-7]+)[lLuU]*$")   # the rest of 0x1F, 0b10, 1e5
AOR = ["+", "-", "*", "/", "%"]
ASR = ["+=", "-=", "*=", "/="]
SKIP_DIRS = {"test", "idlelib", "site-packages", "tkinter", "turtledemo", "__pycache__", "config-3.14-darwin"}
KS = (10, 30, 100, 300, 1000, 3000, 10000)
BARREN_FIRES = 10        # the domain's record behind BARREN: mutation relations hit often, so 10 firings judge them
SEEDS = (0, 1, 2)
N_EVAL = 2000


# ------------------------------------------------------------------------------------------------- the corpus

def strip_comment(line, lang="py"):
    """The line without its trailing comment (`#` in Python, `//` in the C family), outside string literals."""
    q, i = None, 0
    while i < len(line):
        c = line[i]
        if q:
            if c == "\\":
                i += 2
                continue
            if c == q:
                q = None
        elif c in "'\"":
            q = c
        elif (lang == "py" and c == "#") or (lang != "py" and line.startswith("//", i)):
            return line[:i].rstrip()
        i += 1
    return line.rstrip()


def corpus():
    root = Path(sysconfig.get_paths()["stdlib"])
    out = []
    for p in sorted(root.rglob("*.py")):
        rel = p.relative_to(root)
        if any(part in SKIP_DIRS for part in rel.parts) or len(rel.parts) > 2:
            continue
        net = rel.parts[0][:-3] if len(rel.parts) == 1 else rel.parts[0]
        src = p.read_text(errors="replace")
        try:
            tree = ast.parse(src)
        except SyntaxError:
            continue
        drop = set()
        for n in ast.walk(tree):
            if isinstance(n, ast.Expr) and isinstance(n.value, ast.Constant) and isinstance(n.value.value, str):
                drop.update(range(n.lineno, n.end_lineno + 1))
        lines = src.split("\n")
        code = [(i, strip_comment(l)) for i, l in enumerate(lines, 1)
                if i not in drop and l.strip() and not l.strip().startswith("#") and len(l) < 160]
        code = [(i, l) for i, l in code if l.strip()]
        for j, (i, l) in enumerate(code):
            scope = [x for _, x in code[max(0, j - 3):j + 4]]
            out.append((net, l, scope))
    return out


# ------------------------------------------------------------------------------------- the teacher: every mutant

def _binary(a, i):
    if i == 0 or i == len(a) - 1:
        return False
    p = a[i - 1]
    return R.is_ident(p) or R.is_int(p) or p in (")", "]", "'", '"', "NULL", "TRUE", "FALSE")


def _template(a, i):
    """`<` opening a C++/Java template or generic argument list (`vector<int>`, `List<String>`): the index of its
    closing `>`, else None."""
    if i == 0 or not R.is_ident(a[i - 1]):
        return None
    depth = 0
    for j in range(i, len(a)):
        t = a[j]
        if t == "<":
            depth += 1
        elif t in (">", ">>"):
            depth -= 1 if t == ">" else 2
            if depth <= 0:
                nxt = a[j + 1] if j + 1 < len(a) else ""
                ok = nxt in ("", "(", "::", ")", ",", ";", "{", "&", "*", ">", "AND") or R.is_ident(nxt)
                return j if ok else None
        elif not (R.is_ident(t) or R.is_int(t) or t in ("::", ",", "*", "&", "const", ".", "?")):
            return None
    return None


def mutants(a, lang="py", hard=False):
    """Every mutant of token list a, as {mutant tokens: operator}. lang: py, c, cpp, java. hard adds ARG (swap two
    adjacent arguments), IDX (a subscript off by one), DEL (delete a call statement) and, in the C family, UOI
    (++ <-> --)."""
    out = {}
    cfam = lang != "py"
    skip = set()
    if lang in ("cpp", "java"):
        for i, t in enumerate(a):
            if t == "<":
                j = _template(a, i)
                if j is not None:
                    skip.update((i, j))

    def put(m, op):
        m = tuple(m)
        if m != tuple(a):
            out.setdefault(m, op)
    ror = ROR_JS if lang == "js" else ROR
    for i, t in enumerate(a):
        if i in skip:
            continue
        if t in ror and _binary(a, i):
            for u in ror:
                put(a[:i] + [u] + a[i + 1:], "ROR")
        elif t in AOR and _binary(a, i) and a[i - 1] != t and a[i + 1] != t:
            for u in AOR:
                put(a[:i] + [u] + a[i + 1:], "AOR")
        elif t in ASR:
            for u in ASR:
                put(a[:i] + [u] + a[i + 1:], "ASR")
        elif t in ("AND", "OR"):
            put(a[:i] + ["OR" if t == "AND" else "AND"] + a[i + 1:], "LCR")
        elif t in ("TRUE", "FALSE"):
            put(a[:i] + ["FALSE" if t == "TRUE" else "TRUE"] + a[i + 1:], "BCR")
        elif t == "NOT":
            put(a[:i] + a[i + 1:], "NEG")
        elif t == "is" and not cfam and i + 1 < len(a) and a[i + 1] != "NOT":
            put(a[:i + 1] + ["NOT"] + a[i + 1:], "NEG")
        elif R.is_int(t) and t.isdigit() and not (i + 1 < len(a) and NUMTAIL.match(a[i + 1])):
            n = int(t)
            put(a[:i] + [str(n + 1)] + a[i + 1:], "CRP")
            if n in (0, 1):
                put(a[:i] + [str(1 - n)] + a[i + 1:], "CRP")
        elif hard and cfam and t in ("++", "--"):
            put(a[:i] + ["--" if t == "++" else "++"] + a[i + 1:], "UOI")
    if not cfam:
        if a and a[0] in ("if", "elif", "while") and len(a) > 2 and a[1] != "NOT":
            put(a[:1] + ["NOT"] + a[1:], "NEG")
        if a in (["break"], ["continue"]):
            put(["continue" if a[0] == "break" else "break"], "BRK")
        if a and a[0] == "return" and len(a) > 1 and a[1:] != ["NULL"]:
            put(["return", "NULL"], "RET")
    else:
        for i, t in enumerate(a[:-2]):
            if t in ("if", "while") and a[i + 1] == "(" and a[i + 2] != "NOT":
                put(a[:i + 2] + ["NOT"] + a[i + 2:], "NEG")
        if a in (["break", ";"], ["continue", ";"]):
            put(["continue" if a[0] == "break" else "break", ";"], "BRK")
        if a and a[0] == "return" and len(a) > 2 and a[-1] == ";":
            val = ["NULL"] if lang in ("java", "js") else ["0"]
            if a[1:-1] != val:
                put(["return"] + val + [";"], "RET")
    if hard:
        for i in range(1, len(a) - 3):
            if R.is_ident(a[i]) and a[i + 1] == "," and R.is_ident(a[i + 2]) and a[i - 1] in ("(", ",") \
                    and a[i + 3] in (")", ",") and a[i] != a[i + 2]:
                put(a[:i] + [a[i + 2], ",", a[i]] + a[i + 3:], "ARG")
        for i in range(len(a) - 2):
            if a[i] == "[" and R.is_ident(a[i + 1]) and a[i + 2] == "]":
                put(a[:i + 2] + ["+", "1"] + a[i + 2:], "IDX")
                put(a[:i + 2] + ["-", "1"] + a[i + 2:], "IDX")
        end = ";" if cfam else ")"
        if a and R.is_ident(a[0]) and len(a) > 2 and a[1] in (".", "(", "->") and a[-1] == end and "=" not in a \
                and "(" in a:
            put([";"] if cfam else ["pass"], "DEL")
    return out


def _anchor(a, m, o, n):
    """The same edit with one token of context before it kept in the pattern - `if -> if not` rather than `-> not`
    anywhere; at the start of a line the anchor is the start marker `^`."""
    i = 0
    while i < min(len(a), len(m)) and a[i] == m[i]:
        i += 1
    if i == 0:
        return None
    return (a[i - 1],) + tuple(o), (a[i - 1],) + tuple(n)


def edit_tokens(a, b):
    i = 0
    while i < min(len(a), len(b)) and a[i] == b[i]:
        i += 1
    j = 0
    while j < min(len(a), len(b)) - i and a[-1 - j] == b[-1 - j]:
        j += 1
    return tuple(a[i:len(a) - j]), tuple(b[i:len(b) - j])


# ----------------------------------------------------------------------------------------------- the neurons

def neurons_of(a, m, scope):
    """The neurons one mutant instantiates: its literal edit, its relation, its anchored relation."""
    o, n = edit_tokens(a, list(m))
    keys = [("lit", (o, n))]
    if len(o) <= R.MAXSPAN and len(n) <= R.MAXSPAN:
        rel = R.relation(list(o), list(n), scope)
        if R.generative(rel):
            keys.append(("rel", rel))
        at = _anchor(a, list(m), o, n)
        if at is not None:
            ctx = R.relation(list(at[0]), list(at[1]), scope)
            if R.generative(ctx):
                keys.append(("ctx", ctx))
    return keys


class Domain:
    """raw: (net, line, scope[, lang]) - default: the standard library. hard: the harder operator set."""

    def __init__(self, raw=None, hard=False):
        raw = corpus() if raw is None else raw
        self.lines = []
        for item in raw:
            net, l, scope = item[:3]
            lang = item[3] if len(item) > 3 else "py"
            a0 = R.toks(l, lang)
            if not a0:
                continue
            a = ["^"] + a0                                 # the start of the line, so an edit there has an anchor
            refs = {("^",) + m: op for m, op in mutants(a0, lang, hard).items()}
            own = {}
            for m in refs:
                for k in neurons_of(a, m, scope):
                    own.setdefault(k, set()).add(m)
            ts = set(a)
            keys = ts | ({"$INT"} if any(R.is_int(t) for t in a) else set()) | \
                ({"$ID"} if any(R.is_ident(t) for t in a) else set())
            self.lines.append(dict(net=net, lang=lang, a=a, scope=tuple(scope), refs=refs, own=own, tokset=ts,
                                   keys=keys))
        self.nets = sorted({x["net"] for x in self.lines})
        self.cache = {}

    def gen(self, k, i):
        """The candidates neuron k proposes on line i (a set of token tuples); non-empty results cached."""
        key = (k, i)
        hit = self.cache.get(key)
        if hit is not None:
            return hit
        x = self.lines[i]
        kind, (old, new) = k
        lit_old = [t for t in old if not t.startswith(("$", "~", "@"))]
        if lit_old and not set(lit_old) <= x["tokset"]:
            return frozenset()
        c = set(R.generate((old, new), x["a"], list(x["scope"]), cap=400))
        c.discard(tuple(x["a"]))
        c = frozenset(c)
        if c:
            self.cache[key] = c
        return c


def nkey(k):
    """A token a line must contain for neuron k to fire there."""
    old = k[1][0]
    lit = [t for t in old if not t.startswith(("$", "~", "@"))]
    if lit:
        return lit[0]
    if any(t.startswith("$N") for t in old):
        return "$INT"
    if any(t.startswith("$I") for t in old):
        return "$ID"
    return "$ANY"


class Index:
    def __init__(self, neurons):
        self.by = defaultdict(list)
        for k in neurons:
            self.by[nkey(k)].append(k)

    def add(self, k):
        self.by[nkey(k)].append(k)

    def on(self, x):
        out = list(self.by.get("$ANY", ()))
        for t in x["keys"]:
            out += self.by.get(t, ())
        return out


def split(dom, seed):
    rng = random.Random(1000 + seed)
    nets = dom.nets[:]
    rng.shuffle(nets)
    held = set(nets[:len(nets) // 4])
    train = [i for i, x in enumerate(dom.lines) if x["net"] not in held]
    test = [i for i, x in enumerate(dom.lines) if x["net"] in held]
    return train, rng.sample(test, min(N_EVAL, len(test))), held


def junk_lesson(dom, i, rng, vocab):
    """A wrong lesson for line i: one random token replaced by a random token of the corpus - what the body is told
    is a mutant, though no operator makes it."""
    x = dom.lines[i]
    a = x["a"]
    j = rng.randrange(1, len(a))
    m = tuple(a[:j] + [rng.choice(vocab)] + a[j + 1:])
    own = {}
    for k in neurons_of(a, m, list(x["scope"])):
        own.setdefault(k, set()).add(m)
    return {m: "JUNK"}, own


def teach(dom, taught, law, kinds, cheap_t=None, costly_t=None, noise=0.0, noise_seed=0):
    """The swarm learns from the taught lines in order; returns the neurons it ends with as active. noise: the share
    of lessons replaced by a random wrong edit (the body believes them)."""
    lessons = {}
    if noise:
        rng = random.Random(noise_seed)
        vocab = [t for x in dom.lines[:20000] for t in x["a"][1:]]
        for i in taught:
            if rng.random() < noise:
                lessons[i] = junk_lesson(dom, i, rng, vocab)
    refs_of = lambda i: lessons[i][0] if i in lessons else dom.lines[i]["refs"]
    own_of = lambda i: lessons[i][1] if i in lessons else dom.lines[i]["own"]
    seen = set()
    for i in taught:
        for k in own_of(i):
            if k[0] in kinds:
                seen.add(k)
    idx = Index(seen)
    fan_n, fan_s, junk_s = defaultdict(int), defaultdict(int), defaultdict(int)
    for i in taught:                                      # the body measures cost on the taught material
        x = dom.lines[i]
        refs = refs_of(i)
        for k in idx.on(x):
            c = dom.gen(k, i)
            if c:
                fan_n[k] += 1
                fan_s[k] += len(c)
                junk_s[k] += sum(1 for m in c if m not in refs)
    fan = {k: fan_s[k] / fan_n[k] if fan_n[k] else 0 for k in seen}
    junk = {k: junk_s[k] / len(taught) for k in seen}
    ch, co = cheap_t or RL.CHEAP, costly_t or RL.COSTLY
    cheap = {k: fan[k] <= ch[0] and junk[k] <= ch[1] for k in seen}
    costly = {k: fan[k] > co[0] or junk[k] > co[1] for k in seen}
    if law is None:                                       # first sight, no law
        return seen
    level, nets, fires, good = defaultdict(int), defaultdict(set), defaultdict(int), defaultdict(int)
    known, indexed = Index(()), set()
    for i in taught:
        x = dom.lines[i]
        before = dict(level)
        refs = refs_of(i)
        own = {k for k in own_of(i) if k[0] in kinds}
        touch = {k for k in known.on(x) if before.get(k, 0) >= 1 and dom.gen(k, i)} | own
        for k in touch:
            c = dom.gen(k, i)
            hit = any(m in refs for m in c)
            if before.get(k, 0) >= 2 and c:
                fires[k] += 1
                good[k] += hit
            L = level[k]
            FIRE = int(k in own)
            NEWNET = int(FIRE and x["net"] not in nets[k])
            PRED = int(before.get(k, 0) >= 1 and hit)
            BAR = int(L >= 1 and fires[k] >= BARREN_FIRES and good[k] / fires[k] < RL.BARREN_YIELD)
            w = L | FIRE << 2 | NEWNET << 3 | PRED << 4 | int(cheap[k]) << 5 | int(costly[k]) << 6 | BAR << 7
            if k not in indexed:                          # every neuron the law has touched can fire later
                known.add(k)
                indexed.add(k)
            level[k] = law(w) & 3
            if FIRE:
                nets[k].add(x["net"])
    return {k for k, v in level.items() if v >= 2}


def evaluate(dom, active, test):
    real = gen_real = gen_all = 0
    by_op, by_op_hit = Counter(), Counter()
    idx = Index(active)
    for i in test:
        x = dom.lines[i]
        cands = set()
        for k in idx.on(x):
            cands |= dom.gen(k, i)
        refs = x["refs"]
        real += len(refs)
        hit = cands & set(refs)
        gen_real += len(hit)
        gen_all += len(cands)
        for m, op in refs.items():
            by_op[op] += 1
            by_op_hit[op] += m in hit
    return dict(cov=gen_real / max(1, real), prec=gen_real / max(1, gen_all), cand=gen_all / len(test),
                by_op={op: by_op_hit[op] / by_op[op] for op in by_op}, n_op=dict(by_op))


JUNK = (30, 2.0)          # the domain's own cost budget: a neuron spraying more than 2 non-mutants per line is costly


def main() -> int:
    dom = Domain()
    law = RL.load_law(str(Path(RL.__file__).parent / "kernels" / "relate_v1.c"))
    n_mut = sum(len(x["refs"]) for x in dom.lines)
    print(f"  {len(dom.lines):,} code lines in {len(dom.nets)} nets; {n_mut:,} mutants", flush=True)
    policies = [("literal edits, first sight (memorisation, no law)", None, ("lit",), None),
                ("relations, first sight (no law)", None, ("rel",), None),
                ("RELATE law, as in the bug runs", law, ("lit", "rel"), None),
                ("RELATE law + literal edits and anchored relations + the domain's junk budget", law, ("lit", "ctx"), JUNK),
                ("**RELATE law + anchored relations only + the junk budget**", law, ("ctx",), JUNK)]
    res = defaultdict(list)
    ceil = defaultdict(list)
    for seed in SEEDS:
        train, test, held = split(dom, seed)
        order = random.Random(seed).sample(train, max(KS))
        need = set()
        for i in test:
            need |= set(dom.lines[i]["own"])
        for label, kinds in (("relations", ("rel",)), ("anchored relations", ("ctx",)),
                             ("relations + anchored", ("rel", "ctx"))):
            ceil[label].append(evaluate(dom, {k for k in need if k[0] in kinds}, test))
        for kk in KS:
            for name, lw, kinds, junk in policies:
                act = teach(dom, order[:kk], lw, kinds, costly_t=junk)
                ev = evaluate(dom, act, test)
                ev["active"] = len(act)
                res[(name, kk)].append(ev)
            print(f"  seed {seed} k={kk:>5} " + " ".join(
                f"{res[(n, kk)][-1]['cov']:.3f}/{res[(n, kk)][-1]['prec']:.3f}" for n, _, _, _ in policies), flush=True)
    m = lambda name, kk, f: statistics.mean(e[f] for e in res[(name, kk)])
    best = policies[-1][0]
    out = ["# A whole domain, taught - code mutation", "",
           "Generated by `neo4d/domain_mutation.py`. **The domain**: the standard mutation operators (ROR, AOR, ASR, "
           "LCR, BCR, NEG, CRP, BRK, RET - the operator sets of mutmut, PIT and Major) applied to every code line of "
           f"the Python standard library on this machine: **{len(dom.lines):,} lines in {len(dom.nets)} modules, "
           f"{n_mut:,} mutants**. A reference mutator is the teacher and the ground truth.", "",
           f"**The experiment**: a quarter of the modules are held out. The swarm is taught k lines from the rest, "
           "each with all its mutants; every mutant is an event for its neurons, and the RELATE law "
           "(`neo4d/kernels/relate_v1.c`, unchanged from the bug runs) sets every neuron's strength. Measured on "
           f"{N_EVAL:,} lines of the **held-out modules it never saw**, {len(SEEDS)} different splits averaged:", "",
           "- **coverage**: the share of their real mutants the active neurons generate exactly - did it learn the "
           "domain?",
           "- **precision**: the share of generated candidates that are real mutants - does it mutate well, or "
           "spray?", "",
           "## Coverage as the teaching grows", "",
           "| taught lines | " + " | ".join(n for n, _, _, _ in policies) + " |",
           "|---|" + "---|" * len(policies)]
    for kk in KS:
        out.append(f"| {kk:,} | " + " | ".join(f"{m(n, kk, 'cov'):.1%}" for n, _, _, _ in policies) + " |")
    out += ["", "Generalisation ceiling - every relation the held-out mutants need, already known (no literal edit "
            "memorised from the test lines): " + "; ".join(
                f"{label} **{statistics.mean(e['cov'] for e in v):.1%}** at {statistics.mean(e['prec'] for e in v):.1%}"
                f" precision" for label, v in ceil.items()) + ".", "",
            "## How well it mutates - precision and candidates per line", "",
            "| taught lines | policy | coverage | precision | candidates per line | active neurons |",
            "|---|---|---|---|---|---|"]
    for kk in (100, 1000, 10000):
        for n, _, _, _ in policies:
            out.append(f"| {kk:,} | {n} | {m(n, kk, 'cov'):.1%} | {m(n, kk, 'prec'):.1%} | "
                       f"{m(n, kk, 'cand'):.1f} | {m(n, kk, 'active'):.0f} |")
    n_op = res[(best, max(KS))][0]["n_op"]
    tot = sum(n_op.values())
    out += ["", f"## What it learned, operator by operator ({best.strip('*')})", "",
            "| operator | share of the domain | covered at 10 taught | 100 | 1,000 | 10,000 |", "|---|---|---|---|---|---|"]
    for op in sorted(n_op, key=lambda o: -n_op[o]):
        cells = [f"{statistics.mean(e['by_op'].get(op, 0) for e in res[(best, kk)]):.0%}" for kk in (10, 100, 1000, 10000)]
        out.append(f"| {op} | {n_op[op] / tot:.1%} | " + " | ".join(cells) + " |")
    mix, lit, fs = policies[3][0], policies[0][0], policies[1][0]
    cm_ctx = statistics.mean(e["cov"] for e in ceil["anchored relations"])
    cp_ctx = statistics.mean(e["prec"] for e in ceil["anchored relations"])
    ret = statistics.mean(e["by_op"].get("RET", 0) for e in res[(best, max(KS))])
    out += ["", "**What this shows.**", "",
            f"- **It generalises to code it never saw, and expands with scale.** With anchored relations, coverage of "
            f"the held-out modules' mutation domain grows from {m(best, 100, 'cov'):.0%} at 100 taught lines to "
            f"{m(best, 1000, 'cov'):.0%} at 1,000 and {m(best, 10000, 'cov'):.1%} at 10,000 - against a ceiling of "
            f"{cm_ctx:.1%} - while precision stays between {min(m(best, k, 'prec') for k in (100, 1000, 10000)):.0%} "
            f"and {max(m(best, k, 'prec') for k in (100, 1000, 10000)):.0%} (the ceiling's own precision is "
            f"{cp_ctx:.0%}).",
            f"- **Fast or clean.** Literal edits and context-free relations learn faster ({m(lit, 100, 'cov'):.0%}-"
            f"{m(fs, 100, 'cov'):.0%} at 100 lines) but spray: under {max(m(lit, 100, 'prec'), m(fs, 100, 'prec')) + 0.01:.0%}"
            f" of what they propose is a real mutant. With literal edits beside the anchored relations the law starts "
            f"at {m(mix, 100, 'prec'):.0%} precision and decays to {m(mix, 10000, 'prec'):.0%} by 10,000 lines - each "
            "cheap literal is only slightly wrong (a `-` that is unary), the law spares cheap neurons by design, and "
            "the slight errors add up. Anchored relations alone learn slower and stay clean, and scale lets them "
            "catch up.",
            f"- **Memorisation does not transfer**: literal edits alone stop at {m(lit, 10000, 'cov'):.0%} with "
            f"{m(lit, 10000, 'prec'):.0%} precision - a number or a name learned in one module is rarely the one "
            "another needs.",
            f"- **Where it stops**: `return <value> -> return None` (RET) at {ret:.0%}. A long return value is an edit "
            "of more than 3 tokens, which no relation here represents.", "",
            "**What this does not show.** The domain is defined by token-level operators, which the relation "
            "abstraction suits; a domain whose rules need wider context is harder. The cost budget is the body's: the "
            "bug runs' budget is in the third column, the domain's (at most 2 non-mutants per line) in the last two. "
            "The law is the same in every column. The teacher skips hexadecimal, binary and exponent literals and "
            "never touches comments or docstrings."]
    (REPO / "results" / "DOMAIN_MUTATION.md").write_text("\n".join(out) + "\n")
    print("\n".join(out))
    return 0


if __name__ == "__main__":
    sys.exit(main())
