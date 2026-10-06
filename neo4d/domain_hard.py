"""Harder data for the mutation domain - does the swarm still mutate? The RELATE law unchanged; the body as in the
best configuration of results/DOMAIN_MUTATION.md (anchored relations, the domain's junk budget).

    E1  NEW CODEBASES      taught on the standard library's modules, tested on held-out modules, on the standard
                           library's own test code, and on click
    E2  NEW LANGUAGES      taught on Python, tested on C (Homebrew packages), C++ (libc++) and Java (QuixBugs) with
                           no target-language lesson; then with 30 ... 1,000 target lines added - and with the target
                           lines alone, to see what the Python teaching carries over
    E3  HARDER OPERATORS   the teacher adds ARG (swap two adjacent arguments), IDX (a subscript off by one), DEL
                           (delete a call statement) and, in C, UOI (++ <-> --)
    E4  A NOISY TEACHER    10%, 30%, 50% of the lessons replaced by random wrong edits the body believes

    python -m neo4d.domain_hard   -> results/DOMAIN_HARD.md
"""
from __future__ import annotations

import ast
import random
import statistics
import sys
import sysconfig
from collections import defaultdict
from pathlib import Path

from neo4d import REPO
from neo4d import domain_mutation as D
from neo4d import relate_live as RL

SEEDS = (0, 1, 2)


def _v3():
    """The table R1-R9 allow with one change - R9 without "unless cheap": a check of that principle, never a law."""
    from neo4d import judge_relate as J
    t = [0] * 256
    for x in range(256):
        L = J.LV(x)
        if J.B(x, J.COSTLY):
            t[x] = 1 if J.B(x, J.FIRE) or L >= 1 else 0
            continue
        g = [L]
        if J.B(x, J.FIRE):
            g.append(1)
            if J.B(x, J.CHEAP):
                g.append(2)
            if J.B(x, J.NEWNET) and L >= 1:
                g.append(2)
        if J.B(x, J.PREDICTED) and L >= 1:
            g.append(min(L + 1, 3))
        new = max(g)
        if J.B(x, J.BARREN) and not J.B(x, J.PREDICTED) and new == 2:
            new = 1
        t[x] = new
    return t


V3 = _v3()
N_EVAL = 2000
CAP = 40000
LIBCXX = Path("/Library/Developer/CommandLineTools/SDKs/MacOSX.sdk/usr/include/c++/v1")


def _window(code, net, lang):
    return [(net, l, [x for x in code[max(0, j - 3):j + 4]], lang) for j, l in enumerate(code)]


def python_lines(paths, net_of, set_name):
    out = []
    for p in paths:
        src = p.read_text(errors="replace")
        try:
            tree = ast.parse(src)
        except SyntaxError:
            continue
        drop = set()
        for n in ast.walk(tree):
            if isinstance(n, ast.Expr) and isinstance(n.value, ast.Constant) and isinstance(n.value.value, str):
                drop.update(range(n.lineno, n.end_lineno + 1))
        code = [D.strip_comment(l) for i, l in enumerate(src.split("\n"), 1)
                if i not in drop and l.strip() and not l.strip().startswith("#") and len(l) < 160]
        out += _window([l for l in code if l.strip()], f"{set_name}:{net_of(p)}", "py")
    return out


def c_lines(paths, net_of, set_name, lang):
    out = []
    for p in paths:
        try:
            src = p.read_text(errors="replace")
        except OSError:
            continue
        code, block = [], False
        for l in src.split("\n"):
            if block:
                if "*/" in l:
                    l, block = l.split("*/", 1)[1], False
                else:
                    continue
            while "/*" in l:
                head, rest = l.split("/*", 1)
                if "*/" in rest:
                    l = head + " " + rest.split("*/", 1)[1]
                else:
                    l, block = head, True
            l = D.strip_comment(l, lang)
            s = l.strip()
            if not s or s.startswith("#") or len(l) >= 160 or not any(ch.isalnum() for ch in s):
                continue
            code.append(l)
        out += _window(code[:2000], f"{set_name}:{net_of(p)}", lang)
    return out


