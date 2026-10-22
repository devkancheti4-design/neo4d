"""Beyond bug fixes: a local model searching a codebase, with neo4d as its brain - does neo4d improve it?

THE WORK. Code search: someone describes a function in their own words, and the answer is the function. The
descriptions are real: the sentences of each function's own docstring, written by its authors. The search index holds
only the code - names, parameters, the identifiers and strings in the body - with every docstring removed, so a
description never matches itself. After each search the right function is revealed (as when someone opens the result
they wanted), and neo4d learns.

    pass 1   every documented function is looked for once, by its first sentence, in a seeded order
    pass 2   later, functions whose docstring has another sentence are looked for AGAIN, by that other sentence -
             the same thing, found a second time, in different words

    codebases   designed on click, rich (pip's vendored copy) and pytest; then run once, unchanged, on three codebases
                it was never tuned on: pip's own code, requests (pip's vendored copy), numpy
    search      BM25 over the code
    neo4d       two kinds of link, each a neuron whose strength the RELATE v2 law sets:
                vocabulary  a description word missing from the answer's code -> a word of the answer's NAME
                            ("environment" -> env, "terminal" -> term)
                memory      a pair of description words -> the function they led to
                FIRE when the lesson exhibits the link, NEWNET when it does so in a file it was not seen in before,
                PREDICTED when it would have ranked the answer higher, CHEAP / COSTLY by how many functions it points at
                and how many of them are wrong (the mutation domain's own rule: cheap = at most 5, at most 0.5 wrong),
                BARREN when it keeps pointing the wrong way. Active links add to the query.

THE SOLVERS, on the same stream:

    search alone                BM25, top result
    model + search              the model picks from BM25's top 8 (it sees each candidate's signature and first lines)
    neo4d alone                 BM25 with neo4d's links, top result - no model
    model + neo4d               the model picks from neo4d's top 8
    neo4d decides, model if unsure
                                neo4d answers alone when its own record says it can be trusted (its top score stands
                                clear of the next by a margin at which, so far in the stream, it was right 90% of the
                                time); otherwise the model picks from neo4d's top 8

    python -m neo4d.local_search [--model phi4-mini] [--cap 250]    -> results/LOCAL_SEARCH.md
    python -m neo4d.local_search --dump prompts.md                  -> the comparison sample's prompts, no answers
    python -m neo4d.local_search --compare answers.json             -> adds Claude on that sample
"""
from __future__ import annotations

import ast
import itertools
import json
import math
import random
import re
import sys
import sysconfig
import time
import urllib.request
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np

from neo4d import KERNELS, REPO
from neo4d import domain_mutation as D
from neo4d import relate_live as RL
from neo4d.local_model import OLLAMA

SITE = Path(sysconfig.get_paths()["purelib"])
DESIGN = (("click", REPO / "bench" / "click" / "src" / "click", ()),
          ("rich", SITE / "pip" / "_vendor" / "rich", ()),
          ("pytest", SITE / "_pytest", ()))
HELD_OUT = (("pip", SITE / "pip", ("_vendor",)),
            ("requests", SITE / "pip" / "_vendor" / "requests", ()),
            ("numpy", SITE / "numpy", ("tests", "_vendored")))
TOP = 8
TRUST = 0.9
SAMPLE = 5                       # pass-2 tasks per codebase for the comparison with Claude
BUILD = REPO / ".build"
STOP = set("""a an the of to in for and or is are be been being this that these those it its with as by on at from if
not no will can may should would which when where what who whose how than then there their they them we you your our
any all each other such only also into onto over under about after before while but so do does done one two use used
using via e.g i.e etc return returns given otherwise else either whether here just more most less same like""".split())
SKIP = (":", "..", ">>>", "Args", "Arguments", "Returns", "Return", "Raises", "Parameters", "Yields", "Example",
        "Examples", "See Also", "Notes", "References", "Warns", "Other", "Attributes", "Usage", "-", "*", "|", "#")


