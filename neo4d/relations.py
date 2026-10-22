"""Relations - fix rules that generalise past the literal tokens, measured on real fixes. No law here: the body.

A literal pattern is one exact edit, `weight < j -> weight <= j` reduced to `< -> <=`. A RELATION abstracts what is
project-specific and keeps what is not:
    operators and keywords      kept literal (they mean the same in every project)
    identifiers                 placeholders $I1, $I2 ... bound across the edit; a NEW identifier in the fix becomes
                                ~$Ik  (within edit distance 2 of $Ik: a near-copy, a typo or a sibling name)
                                @ctx  (another identifier already in scope - the hunk's lines)
                                ?id   (from nowhere - the relation cannot generate it)
    integers                    $N1 ...; in the fix $Nk+1, $Nk-1, a literal 0 or 1, @num (a number in scope), ?num
So `count + 1 -> count + 2` and `size - 1 -> size - 2` are both `$I1 + $N1 -> $I1 + $N1+1`: one relation, two
literals. A relation GENERATES: applied to a buggy line and its scope it proposes every line it can make, and a fix
is covered when one of them is the real fixed line, exactly.

Edits are the changed span of a one-line replacement, after the common prefix and suffix: up to 3 tokens a side.

    python -m neo4d.relations   -> results/RELATIONS.md
"""
from __future__ import annotations

import json
import re
import sys
from collections import Counter, defaultdict
from functools import lru_cache

from neo4d import REPO
from neo4d import realfix as RF

MAXSPAN = 3
INT = re.compile(r"^\d+[lLuU]*$")
IDENT = re.compile(r"^[A-Za-z_]\w*$")


def canon(tok):
    return RF.CANON.get(tok, tok)


def is_ident(t):
    return bool(IDENT.match(t)) and t not in RF.KEYWORDS and t not in RF.CANON.values()


def is_int(t):
    return bool(INT.match(t))


def edit_distance(a, b, cap=3):
    if abs(len(a) - len(b)) > cap:
        return cap + 1
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i] + [0] * len(b)
        for j, cb in enumerate(b, 1):
            cur[j] = min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb))
        prev = cur
    return prev[-1]


# ------------------------------------------------------------------------------------------------ the corpora

def hunks_with_scope(diff, path_ok, reverse=False):
    """(file, buggy line, fixed line, scope lines) for every 1 -> 1 line replacement, with the @@ hunk's lines as
    scope (context and removed lines - what the buggy program has around the edit)."""
    out, file = [], None
    hunk = []

    def flush():
        if not hunk:
            return
        scope = [l[1:] for l in hunk if l[:1] in (" ", "+" if reverse else "-")]
        i = 0
        while i < len(hunk):
            if hunk[i][:1] in "-+":
                j = i
                while j < len(hunk) and hunk[j][:1] in "-+":
                    j += 1
                block = hunk[i:j]
                m = [l[1:] for l in block if l.startswith("-")]
                p = [l[1:] for l in block if l.startswith("+")]
                if reverse:
                    m, p = p, m
                if len(m) == 1 and len(p) == 1 and m[0].strip() != p[0].strip() and file and path_ok(file):
                    out.append((file, m[0], p[0], scope))
                i = j
            else:
                i += 1
        hunk.clear()

    for line in diff.split("\n"):
        if line.startswith("+++ ") or line.startswith("--- "):
            flush()
            if line.startswith("+++ "):
                q = line[4:].strip()
                file = q[2:] if q.startswith(("a/", "b/")) else q
            continue
        if line.startswith("diff ") or line.startswith("@@"):
            flush()
            continue
        if line[:1] in (" ", "-", "+"):
            hunk.append(line)
        elif line == "":
            hunk.append(" ")
    flush()
    return out


