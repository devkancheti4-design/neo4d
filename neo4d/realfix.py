"""Will fluidnet generalise more on a 4D structure? - tested on real bugs, no law authored.

Three real corpora, three languages - the fix patches only, nothing executed:

    BugsInPy    Python   bench/BugsInPy/projects/*/bugs/*/bug_patch.txt        (- buggy, + fixed)
    Defects4J   Java     bench/defects4j/framework/projects/*/patches/*.src.patch (REVERSE: - fixed, + buggy)
    Defects4C   C/C++    bench/defects4c/defectsc_tpl/data/github_api_save.jsonl  (fix commits, - buggy, + fixed)

T1  fluidnet as shipped: the bugs whose every changed line is a one-line replacement that fluidfix's nine shipped
    classes GENERATE from the buggy line (verbatim, all three languages). An upper bound on repair - real repair
    also needs the line found and the suite to judge - but nothing outside it can be repaired.

T2  the 4D question, held out. Every one-token substitution in a real fix (old token -> new token) is a worked
    example. Teach T classes from half the bugs; count how many substitutions in the OTHER half they cover. A
    taught class is one relabelling of the 16 most-substituted tokens, and the structure decides what one class
    can be:
        ring     a translation of a ring of 16 - the router's structure
        XOR      a translation of the 8-cell's vector space GF(2)^4 - every one is a flip, its own inverse
        8-cell   any symmetry of the 8-cell (axes permuted, reflected) - 384 relabellings
        table    no structure: one class = one memorised (old -> new) pair, 16 per class to match a relabelling
    Each structure gets its OWN best placement of the 16 tokens on it, fitted on the training half alone.

    python3 realfix.py        -> results/REALFIX.md, results/realfix.json
"""
from __future__ import annotations

import glob
import json
import os
import random
import re
import sys
from collections import Counter, defaultdict

from neo4d import generalize as G

from neo4d import REPO
ROOT = str(REPO)
B = os.path.join(ROOT, "bench")
SRC_EXT = {"python": (".py",), "java": (".java",), "c": (".c", ".cc", ".cpp", ".cxx", ".h", ".hpp")}


# ------------------------------------------------------------------------------------- reading the patches

def hunks(diff: str, path_ok, reverse: bool = False):
    """Yield (file, [(buggy_line, fixed_line)], added_only, removed_only) per replacement block."""
    file = None
    minus, plus = [], []
    out = []

    def flush():
        if minus or plus:
            out.append((file, list(minus), list(plus)))
        minus.clear(); plus.clear()

    for line in diff.split("\n"):
        if line.startswith("+++ ") or line.startswith("--- "):
            flush()
            if line.startswith("+++ "):
                p = line[4:].strip()
                file = p[2:] if p.startswith(("a/", "b/")) else p
            continue
        if line.startswith("diff ") or line.startswith("@@"):
            flush()
            continue
        if line.startswith("-"):
            if plus:
                flush()
            minus.append(line[1:])
        elif line.startswith("+"):
            plus.append(line[1:])
        else:
            flush()
    flush()
    res = []
    for f, m, p in out:
        if f is None or not path_ok(f):
            continue
        if reverse:
            m, p = p, m
        res.append((f, m, p))
    return res


def _not_test(path: str) -> bool:
    low = path.lower()
    return not re.search(r"(^|/)(tests?|testing|testes)(/|$)|_test\.|test_|/test/", low)


def load_bugsinpy():
    bugs = []
    for p in sorted(glob.glob(f"{B}/BugsInPy/projects/*/bugs/*/bug_patch.txt")):
        parts = p.split("/")
        bid = f"{parts[-4]}-{parts[-2]}"
        diff = open(p, encoding="utf-8", errors="replace").read()
        bugs.append(("BugsInPy", "python", bid,
                     hunks(diff, lambda f: f.endswith(".py") and _not_test(f))))
    return bugs