# ------------------------------------------------------------------------------------------------ words and code

def parts(word):
    """Identifier or word -> lowercase sub-words (snake_case and CamelCase split), the whole kept too."""
    out = [p.lower() for p in re.findall(r"[A-Z]+(?=[A-Z][a-z])|[A-Z]?[a-z]+|[A-Z]+|\d+", word)]
    if len(out) > 1:
        out.append(word.lower().replace("_", ""))
    return out


def stem(w):
    if w.endswith("sses"):
        return w[:-2]
    if w.endswith("ies") and len(w) > 4:
        return w[:-3] + "y"
    if w.endswith("s") and not w.endswith(("ss", "us", "is")) and len(w) > 3:
        return w[:-1]
    return w


def words(text):
    return [stem(p) for tok in re.findall(r"[A-Za-z_][A-Za-z0-9_]*", text) for p in parts(tok)
            if len(p) > 2 and p.isalpha() and stem(p) not in STOP]


def descriptions(doc):
    """The docstring's sentences that describe: prose paragraphs only, each sentence with 3+ content words."""
    out = []
    for para in re.split(r"\n\s*\n", doc.strip()):
        p = para.strip()
        if not p or p.startswith(SKIP) or "::" in p or re.search(r"^\s*[-=]{3,}\s*$", p, re.M):
            continue
        for s in re.split(r"(?<=[.!?])\s+", " ".join(p.split())):
            if len(set(words(s))) >= 3:
                out.append(s[:300])
        if len(out) >= 4:
            break
    return out


def is_doc(node):
    return isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant) and isinstance(node.value.value, str)


def code_tokens(fn, cls, stem_of_file):
    """Everything a code index sees: names, parameters, identifiers and strings in the body - no docstrings."""
    toks = parts(fn.name) + (parts(cls) if cls else []) + parts(stem_of_file)
    docs = {id(n.value) for n in ast.walk(fn) if is_doc(n)}
    for n in ast.walk(fn):
        if id(n) in docs:
            continue
        if isinstance(n, ast.Name):
            toks += parts(n.id)
        elif isinstance(n, ast.Attribute):
            toks += parts(n.attr)
        elif isinstance(n, ast.arg):
            toks += parts(n.arg)
        elif isinstance(n, ast.keyword) and n.arg:
            toks += parts(n.arg)
        elif isinstance(n, ast.Constant) and isinstance(n.value, str) and len(n.value) < 200:
            toks += [p for t in re.findall(r"[A-Za-z]{3,}", n.value) for p in parts(t)]
    return Counter(stem(t) for t in toks if len(t) > 1)


def name_words(name):
    """The sub-words of a function's name (class included), without the joined whole."""
    return {stem(p.lower()) for p in re.findall(r"[A-Z]+(?=[A-Z][a-z])|[A-Z]?[a-z]+|[A-Z]+", name) if len(p) > 1}


def shown(fn, lines, cls, rel):
    """What the model is shown for a candidate: where it is, its signature, its first lines of code."""
    body = [s for s in fn.body if not is_doc(s)]
    sig = " ".join(l.strip() for l in lines[fn.lineno - 1:max(fn.lineno, fn.body[0].lineno - 1)])
    sig = re.sub(r"\s+", " ", sig)[:160]
    head = []
    if body:
        for l in lines[body[0].lineno - 1:]:
            if l.strip() and not l.strip().startswith("#"):
                head.append(l.strip()[:100])
            if len(head) == 3:
                break
    return f"`{rel}` `{cls + '.' if cls else ''}{fn.name}`\n    {sig}\n" + "".join(f"    {h}\n" for h in head)