def corpus():
    """Every 1 -> 1 replacement in the three benchmarks: (corpus, project, bug, buggy, fixed, scope), plus the number
    of bugs per corpus and which bugs are made ONLY of such replacements."""
    import glob
    import os
    fixes, bugs, pure = [], Counter(), {}
    B = RF.B
    for p in sorted(glob.glob(f"{B}/BugsInPy/projects/*/bugs/*/bug_patch.txt")):
        parts = p.split("/")
        proj, bid = parts[-4], f"{parts[-4]}-{parts[-2]}"
        diff = open(p, encoding="utf-8", errors="replace").read()
        hs = hunks_with_scope(diff, lambda f: f.endswith(".py") and RF._not_test(f))
        bugs["BugsInPy"] += 1
        pure[("BugsInPy", bid)] = _pure(diff, lambda f: f.endswith(".py") and RF._not_test(f), False)
        fixes += [("BugsInPy", proj, bid, m, q, s) for _, m, q, s in hs]
    for p in sorted(glob.glob(f"{B}/defects4j/framework/projects/*/patches/*.src.patch")):
        parts = p.split("/")
        proj, bid = parts[-3], f"{parts[-3]}-{os.path.basename(p).split('.')[0]}"
        diff = open(p, encoding="utf-8", errors="replace").read()
        hs = hunks_with_scope(diff, lambda f: f.endswith(".java"), reverse=True)
        bugs["Defects4J"] += 1
        pure[("Defects4J", bid)] = _pure(diff, lambda f: f.endswith(".java"), True)
        fixes += [("Defects4J", proj, bid, m, q, s) for _, m, q, s in hs]
    for line in open(f"{B}/defects4c/defectsc_tpl/data/github_api_save.jsonl", encoding="utf-8"):
        d = json.loads(line)
        c = json.loads(d["content"]) if isinstance(d["content"], str) else d["content"]
        m_ = re.search(r"repos/([^/]+/[^/]+)/commits", d.get("commit", ""))
        proj = m_.group(1) if m_ else "?"
        bid = c.get("sha", "")[:10]
        diff = ""
        for f in c.get("files", []):
            if f.get("patch") and f["filename"].endswith(RF.SRC_EXT["c"]) and RF._not_test(f["filename"]):
                diff += f"--- a/{f['filename']}\n+++ b/{f['filename']}\n{f['patch']}\n"
        bugs["Defects4C"] += 1
        pure[("Defects4C", bid)] = _pure(diff, lambda f: True, False)
        fixes += [("Defects4C", proj, bid, m, q, s) for _, m, q, s in hunks_with_scope(diff, lambda f: True)]
    return fixes, bugs, pure


def _pure(diff, path_ok, reverse):
    hs = RF.hunks(diff, path_ok, reverse)
    blocks = [(m, p) for _, m, p in hs if any(x.strip() for x in m + p)]
    return bool(blocks) and all(len(m) == 1 and len(p) == 1 for m, p in blocks)


# ----------------------------------------------------------------------------------------- edits and relations

TOK_JS = re.compile(r"[A-Za-z_$][\w$]*|\d+(?:\.\d+)?n?|===|!==|==|!=|<=|>=|=>|&&|\|\||\?\?|\?\.|<<|>>|\+\+|--|\+=|-=|\*=|/=|\.\.\.|\S")


def toks_js(line):
    """JavaScript tokens: `===` `!==` `=>` `??` `?.` whole, `$` part of a name (renamed `_S_` so a name never looks
    like a pattern placeholder), then the shared canonical forms (`&&` AND, `!` NOT, `true` TRUE, `null` NULL)."""
    return [canon(t.replace("$", "_S_")) for t in TOK_JS.findall(line)]


def toks(line, lang="py"):
    if lang == "js":
        return toks_js(line)
    return [canon(t) for t in RF.TOK.findall(line)]


def edit(buggy, fixed):
    a, b = toks(buggy), toks(fixed)
    i = 0
    while i < min(len(a), len(b)) and a[i] == b[i]:
        i += 1
    j = 0
    while j < min(len(a), len(b)) - i and a[-1 - j] == b[-1 - j]:
        j += 1
    o, n = a[i:len(a) - j], b[i:len(b) - j]
    if (not o and not n) or len(o) > MAXSPAN or len(n) > MAXSPAN:
        return None
    return a, b, i, o, n


def scope_idents(scope):
    return sorted({t for l in scope for t in toks(l) if is_ident(t)})


def scope_ints(scope):
    return sorted({t for l in scope for t in toks(l) if is_int(t)})