def load_defects4j():
    bugs = []
    for p in sorted(glob.glob(f"{B}/defects4j/framework/projects/*/patches/*.src.patch")):
        parts = p.split("/")
        bid = f"{parts[-3]}-{os.path.basename(p).split('.')[0]}"
        diff = open(p, encoding="utf-8", errors="replace").read()
        bugs.append(("Defects4J", "java", bid, hunks(diff, lambda f: f.endswith(".java"), reverse=True)))
    return bugs


def load_defects4c():
    bugs = []
    path = f"{B}/defects4c/defectsc_tpl/data/github_api_save.jsonl"
    for line in open(path, encoding="utf-8"):
        d = json.loads(line)
        c = json.loads(d["content"]) if isinstance(d["content"], str) else d["content"]
        diff = ""
        for f in c.get("files", []):
            if f.get("patch") and f["filename"].endswith(SRC_EXT["c"]) and _not_test(f["filename"]):
                diff += f"--- a/{f['filename']}\n+++ b/{f['filename']}\n{f['patch']}\n"
        bugs.append(("Defects4C", "c", c.get("sha", d.get("id"))[:10], hunks(diff, lambda f: True)))
    return bugs


# ------------------------------------------------------------------------------------------- T1: shipped

def norm_ws(s: str) -> str:
    return re.sub(r"\s+", " ", s.strip())


def t1(bugs, shipped):
    rows = defaultdict(lambda: Counter())
    examples = defaultdict(list)
    for corpus, lang, bid, hs in bugs:
        rows[corpus]["bugs"] += 1
        pairs = []
        clean = bool(hs)
        for f, m, p in hs:
            if len(m) == 1 and len(p) == 1:
                pairs.append((m[0], p[0]))
            elif any(x.strip() for x in m + p):
                clean = False
        if not clean or not pairs:
            continue
        rows[corpus]["one-line replacements only"] += 1
        ok_all, classes = True, set()
        for buggy, fixed in pairs:
            hit = None
            for c in shipped:
                cands = c.candidates(buggy, 1, [buggy])
                if any(norm_ws(x) == norm_ws(fixed) for x in cands):
                    hit = c.name
                    break
            if hit is None:
                ok_all = False
                break
            classes.add(hit)
        if ok_all:
            rows[corpus]["generated by the shipped classes"] += 1
            if len(pairs) > 1 and len(classes) > 1:
                rows[corpus]["... needing two or more classes"] += 1
            if len(examples[corpus]) < 3:
                examples[corpus].append((bid, pairs[0][0].strip(), pairs[0][1].strip(), sorted(classes)))
    return rows, examples


# -------------------------------------------------------------------------------- T2: substitutions, held out

TOK = re.compile(r"[A-Za-z_]\w*|\d+(?:\.\d+)?[lLfFuU]*|==|!=|<=|>=|&&|\|\||<<|>>|\+\+|--|\+=|-=|\*=|/=|->|::|\S")
CANON = {"true": "TRUE", "True": "TRUE", "false": "FALSE", "False": "FALSE",
         "null": "NULL", "None": "NULL", "NULL": "NULL", "nullptr": "NULL",
         "&&": "AND", "and": "AND", "||": "OR", "or": "OR", "!": "NOT", "not": "NOT"}
KEYWORDS = {"TRUE", "FALSE", "NULL", "AND", "OR", "NOT", "min", "max", "is", "in", "if", "while", "break",
            "continue", "return", "else", "elif", "for"}


def generic(tok: str) -> bool:
    """A token whose meaning does not depend on the project: an operator, a literal, a keyword."""
    return tok in KEYWORDS or not re.match(r"[A-Za-z_]", tok)


def substitutions(bugs):
    out = []           # (corpus, bug, old, new)
    for corpus, lang, bid, hs in bugs:
        for f, m, p in hs:
            if len(m) != 1 or len(p) != 1:
                continue
            a = [CANON.get(t, t) for t in TOK.findall(m[0])]
            b = [CANON.get(t, t) for t in TOK.findall(p[0])]
            if len(a) != len(b) or not a:
                continue
            diff = [i for i in range(len(a)) if a[i] != b[i]]
            if len(diff) == 1 and generic(a[diff[0]]) and generic(b[diff[0]]):
                out.append((corpus, bid, a[diff[0]], b[diff[0]]))
    return out