class Codebase:
    def __init__(self, name, root, exclude, cap, seed=2026):
        self.name = name
        funcs = []
        for p in sorted(root.rglob("*.py")):
            if any(x in p.relative_to(root).parts for x in exclude):
                continue
            src = p.read_text(errors="replace")
            try:
                tree = ast.parse(src)
            except SyntaxError:
                continue
            lines = src.split("\n")
            rel = str(p.relative_to(root))
            for cls_node in [tree] + [n for n in ast.walk(tree) if isinstance(n, ast.ClassDef)]:
                cls = getattr(cls_node, "name", "")
                for fn in cls_node.body:
                    if not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
                        continue
                    name = f"{cls + '.' if cls else ''}{fn.name}"
                    funcs.append(dict(file=rel, name=name, desc=descriptions(ast.get_docstring(fn) or ""),
                                      named=name_words(name), toks=code_tokens(fn, cls, p.stem),
                                      show=shown(fn, lines, cls, rel)))
        self.funcs = funcs
        key = lambda f, d: " ".join(sorted(set(words(funcs[f]["desc"][d]))))
        seen = Counter(key(i, d) for i, f in enumerate(funcs) for d in range(len(f["desc"])))
        first = [i for i, f in enumerate(funcs) if f["desc"] and seen[key(i, 0)] == 1]
        random.Random(seed).shuffle(first)
        first = first[:cap]
        again = [i for i in first if len(funcs[i]["desc"]) > 1 and seen[key(i, 1)] == 1 and key(i, 1) != key(i, 0)]
        random.Random(seed + 1).shuffle(again)
        self.tasks = [(f, 0) for f in first] + [(f, 1) for f in again]
        self.n1 = len(first)
        self.n = len(funcs)
        self.dl = np.array([sum(f["toks"].values()) for f in funcs], float)
        self.avg = self.dl.mean()
        self.post = defaultdict(list)
        for i, f in enumerate(funcs):
            for t, c in f["toks"].items():
                self.post[t].append((i, c))
        self.df = {t: len(v) for t, v in self.post.items()}
        self._col = {}

    def col(self, t, k1=1.2, b=0.75):
        """A term's BM25 contribution to every function. "#i" is a memory token: function i, as if it held one rare word."""
        if t not in self._col:
            if t.startswith("#"):
                post = [(int(t[1:]), 1)]
            else:
                post = self.post.get(t, [])
            v = np.zeros(self.n)
            df = len(post)
            if df:
                idf = math.log(1 + (self.n - df + 0.5) / (df + 0.5))
                for i, c in post:
                    v[i] = idf * c * (k1 + 1) / (c + k1 * (1 - b + b * self.dl[i] / self.avg))
            self._col[t] = v
        return self._col[t]

    def score(self, weights):
        s = np.zeros(self.n)
        for t, w in weights.items():
            s += w * self.col(t)
        return s

    @staticmethod
    def ranked(s):
        return sorted(range(len(s)), key=lambda i: (-s[i], i))


# ------------------------------------------------------------------------------------------------- the brain

