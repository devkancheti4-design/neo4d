"""INDUCE live on click's history - does the system's knowledge grow, and does it stay right?

click's whole git history, replayed in commit order. Each fix commit is first SCORED against the knowledge the system
has so far (prospective - nothing learned from a commit is used to score it), then LEARNED from: every one-token change
`old -> new` in it is a candidate class, its evidence is measured, and the authored INDUCE law (neo4d/kernels/induce.c)
decides REJECT / KEEP / ADMIT / RETIRE.

    the bits      SEEN2, SEEN5      the pattern occurred in 2+ / 5+ different commits so far
                  CONFIRMED         it had occurred in an EARLIER commit and has now generated a later fix exactly
                  REFUTED           0 - a confident wrong fix needs the suite at that commit; not measured in a patch
                                    replay (the SHIP law catches it at repair time)
                  PROVABLE          a one-token class carries its property mechanically (exactly that token changes)
                  CONFLICT          an admitted class has the same old token with a different rewrite
                  NOISY             the old token occurs on more than 5% of click's source lines
                  ADMITTED          already in the vocabulary
    scored        coverage          the share of each fix's one-line replacements the knowledge generates exactly
                  competing         one-line fixes where an admitted class fires on the line but proposes something
                                    other than the real fix (a candidate the suite and SHIP must reject - never shipped
                                    by itself)

Three learners on the same replay: NONE (fluidfix's nine shipped classes only), FIRST-SIGHT (admit every pattern the
first time it is seen - fluidnet's teach-at-first-sight), and INDUCE (the law).

    python -m neo4d.induce_live   -> results/INDUCE_LIVE.md
"""
from __future__ import annotations

import ctypes
import re
import subprocess
import sys
from collections import defaultdict
from pathlib import Path

from neo4d import REPO, build_kernel
from neo4d import classes as C
from neo4d import realfix as RF

CLICK = REPO / "bench" / "click"
FIX = re.compile(r"\b(fix|bug|issue|correct|regression|typo|wrong|broken|mistake)", re.I)
SRC = re.compile(r"(^|/)click/[^/]+\.py$")


def git(*a):
    return subprocess.run(["git", "-C", str(CLICK), *a], capture_output=True, text=True).stdout


def commits():
    out = git("log", "--reverse", "--no-merges", "--format=%H%x09%ad%x09%s", "--date=short")
    return [tuple(l.split("\t", 2)) for l in out.splitlines() if l.count("\t") >= 2]


def one_line_fixes(sha):
    """(buggy line, fixed line) for every one-line replacement in click's source files in this commit."""
    diff = git("show", "--format=", "-U0", sha, "--", "click", "src/click")
    pairs = []
    for f, m, p in RF.hunks(diff, lambda path: bool(SRC.search(path)) and "/tests/" not in path):
        if len(m) == 1 and len(p) == 1 and m[0].strip() != p[0].strip():
            pairs.append((m[0], p[0]))
    return pairs


def token_sub(buggy, fixed):
    a, b = RF.TOK.findall(buggy), RF.TOK.findall(fixed)
    if len(a) != len(b) or not a:
        return None
    d = [i for i in range(len(a)) if a[i] != b[i]]
    return (a[d[0]], b[d[0]]) if len(d) == 1 else None


def apply(old, new, line):
    """The class old -> new on a line: every single-token rewrite of an occurrence of `old`."""
    toks = list(re.finditer(r"[A-Za-z_]\w*|\d+(?:\.\d+)?[lLfFuU]*|==|!=|<=|>=|&&|\|\||<<|>>|\+\+|--|\+=|-=|\*=|/=|->|::|\S",
                            line))
    return [line[:m.start()] + new + line[m.end():] for m in toks if m.group(0) == old]


def noisy_tokens():
    lines = []
    for p in sorted((CLICK / "src" / "click").glob("*.py")):
        lines += p.read_text(errors="replace").split("\n")
    n = len(lines)
    counts = defaultdict(int)
    for l in lines:
        for t in set(RF.TOK.findall(l)):
            counts[t] += 1
    return {t for t, c in counts.items() if c > 0.05 * n}, n