def best_placement(pairs, kind: str, T: int, rng, iters=20000):
    """Place the 16 tokens on the structure to maximise training coverage by T classes (annealed swaps)."""
    H = {"ring": G.ring16(), "xor": G.xor16(), "cube": G.cube16()}[kind]
    # for each (f, a) on positions, the set of class elements that map f -> a
    fit = defaultdict(list)
    for gi, g in enumerate(H):
        for f in range(16):
            fit[(f, int(g[f]))].append(gi)

    def coverage(pos):
        idx = [(pos[f], pos[a]) for f, a in pairs]
        chosen, covered, left = [], 0, list(range(len(idx)))
        for _ in range(T):                       # greedy max coverage, T classes
            votes = Counter()
            for i in left:
                for gi in fit[idx[i]]:
                    votes[gi] += 1
            if not votes:
                break
            gi, n = votes.most_common(1)[0]
            chosen.append(gi)
            g = H[gi]
            left = [i for i in left if g[idx[i][0]] != idx[i][1]]
            covered += n
        return covered, chosen

    pos = list(range(16))
    rng.shuffle(pos)
    cur, chosen = coverage(pos)
    best = (cur, pos[:], chosen)
    temp = 2.0
    for it in range(iters):
        i, j = rng.randrange(16), rng.randrange(16)
        pos[i], pos[j] = pos[j], pos[i]
        new, ch = coverage(pos)
        if new >= cur or rng.random() < pow(2.718, (new - cur) / max(temp, 1e-3)):
            cur, chosen = new, ch
            if cur > best[0]:
                best = (cur, pos[:], ch)
        else:
            pos[i], pos[j] = pos[j], pos[i]
        temp *= 0.9997
    return best, H


def t2(subs, T_values=(1, 2, 4), folds=10, seed=2026, iters=3000):
    """k-fold cross-validation by bug: fit the placement and the T classes on the other folds, count the held-out
    fold's substitutions they generate. Every substitution is held out exactly once."""
    rng = random.Random(seed)
    bug_ids = sorted({(c, b) for c, b, _, _ in subs})
    rng.shuffle(bug_ids)
    fold_of = {bid: i % folds for i, bid in enumerate(bug_ids)}
    res = {"folds": folds, "n": len(subs), "rows": {}}
    for T in T_values:
        hits = {k: 0 for k in ("ring", "xor", "cube", "table")}
        trainc = {k: 0.0 for k in hits}
        scored = 0
        for fo in range(folds):
            train = [(o, n) for c, b, o, n in subs if fold_of[(c, b)] != fo]
            test = [(o, n) for c, b, o, n in subs if fold_of[(c, b)] == fo]
            freq = Counter()
            for o, n in train:
                freq[o] += 1; freq[n] += 1
            vocab = [t for t, _ in freq.most_common(16)]
            tr = [(vocab.index(o), vocab.index(n)) for o, n in train if o in vocab and n in vocab]
            scored += len(test)
            for kind in ("ring", "xor", "cube"):
                (cov, pos, chosen), H = best_placement(tr, kind, T, random.Random(seed + 31 * T + fo), iters)
                trainc[kind] += cov / max(1, len(tr)) / folds
                for o, n in test:
                    if o in vocab and n in vocab:
                        f, a = vocab.index(o), vocab.index(n)
                        hits[kind] += any(H[gi][pos[f]] == pos[a] for gi in chosen)
            top = [p for p, _ in Counter(train).most_common(16 * T)]
            trainc["table"] += sum(1 for x in train if x in top) / max(1, len(train)) / folds
            hits["table"] += sum(1 for x in test if x in top)
        res["rows"][T] = {k: (trainc[k], hits[k], scored) for k in hits}
        print(f"  T2 T={T}  " + "  ".join(f"{k} {hits[k]}/{scored}" for k in hits), flush=True)
    pairs = Counter((o, n) for _, _, o, n in subs)
    rev = sum(c for (o, n), c in pairs.items() if (n, o) in pairs)
    res["flip_share"] = rev / max(1, sum(pairs.values()))
    res["top_pairs"] = [(f"{o} -> {n}", c) for (o, n), c in pairs.most_common(15)]
    return res