class Brain:
    """neo4d's links from description words to code; the RELATE v2 law sets each link's strength.

    links   "name" (into the answer's name) or "body" (into any token of the answer's code - the first design)
    cheap   "domain" (at most 5 functions pointed at and at most 0.5 of them wrong) or "fan" (at most 5 - the first design)
    memory  "pairs" (two description words -> the function), "words" (one word -> the function) or None
    """

    def __init__(self, law, links="name", cheap="domain", memory="pairs"):
        self.law, self.links_of, self.cheap, self.memory = law, links, cheap, memory
        self.level = defaultdict(int)
        self.nets = defaultdict(set)
        self.fires = defaultdict(int)
        self.good = defaultdict(int)
        self.by_w = defaultdict(set)

    def keys(self, ws):
        ws = sorted(set(ws))
        return {"+".join(p) for p in itertools.combinations(ws, 2)} if self.memory == "pairs" else set(ws)

    def links(self, ws):
        keys = set(ws) | (self.keys(ws) if self.memory else set())
        return [(w, t) for w in keys for t in self.by_w[w] if self.level[(w, t)] >= 2]

    def expand(self, ws):
        weights = {w: 1.0 for w in ws}
        for w, t in self.links(ws):
            weights[t] = min(1.0, weights.get(t, 0.0) + (0.5 if self.level[(w, t)] == 2 else 1.0))
        return weights

    def learn(self, cb, f, ws):
        ws, fn = set(ws), cb.funcs[f]
        have = set(fn["toks"])
        into = have if self.links_of == "body" else fn["named"]
        own = {(w, t) for w in ws - have for t in into if t != w}
        if self.memory:
            own |= {(k, f"#{f}") for k in self.keys(ws)}
        fired = set(self.links(ws))
        for k in fired:
            self.fires[k] += 1
            self.good[k] += k[1] == f"#{f}" if k[1].startswith("#") else k[1] in have
        base = cb.score({w: 1.0 for w in ws})
        r0 = int((base > base[f]).sum())
        for k in own | fired:
            L = self.level[k]
            FIRE = int(k in own)
            NEWNET = int(FIRE and fn["file"] not in self.nets[k])
            PRED = 0
            if L >= 1 and FIRE:
                s = base + 0.5 * cb.col(k[1])
                PRED = int((s > s[f]).sum() < r0)
            fan = 1 if k[1].startswith("#") else cb.df.get(k[1], 0)
            if self.cheap == "domain":
                cheap = fan <= RL.CHEAP[0] and fan - 1 <= RL.CHEAP[1]
            else:
                cheap = fan <= RL.CHEAP[0]
            costly = fan > RL.COSTLY[0]
            BAR = int(L >= 1 and self.fires[k] >= D.BARREN_FIRES and self.good[k] / self.fires[k] < RL.BARREN_YIELD)
            x = L | FIRE << 2 | NEWNET << 3 | PRED << 4 | int(cheap and not costly) << 5 | int(costly) << 6 | BAR << 7
            self.level[k] = self.law(x) & 3
            if FIRE:
                self.nets[k].add(fn["file"])
                self.by_w[k[0]].add(k[1])


# -------------------------------------------------------------------------------------------------- the model

def prompt_of(cb, f, d, short):
    cands = "".join(f"{n + 1}. {cb.funcs[i]['show']}" for n, i in enumerate(short))
    return (f"You are searching the Python codebase `{cb.name}` for one function. Which candidate matches this "
            f"description?\n\n\"{cb.funcs[f]['desc'][d]}\"\n\nCandidates:\n{cands}\n"
            "Reply with only the number of the best candidate.")


def ask(model, prompt, cache):
    if prompt not in cache:
        body = json.dumps({"model": model, "prompt": prompt, "stream": False,
                           "options": {"temperature": 0.0, "num_predict": 8, "seed": 1000, "num_ctx": 4096}}).encode()
        req = urllib.request.Request(OLLAMA, data=body, headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=300) as r:
            reply = json.loads(r.read())["response"]
        m = re.search(r"\d+", reply)
        cache[prompt] = int(m.group(0)) if m else 0
    return cache[prompt]


def pick(short, n):
    return short[n - 1] if 1 <= n <= len(short) else None


class Gate:
    """When may neo4d answer alone? Its record so far: the smallest score margin at which it was right 90% of the time."""

    def __init__(self):
        self.hist = []

    def trusted(self, margin):
        ok = n = 0
        best = None
        for m, right in sorted(self.hist, reverse=True):
            n += 1
            ok += right
            if n >= 10 and ok / n >= TRUST:
                best = m
        return best is not None and margin >= best


def margin_of(s, r):
    return float(s[r[0]] / max(1e-9, s[r[1]])) if len(r) > 1 else 99.0


# ---------------------------------------------------------------------------------------------------- the run