def cap(lines, n, seed=7):
    """At most n lines, whole files kept together, files in a seeded order."""
    by = defaultdict(list)
    for x in lines:
        by[x[0]].append(x)
    nets = sorted(by)
    random.Random(seed).shuffle(nets)
    out = []
    for net in nets:
        if len(out) >= n:
            break
        out += by[net]
    return out


def corpora():
    root = Path(sysconfig.get_paths()["stdlib"])
    lib = [(f"py:{net}", l, s, "py") for net, l, s in D.corpus()]
    tests = cap(python_lines(sorted((root / "test").glob("test_*.py")), lambda p: p.stem, "pytest"), CAP)
    click = python_lines(sorted((REPO / "bench" / "click" / "src" / "click").glob("*.py")), lambda p: p.stem, "click")
    cfiles = sorted(p for p in Path("/opt/homebrew/Cellar").rglob("*.c")
                    if p.stat().st_size > 2000 and "site-packages" not in p.parts and "python" not in p.parts[4].lower())
    pkg = lambda p: p.parts[p.parts.index("Cellar") + 1] if "Cellar" in p.parts else p.parent.name
    cc = cap(c_lines(cfiles, lambda p: f"{pkg(p)}/{p.stem}", "c", "c"), CAP)
    cpp = cap(c_lines(sorted(x for x in LIBCXX.rglob("*") if x.is_file()), lambda p: p.name, "cpp", "cpp"), CAP)
    java = c_lines(sorted((REPO / "bench" / "QuixBugs" / "correct_java_programs").glob("*.java")),
                   lambda p: p.stem, "java", "java")
    return dict(lib=lib, tests=tests, click=click, c=cc, cpp=cpp, java=java)


def sets_of(dom):
    out = defaultdict(list)
    for i, x in enumerate(dom.lines):
        out[x["net"].split(":", 1)[0]].append(i)
    return out