def relation(o, n, scope):
    """The relation an edit instantiates (old pattern, new pattern), or None for tokens it cannot abstract."""
    names, nums, old = {}, {}, []
    for t in o:
        if is_ident(t):
            names.setdefault(t, f"$I{len(names) + 1}")
            old.append(names[t])
        elif is_int(t):
            nums.setdefault(t, f"$N{len(nums) + 1}")
            old.append(nums[t])
        else:
            old.append(t)
    sid, sint = set(scope_idents(scope)), set(scope_ints(scope))
    new = []
    for t in n:
        if is_ident(t):
            if t in names:
                new.append(names[t])
            else:
                near = [names[x] for x in names if edit_distance(x, t) <= 2 or x.lower() == t.lower()]
                new.append(f"~{near[0]}" if near else ("@ctx" if t in sid else "?id"))
        elif is_int(t):
            v = int(re.sub(r"\D", "", t) or 0)
            hit = None
            for x, ph in nums.items():
                xv = int(re.sub(r"\D", "", x) or 0)
                if v == xv:
                    hit = ph
                elif v == xv + 1:
                    hit = hit or f"{ph}+1"
                elif v == xv - 1:
                    hit = hit or f"{ph}-1"
            new.append(hit or (t if t in ("0", "1") else ("@num" if t in sint else "?num")))
        else:
            new.append(t)
    return tuple(old), tuple(new)


def literal(o, n):
    return tuple(o), tuple(n)


def generative(rel):
    return not any(x in ("?id", "?num") for x in rel[1])


def generate(rel, a, scope, cap=200):
    """Every line (as tokens) the relation makes from buggy tokens a with scope; each window of a matching the old
    pattern is rewritten. Placeholders bind consistently; ~$Ik, @ctx and @num expand over the scope."""
    old, new = rel
    sid, sint = scope_idents(scope), scope_ints(scope)
    out = []
    L = len(old)
    starts = range(len(a) + 1) if L == 0 else range(len(a) - L + 1)
    for s in starts:
        bind, ok = {}, True
        for k, pat in enumerate(old):
            t = a[s + k]
            if pat.startswith("$I"):
                ok = is_ident(t) and bind.setdefault(pat, t) == t
            elif pat.startswith("$N"):
                ok = is_int(t) and bind.setdefault(pat, t) == t
            else:
                ok = t == pat
            if not ok:
                break
        if not ok:
            continue
        choices = [[]]
        for pat in new:
            if pat in bind:
                opts = [bind[pat]]
            elif pat.startswith("~$I"):
                base = bind.get(pat[1:], "")
                opts = [x for x in sid if x != base and (edit_distance(x, base) <= 2 or x.lower() == base.lower())]
            elif pat == "@ctx":
                opts = sid
            elif pat == "@num":
                opts = sint
            elif pat.startswith("$N") and pat[-2:] in ("+1", "-1"):
                base = bind.get(pat[:-2], "0")
                v = int(re.sub(r"\D", "", base) or 0) + (1 if pat.endswith("+1") else -1)
                opts = [str(v)] if v >= 0 else []
            else:
                opts = [pat]
            choices = [c + [x] for c in choices for x in opts][:cap]
        for c in choices:
            out.append(tuple(a[:s] + c + a[s + L:]))
    return out


@lru_cache(maxsize=1 << 20)
def _near(base, sid):
    return [x for x in sid if x != base and (edit_distance(x, base) <= 2 or x.lower() == base.lower())]


def _options(pat, bind, sid, sint):
    if pat in bind:
        return [bind[pat]]
    if pat.startswith("~$I"):
        return _near(bind.get(pat[1:], ""), sid)
    if pat == "@ctx":
        return sid
    if pat == "@num":
        return sint
    if pat.startswith("$N") and pat[-2:] in ("+1", "-1"):
        base = bind.get(pat[:-2], "0")
        v = int(re.sub(r"\D", "", base) or 0) + (1 if pat.endswith("+1") else -1)
        return [str(v)] if v >= 0 else []
    return [pat]


@lru_cache(maxsize=1 << 16)
def _scope(scope):
    return tuple(scope_idents(scope)), tuple(scope_ints(scope))