def stream(cb, brain, model=None, cache=None, sample=()):
    gate = Gate()
    rows = []
    for n, (f, d) in enumerate(cb.tasks):
        ws = words(cb.funcs[f]["desc"][d])
        sb = cb.score({w: 1.0 for w in ws})
        se = cb.score(brain.expand(ws))
        rb, re_ = cb.ranked(sb), cb.ranked(se)
        shb, she = rb[:TOP], re_[:TOP]
        mg = margin_of(se, re_)
        trusted = gate.trusted(mg)
        row = dict(n=n, again=d > 0, search=rb[0] == f, neo=re_[0] == f, rec_b=f in shb, rec_e=f in she,
                   trusted=trusted)
        if model:
            row["model"] = pick(shb, ask(model, prompt_of(cb, f, d, shb), cache)) == f
            row["model_neo"] = pick(she, ask(model, prompt_of(cb, f, d, she), cache)) == f
            row["calls_gate"] = 0 if trusted else 1
            row["gated"] = row["neo"] if trusted else row["model_neo"]
        if n in sample:
            row["prompts"] = (prompt_of(cb, f, d, shb), prompt_of(cb, f, d, she))
            row["truth"] = (shb.index(f) + 1 if f in shb else 0, she.index(f) + 1 if f in she else 0)
        rows.append(row)
        gate.hist.append((mg, row["neo"]))
        brain.learn(cb, f, ws)
        if model and (n + 1) % 100 == 0:
            print(f"  {cb.name}: {n + 1}/{len(cb.tasks)}  search {sum(r['search'] for r in rows)}  "
                  f"model {sum(r['model'] for r in rows)}  model+neo4d {sum(r['model_neo'] for r in rows)}", flush=True)
    return rows


def pct(rows, key):
    return sum(bool(r.get(key)) for r in rows) / max(1, len(rows))


VARIANTS = (("first design: links into any code token, cheap = at most 5 functions", dict(links="body", cheap="fan", memory=None)),
            ("links into any code token, the domain's cheap rule", dict(links="body", cheap="domain", memory=None)),
            ("vocabulary links into the name, the domain's cheap rule", dict(links="name", cheap="domain", memory=None)),
            ("vocabulary links + memory links keyed on one word", dict(links="name", cheap="domain", memory="words")),
            ("**final: vocabulary links + memory links keyed on a pair of words**", dict(links="name", cheap="domain", memory="pairs")))