def main() -> int:
    induce = ctypes.CDLL(str(build_kernel("induce"))).induce
    induce.argtypes, induce.restype = [ctypes.c_int32], ctypes.c_int32
    shipped = C.shipped()
    noisy, n_lines = noisy_tokens()
    all_commits = commits()
    fixes = [(sha, date, msg) for sha, date, msg in all_commits if FIX.search(msg)]
    seen = defaultdict(set)                      # pattern -> commits it occurred in
    vocab = {"none": set(), "first-sight": set(), "induce": set()}
    events = defaultdict(int)
    timeline = []                                # (index, date, fixes in commit, covered per learner, competing per learner)
    for idx, (sha, date, msg) in enumerate(fixes):
        pairs = one_line_fixes(sha)
        if not pairs:
            continue
        cov = {k: 0 for k in vocab}
        comp = {k: 0 for k in vocab}
        for buggy, fixed in pairs:
            shipped_hit = any(RF.norm_ws(c) == RF.norm_ws(fixed) for cl in shipped for c in cl.candidates(buggy, 1, [buggy]))
            for k, V in vocab.items():
                cands = [c for (o, n) in V for c in apply(o, n, buggy)]
                hit = shipped_hit or any(RF.norm_ws(c) == RF.norm_ws(fixed) for c in cands)
                cov[k] += hit
                comp[k] += bool(cands) and not any(RF.norm_ws(c) == RF.norm_ws(fixed) for c in cands)
        timeline.append((idx, date, len(pairs), cov, comp))
        # learn from this commit, after scoring it
        subs = {token_sub(b, f) for b, f in pairs} - {None}
        for pat in subs:
            earlier = len(seen[pat]) >= 1
            seen[pat].add(sha)
            vocab["first-sight"].add(pat)
            o, n = pat
            conflict = any(oo == o and nn != n for (oo, nn) in vocab["induce"])
            x = (int(len(seen[pat]) >= 2) | int(len(seen[pat]) >= 5) << 1 | int(earlier) << 2 | 0 << 3
                 | 1 << 4 | int(conflict) << 5 | int(o in noisy) << 6 | int(pat in vocab["induce"]) << 7)
            act = int(induce(x))
            events[["REJECT", "KEEP", "ADMIT", "RETIRE"][act]] += 1
            if act == 2:
                vocab["induce"].add(pat)
            elif act == 3:
                vocab["induce"].discard(pat)
    total_fix_lines = sum(t[2] for t in timeline)
    thirds = [timeline[i * len(timeline) // 3:(i + 1) * len(timeline) // 3] for i in range(3)]

    def share(rows, k):
        n = sum(r[2] for r in rows)
        return sum(r[3][k] for r in rows) / n if n else 0.0

    def comp_share(rows, k):
        n = sum(r[2] for r in rows)
        return sum(r[4][k] for r in rows) / n if n else 0.0

    out = ["# INDUCE live on click's history", "",
           f"Generated by `neo4d/induce_live.py`. click's history to 06b2a67: {len(all_commits):,} commits, "
           f"{len(fixes):,} with a fix-like message, **{len(timeline):,} of them changing a line of click's source in "
           f"place** - {total_fix_lines:,} one-line fixes in all, replayed in commit order. Each commit is scored "
           "against the knowledge so far, then learned from.", "",
           f"Learners: **none** - fluidfix's nine shipped classes only; **first-sight** - every one-token pattern admitted "
           f"the first time it appears; **induce** - the authored INDUCE law decides. Noisy tokens (>5% of {n_lines:,} "
           f"source lines): {len(noisy)}.", "",
           "## The learning curve - share of each future fix the knowledge generates exactly", "",
           "| history | one-line fixes | none | first-sight | **induce** |", "|---|---|---|---|---|"]
    for name, rows in zip(("first third", "middle third", "last third"), thirds):
        if rows:
            out.append(f"| {name} ({rows[0][1]} .. {rows[-1][1]}) | {sum(r[2] for r in rows)} | {share(rows, 'none'):.1%} | "
                       f"{share(rows, 'first-sight'):.1%} | **{share(rows, 'induce'):.1%}** |")
    out.append(f"| **all** | {total_fix_lines} | {share(timeline, 'none'):.1%} | {share(timeline, 'first-sight'):.1%} | "
               f"**{share(timeline, 'induce'):.1%}** |")
    out += ["", "## Competing proposals - a class fires on the fixed line but proposes something else", "",
            "Not shipped by themselves (the suite and SHIP must reject them), but each one is work and risk.", "",
            "| history | none | first-sight | **induce** |", "|---|---|---|---|"]
    for name, rows in zip(("first third", "middle third", "last third"), thirds):
        if rows:
            out.append(f"| {name} | {comp_share(rows, 'none'):.1%} | {comp_share(rows, 'first-sight'):.1%} | "
                       f"**{comp_share(rows, 'induce'):.1%}** |")
    out += ["", "## What INDUCE decided", "",
            f"{dict(events)} over the replay; classes in the vocabulary at the end: first-sight "
            f"{len(vocab['first-sight'])}, induce **{len(vocab['induce'])}**: "
            + ", ".join(f"`{o} -> {n}`" for o, n in sorted(vocab["induce"])) + ".", "",
            "## What this does not show", "",
            "- Coverage is patch-level: a class *generating* the real fixed line. Shipping it still needs the suite and "
            "the SHIP law (premise, stable green, unique, property).",
            "- REFUTED is not measured here - it needs the project's suite at each historical commit.",
            "- Only one-token changes become classes; most real fixes change more than one token."]
    (REPO / "results" / "INDUCE_LIVE.md").write_text("\n".join(out) + "\n")
    print("\n".join(out))
    return 0


if __name__ == "__main__":
    sys.exit(main())