def report(t1rows, t1ex, sres, nsubs_by) -> str:
    out = ["# Will fluidnet generalise more on a 4D structure? - real bugs", "",
           "Generated by `realfix.py` from the fix patches of three real benchmarks. Nothing is executed and no law "
           "is authored: T1 asks what fluidfix's shipped vocabulary can generate, T2 asks which structure real fixes "
           "follow, held out.", "",
           "## T1 - fluidnet as shipped, on real bugs", "",
           "| corpus | bugs | only one-line replacements | every line generated by the 9 shipped classes | ... of those, needing 2+ classes |",
           "|---|---|---|---|---|"]
    for c in ("BugsInPy", "Defects4J", "Defects4C"):
        r = t1rows[c]
        out.append(f"| {c} | {r['bugs']} | {r['one-line replacements only']} | "
                   f"**{r['generated by the shipped classes']}** | {r['... needing two or more classes']} |")
    out += ["", "Examples the shipped classes generate:", ""]
    for c, exs in t1ex.items():
        for bid, b, f, cl in exs:
            out.append(f"- {c} `{bid}` ({', '.join(cl)}): `{b}` -> `{f}`")
    out += ["", "## T2 - which structure do real fixes follow? (cross-validated by bug)", "",
            f"**{sres['n']} one-token substitutions** between project-independent tokens (operators, literals, "
            "keywords), from " + ", ".join(f"{k} {n}" for k, n in nsubs_by.items()) + f" - out of "
            f"{sum(r['bugs'] for r in t1rows.values())} real bugs. {sres['folds']}-fold cross-validation by bug: each "
            "fold's substitutions are held out once, the 16-token vocabulary, the placement and the T classes are "
            "fitted on the other folds alone. **This sample is small - read T2 as a direction, not a verdict.**", "",
            f"**{100*sres['flip_share']:.0f}%** of real substitutions are flips: the reverse substitution is also a "
            "real fix somewhere in the corpus.", "",
            "Held-out substitutions the T taught classes generate (mean training coverage in brackets):", "",
            "| T taught classes | ring (the router's) | XOR (8-cell vector space) | 8-cell symmetries | table (no structure, 16T pairs) |",
            "|---|---|---|---|---|"]
    for T, row in sres["rows"].items():
        cells = [f"**{row[k][1]}/{row[k][2]}** ({100*row[k][0]:.0f}%)" for k in ("ring", "xor", "cube", "table")]
        out.append(f"| {T} | " + " | ".join(cells) + " |")
    out += ["", "Most frequent real substitutions:", "",
            ", ".join(f"`{p}` {c}" for p, c in sres["top_pairs"])]
    return "\n".join(out) + "\n"


def main() -> int:
    sys.path.insert(0, ROOT)
    from neo4d import classes as C
    bugs = load_bugsinpy() + load_defects4j() + load_defects4c()
    print(f"  {len(bugs)} real bugs loaded", flush=True)
    t1rows, t1ex = t1(bugs, C.shipped())
    for c, r in t1rows.items():
        print(f"  T1 {c:10} {dict(r)}", flush=True)
    subs = substitutions(bugs)
    nsubs_by = Counter(c for c, _, _, _ in subs)
    print(f"  {len(subs)} one-token substitutions: {dict(nsubs_by)}", flush=True)
    sres = t2(subs)
    os.makedirs(os.path.join(ROOT, "results"), exist_ok=True)
    with open(os.path.join(ROOT, "results/realfix.json"), "w") as fh:
        json.dump({"t1": {k: dict(v) for k, v in t1rows.items()}, "t2": sres}, fh, indent=1, default=str)
    md = report(t1rows, t1ex, sres, nsubs_by)
    with open(os.path.join(ROOT, "results/REALFIX.md"), "w") as fh:
        fh.write(md)
    print("\n" + md)
    return 0


if __name__ == "__main__":
    sys.exit(main())