def main() -> int:
    args = sys.argv[1:]
    model = args[args.index("--model") + 1] if "--model" in args else "phi4-mini"
    cap = int(args[args.index("--cap") + 1]) if "--cap" in args else 250
    law = RL.load_law(str(KERNELS / "relate_v2.c"))
    if "--compare" in args:
        return compare(args[args.index("--compare") + 1], model)
    if "--dump" in args:
        print(dump_prompts(args[args.index("--dump") + 1]), "prompts")
        return 0
    BUILD.mkdir(exist_ok=True)
    cache_p = BUILD / f"local_search_cache_{model.replace(':', '_')}.json"
    cache = json.loads(cache_p.read_text()) if cache_p.exists() else {}
    t0 = time.time()
    cbs = [(Codebase(name, root, ex, cap), name in dict((n, 0) for n, _, _ in HELD_OUT)) for name, root, ex in DESIGN + HELD_OUT]
    print(f"  codebases read ({time.time() - t0:.0f}s)", flush=True)
    out = ["# Beyond bug fixes: a local model searching a codebase, with neo4d as its brain", "",
           f"Generated by `neo4d/local_search.py`. Local model: **{model}** (ollama, on this machine). Each task: a "
           "function described in plain words - a sentence of its own docstring, written by its authors - and the answer "
           "is that function. The search index holds the code only (names, parameters, identifiers and strings), every "
           "docstring removed, so a description never matches itself. After each search the right function is revealed "
           "and neo4d learns; the RELATE v2 law decides every link.", "",
           "- **pass 1, first time:** every documented function looked for once, by its first sentence.",
           "- **pass 2, again in other words:** later, the functions whose docstring has another sentence are looked for "
           "again by that sentence - the same thing found a second time, described differently.", "",
           "neo4d was designed on click, rich and pytest, then run once, unchanged, on pip, requests and numpy.", "",
           "| codebase | | functions in the index | pass 1 searches | pass 2 searches |", "|---|---|---|---|---|"]
    out += [f"| {cb.name} | {'held out' if held else 'design'} | {cb.n:,} | {cb.n1} | {len(cb.tasks) - cb.n1} |"
            for cb, held in cbs]
    results, claude = [], []
    for cb, held in cbs:
        sample = set(random.Random(7).sample(range(cb.n1, len(cb.tasks)), min(SAMPLE, len(cb.tasks) - cb.n1)))
        rows = stream(cb, Brain(law), model, cache, sample)
        cache_p.write_text(json.dumps(cache))
        results.append((cb, held, rows))
        for r in rows:
            if "prompts" in r:
                claude.append(dict(codebase=cb.name, n=r["n"], prompts=r["prompts"], truth=r["truth"],
                                   model=r["model"], model_neo=r["model_neo"], neo=r["neo"], trusted=r["trusted"]))
        print(f"  {cb.name} done ({time.time() - t0:.0f}s)", flush=True)
    SOLVERS = (("search alone", "search", None), (f"{model} + search", "model", "all"), ("neo4d alone", "neo", None),
               (f"{model} + neo4d", "model_neo", "all"), (f"neo4d decides, {model} if unsure", "gated", "gate"))

    def calls(rows, how):
        return 0 if how is None else len(rows) if how == "all" else sum(r["calls_gate"] for r in rows)

    for title, keep in (("Held-out codebases (pip, requests, numpy) - never tuned on", True),
                        ("Design codebases (click, rich, pytest)", False)):
        rows = [r for cb, held, rs in results if held == keep for r in rs]
        p1, p2 = [r for r in rows if not r["again"]], [r for r in rows if r["again"]]
        out += ["", f"## {title}", "",
                f"| solver | pass 1: first time | **pass 2: again, in other words** | {model} calls |", "|---|---|---|---|"]
        for label, key, how in SOLVERS:
            out.append(f"| {label} | {pct(p1, key):.1%} | **{pct(p2, key):.1%}** | {calls(rows, how)} of {len(rows)} |")
        out += ["", f"The right function among the {TOP} candidates the model is shown: pass 1 search {pct(p1, 'rec_b'):.1%}, "
                f"neo4d {pct(p1, 'rec_e'):.1%}; pass 2 search {pct(p2, 'rec_b'):.1%}, neo4d {pct(p2, 'rec_e'):.1%}."]
    out += ["", "## Codebase by codebase", "",
            f"| codebase | search, pass 1 / 2 | neo4d, pass 1 / 2 | {model} + search, pass 1 / 2 | {model} + neo4d, pass 1 / 2 | "
            f"neo4d decides, pass 1 / 2 | {model} calls, neo4d decides |", "|---|---|---|---|---|---|---|"]
    for cb, held, rows in results:
        p1, p2 = rows[:cb.n1], rows[cb.n1:]
        out.append(f"| {cb.name}{' (held out)' if held else ''} | " + " | ".join(
            f"{pct(p1, k):.0%} / {pct(p2, k):.0%}" for k in ("search", "neo", "model", "model_neo", "gated"))
            + f" | {calls(rows, 'gate')} of {len(rows)} |")
    out += ["", "## What was tried, without the model", "",
            "neo4d alone against search alone, top result. The first three designs were tried on the design codebases "
            "and did not help; the held-out codebases were run only with the final design's rules fixed.", "",
            "| design | design codebases, pass 1 | design, pass 2 | held out, pass 1 | held out, pass 2 |",
            "|---|---|---|---|---|"]
    base = {k: [r for cb, held, rs in results if held == k for r in rs] for k in (False, True)}
    out.append("| search alone | " + " | ".join(f"{pct([r for r in base[k] if r['again'] == a], 'search'):.1%}"
                                              for k in (False, True) for a in (False, True)) + " |")
    for label, opts in VARIANTS:
        cells = []
        for k in (False, True):
            rows = [r for cb, held in cbs if held == k for r in stream(cb, Brain(law, **opts))]
            cells += [f"{pct([r for r in rows if not r['again']], 'neo'):.1%}", f"{pct([r for r in rows if r['again']], 'neo'):.1%}"]
        out.append(f"| {label} | " + " | ".join(cells) + " |")
    out += ["", "**What this does not show.** The descriptions are docstrings, written by the code's authors, not "
            "questions from users. Pass 2's descriptions are other sentences of the same docstring, which often share "
            "words with the first - that shared vocabulary is what memory links use, and real repeated searches may share "
            "more or less. The right answer is revealed after every search; in real use it comes from what the person "
            "opens, and some of that signal is lost."]
    (REPO / "results" / "LOCAL_SEARCH.md").write_text("\n".join(out) + "\n")
    (BUILD / "local_search_claude.json").write_text(json.dumps(claude))
    print("\n".join(out))
    return 0