def fire(rel, a, scope, b=None):
    """What `generate` would give, without listing it: (candidates, whether b is one of them). Candidates are
    counted per matching window (the product of each new token's options, the unchanged line itself excluded)."""
    old, new = rel
    sid, sint = _scope(tuple(scope))
    L, count, hit = len(old), 0, False
    for s in (range(len(a) + 1) if L == 0 else range(len(a) - L + 1)):
        bind, ok = {}, True
        for k, pat in enumerate(old):
            t = a[s + k]
            if pat.startswith("$I"):
                ok = is_ident(t) and bind.setdefault(pat, t) == t
            elif pat.startswith("$N"):
                ok = is_int(t) and bind.setdefault(pat, t) == t
            else:
                ok = t == pat
            if not ok:
                break
        if not ok:
            continue
        opts = [_options(pat, bind, sid, sint) for pat in new]
        n = 1
        for o in opts:
            n *= len(o)
        if len(new) == L and n and all(a[s + j] in opts[j] for j in range(L)):
            n -= 1
        count += n
        if b is not None and not hit and len(b) == len(a) - L + len(new) and list(b[:s]) == a[:s] \
                and list(b[s + len(new):]) == a[s + L:]:
            hit = all(b[s + j] in opts[j] for j in range(len(new))) and tuple(b) != tuple(a)
    return count, hit


# ------------------------------------------------------------------------------------------------ measurement

def main() -> int:
    fixes, nbugs, pure = corpus()
    rows = []
    for c, proj, bid, m, q, s in fixes:
        e = edit(m, q)
        if e is None:
            continue
        a, b, i, o, n = e
        rows.append(dict(corpus=c, proj=proj, bid=bid, a=a, b=tuple(b), scope=s, lit=literal(o, n),
                         rel=relation(o, n, s), size=max(len(o), len(n))))
    print(f"  {len(fixes)} one-line replacements; {len(rows)} small edits (<= {MAXSPAN} tokens)", flush=True)
    projs = sorted({r["proj"] for r in rows})
    by_proj_lit, by_proj_rel = defaultdict(set), defaultdict(set)
    for r in rows:
        by_proj_lit[r["lit"]].add(r["proj"])
        by_proj_rel[r["rel"]].add(r["proj"])
    res = {}
    for level, key, by in (("literal", "lit", by_proj_lit), ("relation", "rel", by_proj_rel)):
        for need in (1, 2):
            cov = fan = fired = 0
            for r in rows:
                pool = [k for k, ps in by.items() if len(ps - {r["proj"]}) >= need and generative(k)]
                res_ = [fire(k, r["a"], r["scope"], r["b"]) for k in pool]
                n_c = sum(c for c, _ in res_)
                cov += any(h for _, h in res_)
                fan += n_c
                fired += bool(n_c)
            res[(level, need)] = (cov, fan / len(rows), fired, len([k for k, ps in by.items() if len(ps) >= need]))
            print(f"  {level:8} seen in >= {need} other projects: covers {cov}/{len(rows)}, "
                  f"{fan / len(rows):.1f} candidates per line", flush=True)
    distinct = Counter(r["rel"] for r in rows)
    lits_per_rel = defaultdict(set)
    for r in rows:
        lits_per_rel[r["rel"]].add(r["lit"])
    out = ["# Relations on real fixes - the ceiling, before any law", "",
           f"Generated by `neo4d/relations.py`. {sum(nbugs.values()):,} real bugs (" +
           ", ".join(f"{k} {v}" for k, v in nbugs.items()) + f"); {len(fixes):,} one-line replacements; "
           f"**{len(rows):,} small edits** (up to {MAXSPAN} tokens changed a side) in {len(projs)} projects.", "",
           "Leave-one-project-out: a fix counts only if patterns learned from OTHER projects generate it exactly.", "",
           "| learned from other projects | patterns | covers | candidates per line |", "|---|---|---|---|"]
    for (level, need), (cov, fan, fired, npat) in res.items():
        out.append(f"| {level}, seen in >= {need} other project{'s' if need > 1 else ''} | {npat:,} | "
                   f"**{cov}/{len(rows)} = {cov / len(rows):.1%}** | {fan:.1f} |")
    multi = sum(1 for k, v in lits_per_rel.items() if len(v) >= 2)
    out += ["", f"Relations with two or more different literal instances: {multi:,} of {len(distinct):,}.", "",
            "Most frequent relations:", ""]
    for k, c in distinct.most_common(25):
        out.append(f"- `{' '.join(k[0]) or '(nothing)'} -> {' '.join(k[1]) or '(nothing)'}` - {c} fixes, "
                   f"{len(by_proj_rel[k])} projects, {len(lits_per_rel[k])} literal forms")
    (REPO / "results" / "RELATIONS.md").write_text("\n".join(out) + "\n")
    print("\n".join(out))
    return 0


if __name__ == "__main__":
    sys.exit(main())