def halves(dom, idx, seed):
    """Split a set's lines by net, half for teaching and half held out."""
    nets = sorted({dom.lines[i]["net"] for i in idx})
    random.Random(500 + seed).shuffle(nets)
    held = set(nets[:max(1, len(nets) // 2)])
    return [i for i in idx if dom.lines[i]["net"] not in held], [i for i in idx if dom.lines[i]["net"] in held]


def sample(idx, n, seed):
    return random.Random(900 + seed).sample(idx, min(n, len(idx)))


def main() -> int:
    law = RL.load_law(str(Path(RL.__file__).parent / "kernels" / "relate.c"))
    C = corpora()
    print("  " + ", ".join(f"{k} {len(v):,}" for k, v in C.items()), flush=True)
    base = D.Domain(raw=C["lib"] + C["tests"] + C["click"] + C["c"] + C["cpp"] + C["java"])
    S = sets_of(base)
    best = lambda taught, dom=base, **kw: D.teach(dom, taught, law, ("ctx",), costly_t=D.JUNK, **kw)
    nolaw = lambda taught, dom=base: D.teach(dom, taught, None, ("rel",))
    nmut = {k: sum(len(base.lines[i]["refs"]) for i in v) for k, v in S.items()}
    out = ["# Harder data - does it still mutate?", "",
           "Generated by `neo4d/domain_hard.py`. The mutation domain of `results/DOMAIN_MUTATION.md`, the RELATE law "
           "unchanged, the body in its best configuration there (anchored relations, at most 2 non-mutants per line). "
           f"Coverage and precision as there; {len(SEEDS)} seeds averaged.", "",
           "| data | lines | mutants |", "|---|---|---|"]
    names = dict(py="standard library", pytest="standard library tests", click="click", c="C (Homebrew packages)",
                 cpp="C++ (libc++)", java="Java (QuixBugs)")
    for k, nm in names.items():
        out.append(f"| {nm} | {len(S[k]):,} | {nmut[k]:,} |")

    # E1 - new codebases
    rows = defaultdict(list)
    for seed in SEEDS:
        nets = sorted({base.lines[i]["net"] for i in S["py"]})
        random.Random(1000 + seed).shuffle(nets)
        held = set(nets[:len(nets) // 4])
        train = [i for i in S["py"] if base.lines[i]["net"] not in held]
        taught = random.Random(seed).sample(train, 10000)
        act, act0 = best(taught), nolaw(taught)
        tests = dict(py=sample([i for i in S["py"] if base.lines[i]["net"] in held], N_EVAL, seed),
                     pytest=sample(S["pytest"], N_EVAL, seed), click=sample(S["click"], N_EVAL, seed))
        for k, t in tests.items():
            rows[(k, "law")].append(D.evaluate(base, act, t))
            rows[(k, "nolaw")].append(D.evaluate(base, act0, t))
        print(f"  E1 seed {seed} done", flush=True)
    m = lambda r, f: statistics.mean(e[f] for e in r)
    out += ["", "## E1 - new codebases (taught 10,000 lines of standard-library modules)", "",
            "| tested on | coverage | precision | candidates per line | no law, relations: coverage / precision |",
            "|---|---|---|---|---|"]
    for k, nm in (("py", "held-out standard-library modules"), ("pytest", "the standard library's test code"),
                  ("click", "click - another project")):
        r, r0 = rows[(k, "law")], rows[(k, "nolaw")]
        out.append(f"| {nm} | **{m(r, 'cov'):.1%}** | **{m(r, 'prec'):.1%}** | {m(r, 'cand'):.1f} | "
                   f"{m(r0, 'cov'):.1%} / {m(r0, 'prec'):.1%} |")

    # E2 - new languages
    KT = (0, 30, 100, 300, 1000)
    e2 = defaultdict(list)
    for seed in SEEDS:
        py_taught = random.Random(seed).sample(S["py"], 10000)
        for lang in ("c", "cpp", "java"):
            tr, te = halves(base, S[lang], seed)
            te = sample(te, N_EVAL, seed)
            tr = random.Random(seed).sample(tr, min(len(tr), max(KT)))
            for kt in KT:
                e2[(lang, "py+", kt)].append(D.evaluate(base, best(py_taught + tr[:kt]), te))
                if kt:
                    e2[(lang, "only", kt)].append(D.evaluate(base, best(tr[:kt]), te))
        print(f"  E2 seed {seed} done", flush=True)
    out += ["", "## E2 - new languages", "",
            "Taught 10,000 Python lines, then k lines of the target language (from half its files; tested on the "
            "other half). `alone`: the same k target lines with no Python before them.", "",
            "| language | target lines | coverage | precision | alone: coverage / precision |", "|---|---|---|---|---|"]
    for lang in ("c", "cpp", "java"):
        for kt in KT:
            r = e2[(lang, "py+", kt)]
            if not r:
                continue
            alone = e2.get((lang, "only", kt))
            a = f"{m(alone, 'cov'):.1%} / {m(alone, 'prec'):.1%}" if alone else "-"
            out.append(f"| {names[lang]} | {kt:,} | **{m(r, 'cov'):.1%}** | {m(r, 'prec'):.1%} | {a} |")
    ops = defaultdict(list)
    for seed in SEEDS:
        for lang in ("c", "cpp", "java"):
            r = e2[(lang, "py+", 0)][seed]
            for op, v in r["by_op"].items():
                ops[(lang, op)].append(v)
    allops = sorted({op for (_, op) in ops})
    out += ["", "With no target-language lesson, operator by operator:", "",
            "| language | " + " | ".join(allops) + " |", "|---|" + "---|" * len(allops)]
    for lang in ("c", "cpp", "java"):
        out.append(f"| {names[lang]} | " + " | ".join(
            f"{statistics.mean(ops[(lang, op)]):.0%}" if ops.get((lang, op)) else "-" for op in allops) + " |")

    # E3 - harder operators
    hard = D.Domain(raw=C["lib"] + C["c"], hard=True)
    H = sets_of(hard)
    e3 = defaultdict(list)
    for seed in SEEDS:
        nets = sorted({hard.lines[i]["net"] for i in H["py"]})
        random.Random(1000 + seed).shuffle(nets)
        held = set(nets[:len(nets) // 4])
        train = [i for i in H["py"] if hard.lines[i]["net"] not in held]
        test = sample([i for i in H["py"] if hard.lines[i]["net"] in held], N_EVAL, seed)
        ctr, cte = halves(hard, H["c"], seed)
        for kk in (1000, 10000):
            taught = random.Random(seed).sample(train, kk)
            e3[("py", kk)].append(D.evaluate(hard, best(taught, dom=hard), test))
        taught = random.Random(seed).sample(train, 10000) + random.Random(seed).sample(ctr, min(1000, len(ctr)))
        e3[("c", 10000)].append(D.evaluate(hard, best(taught, dom=hard), sample(cte, N_EVAL, seed)))
        print(f"  E3 seed {seed} done", flush=True)
    hops = sorted({op for r in e3[("py", 10000)] + e3[("c", 10000)] for op in r["by_op"]})
    out += ["", "## E3 - harder operators", "",
            "The teacher adds ARG (swap two adjacent arguments: `f(a, b)` -> `f(b, a)`), IDX (`a[i]` -> `a[i + 1]`, "
            "`a[i - 1]`), DEL (a call statement deleted - the whole line replaced) and, in C, UOI (`++` <-> `--`).", "",
            "| tested on | taught | coverage | precision | " + " | ".join(hops) + " |",
            "|---|---|---|---|" + "---|" * len(hops)]
    for key, label, taught_label in ((("py", 1000), "held-out Python modules", "1,000 Python"),
                                     (("py", 10000), "held-out Python modules", "10,000 Python"),
                                     (("c", 10000), "held-out C files", "10,000 Python + 1,000 C")):
        r = e3[key]
        cells = [f"{statistics.mean(e['by_op'].get(op, 0) for e in r):.0%}" if any(op in e["by_op"] for e in r) else "-"
                 for op in hops]
        out.append(f"| {label} | {taught_label} | **{m(r, 'cov'):.1%}** | {m(r, 'prec'):.1%} | " + " | ".join(cells) + " |")

    # E4 - a noisy teacher
    e4 = defaultdict(list)
    for seed in SEEDS:
        nets = sorted({base.lines[i]["net"] for i in S["py"]})
        random.Random(1000 + seed).shuffle(nets)
        held = set(nets[:len(nets) // 4])
        train = [i for i in S["py"] if base.lines[i]["net"] not in held]
        test = sample([i for i in S["py"] if base.lines[i]["net"] in held], N_EVAL, seed)
        taught = random.Random(seed).sample(train, 10000)
        for nz in (0.0, 0.1, 0.3, 0.5):
            e4[("law", nz)].append(D.evaluate(base, best(taught, noise=nz, noise_seed=seed), test))
            e4[("v3", nz)].append(D.evaluate(base, D.teach(base, taught, lambda x: V3[x], ("ctx",), costly_t=D.JUNK,
                                                           noise=nz, noise_seed=seed), test))
            e4[("nolaw", nz)].append(D.evaluate(base, D.teach(base, taught, None, ("ctx",), noise=nz,
                                                              noise_seed=seed), test))
        print(f"  E4 seed {seed} done", flush=True)
    out += ["", "## E4 - a noisy teacher (10,000 lessons, a share of them wrong)", "",
            "A wrong lesson: one random token of the line replaced by a random token of the corpus, presented as a "
            "mutant. Tested against the true teacher on held-out modules.", "",
            "| wrong lessons | law: coverage | law: precision | principle test - a barren relation weakens even when cheap: coverage / precision | no law: coverage / precision |",
            "|---|---|---|---|---|"]
    for nz in (0.0, 0.1, 0.3, 0.5):
        r, r3, r0 = e4[("law", nz)], e4[("v3", nz)], e4[("nolaw", nz)]
        out.append(f"| {nz:.0%} | **{m(r, 'cov'):.1%}** | **{m(r, 'prec'):.1%}** | {m(r3, 'cov'):.1%} / "
                   f"**{m(r3, 'prec'):.1%}** | {m(r0, 'cov'):.1%} / {m(r0, 'prec'):.1%} |")
    out += ["", "The law spares a cheap relation from weakening (R9: \"unless cheap or proven\"), so every wrong lesson "
            "that makes a cheap rule stays active, and a thousand of them spray. The principle test drops that one "
            "exemption - the table it allows, built here only to measure the change, not handed over as a law."]
    (REPO / "results" / "DOMAIN_HARD.md").write_text("\n".join(out) + "\n")
    print("\n".join(out))
    return 0


if __name__ == "__main__":
    sys.exit(main())