def dump_prompts(path):
    """The comparison sample's prompts, without answers, for Claude to answer: one per distinct prompt."""
    claude = json.loads((BUILD / "local_search_claude.json").read_text())
    seen, out = {}, []
    for c in claude:
        for p in c["prompts"]:
            if p not in seen:
                seen[p] = len(seen)
                out += [f"### prompt {seen[p]}", p, ""]
    Path(path).write_text("\n".join(out))
    return len(seen)


def compare(answers_path, model):
    claude = json.loads((BUILD / "local_search_claude.json").read_text())
    answers = json.loads(Path(answers_path).read_text())
    seen = {}
    for c in claude:
        for p in c["prompts"]:
            seen.setdefault(p, len(seen))
    rows = []
    for c in claude:
        a_b, a_e = (answers[str(seen[p])] for p in c["prompts"])
        right_b = a_b == c["truth"][0] and c["truth"][0] > 0
        right_e = a_e == c["truth"][1] and c["truth"][1] > 0
        rows.append(dict(model=c["model"], model_neo=c["model_neo"], gated=c["neo"] if c["trusted"] else c["model_neo"],
                         claude=right_b, claude_neo=right_e, claude_gated=c["neo"] if c["trusted"] else right_e,
                         rec_b=c["truth"][0] > 0, rec_e=c["truth"][1] > 0, trusted=c["trusted"]))
    n = len(rows)
    t = sum(r["trusted"] for r in rows)
    out = ["", f"## Against Claude, on {n} of the same searches", "",
           f"{SAMPLE} pass-2 searches from each codebase. Claude answered every prompt the local model was shown - the "
           "same description, the same candidates - with one number, never seeing the answers.", "",
           "| solver | right function | model calls |", "|---|---|---|"]
    for label, key, c in ((f"{model} + search", "model", n), (f"{model} + neo4d", "model_neo", n),
                          (f"neo4d decides, {model} if unsure", "gated", n - t), ("Claude + search", "claude", n),
                          ("Claude + neo4d", "claude_neo", n), ("neo4d decides, Claude if unsure", "claude_gated", n - t)):
        out.append(f"| {label} | **{pct(rows, key):.0%}** ({sum(r[key] for r in rows)}/{n}) | {c} |")
    out += ["", f"The right function was among the candidates shown in {sum(r['rec_b'] for r in rows)}/{n} searches with "
            f"search and {sum(r['rec_e'] for r in rows)}/{n} with neo4d - no reader can pick a function it is not shown."]
    p = REPO / "results" / "LOCAL_SEARCH.md"
    text = p.read_text().split("\n## Against Claude")[0].rstrip("\n")
    p.write_text(text + "\n" + "\n".join(out) + "\n")
    print("\n".join(out))
    return 0


if __name__ == "__main__":
    sys.exit(main())
