"""The self-learning loop with both authored laws: PICK chooses every trial, HARVEST decides it - live, on click.

Same vocabulary, same two secret affine renumberings as harvest_live.py (read back from results/harvest_live.json),
same budget, same click suite. The only change: the body no longer cycles kinds over random sites - every candidate
(kind, site) is measured into PICK's eight bits and the highest rank runs next (ties: lowest kind, file, line).

    EXECUTED    the innermost statement holding the line is executed by click's suite (one coverage run, C tracer)
    ALT_NONE    on the mutant, no class proposes any candidate other than the original line
    MANY_TESTS  10+ distinct tests execute that statement
    NAMED       the enclosing function's name occurs in click's test source
    NEW_SPAN, TRIED, COLD from the harvest so far

    python3 harvest_pick.py   -> results/HARVEST_PICK.md
"""
from __future__ import annotations

import ast
import ctypes
import json
import re
import subprocess
import sys
import time
from collections import Counter
from pathlib import Path

from neo4d import corpus4d_big as CB
from neo4d import harvest_live as HL

from neo4d import REPO as ROOT, KERNELS, BUILD
COV = ROOT / "bench" / "pick_click" / "cov.json"
_so = BUILD / "pick.so"
subprocess.run(["cc", "-O2", "-shared", "-fPIC", "-o", str(_so), str(KERNELS / "pick.c")], check=True)
_p = ctypes.CDLL(str(_so)).pick
_p.argtypes, _p.restype = [ctypes.c_int32], ctypes.c_int32
pick = lambda x: int(_p(x))


def candidates(vocab):
    """Every (kind, site) the vocabulary can mutate in click's source, with its static PICK bits."""
    cov = json.load(open(COV))["files"]
    tests_text = "\n".join(p.read_text() for p in (HL.WORK / "tests").glob("*.py"))
    out = []
    for p in sorted((HL.WORK / "src" / "click").glob("*.py")):
        rel = str(p.relative_to(HL.WORK))
        src = p.read_text().split("\n")
        spans = [(n.lineno, n.end_lineno) for n in ast.walk(ast.parse("\n".join(src))) if isinstance(n, ast.stmt)]
        ctxs = cov.get(rel, {}).get("contexts", {})
        for i, line in enumerate(src):
            if not line.strip() or line.lstrip().startswith("#"):
                continue
            ln = i + 1
            inner = [s for s in spans if s[0] <= ln <= s[1]]
            start = min(inner, key=lambda s: s[1] - s[0])[0] if inner else ln
            ctx = ctxs.get(str(start)) or ctxs.get(str(ln))
            executed = ctx is not None
            ntests = len({t.split("|")[0] for t in (ctx or []) if t})
            name = next((m.group(1) for l in reversed(src[:ln]) for m in [re.match(r"\s*def (\w+)", l)] if m), None)
            named = bool(name) and not name.startswith("__") and re.search(rf"\b{re.escape(name)}\b", tests_text) is not None
            for k, cls in vocab.items():
                mut = HL.inject(k, cls, line)
                if mut in (None, line):
                    continue
                alts = {c for kk, cc in vocab.items() for c in cc.candidates(mut, ln, src) if c not in (line, mut)}
                out.append({"kind": k, "rel": rel, "i": i, "executed": executed, "alt_none": not alts,
                            "many": ntests >= 10, "named": named})
    return out


def word(c, new_span, tried, cold):
    return (int(new_span) | int(c["executed"]) << 1 | int(tried) << 2 | int(c["alt_none"]) << 3
            | int(c["many"]) << 4 | int(c["named"]) << 5 | int(cold) << 6)


def run(code_of, vocab, cands, budget):
    suite = HL.Suite()
    kind_at = {c: k for k, c in code_of.items()}
    lines_of = {}
    taken, log, tried, skips = [], [], set(), Counter()
    while True:
        F = [k for k, _ in taken]
        full = len(F) >= 1 and HL.rank([f ^ F[0] for f in F[1:]]) == 4
        if full or suite.runs >= budget:
            log.append({"act": "STOP", "why": "FULL" if full else "SPENT"})
            break
        base = HL.rank([f ^ F[0] for f in F[1:]]) if F else 0
        best, best_r = None, 0
        for c in cands:
            k = c["kind"]
            new = not F or HL.rank([f ^ F[0] for f in F[1:]] + [k ^ F[0]]) > base
            r = pick(word(c, new, (k, c["rel"], c["i"]) in tried, skips[k] >= 2))
            if r > best_r:
                best, best_r = c, r
        if best is None:
            log.append({"act": "STOP", "why": "PICK ranks every trial 0"})
            break
        k, rel, i = best["kind"], best["rel"], best["i"]
        tried.add((k, rel, i))
        L = lines_of.setdefault(rel, (HL.WORK / rel).read_text().split("\n"))
        orig, mut = L[i], HL.inject(k, vocab[k], L[i])
        ML = L[:]; ML[i] = mut
        b = {"NEW_SPAN": 1, "FULL": 0, "SPENT": 0, "RECHECKED": 0}
        b["KILLED"] = int(not suite.green(rel, ML, fast=True))
        restoring = []
        if b["KILLED"]:
            greening = 0
            for code in range(16):
                kk = kind_at.get(code)
                if kk is None:
                    continue
                for cand in vocab[kk].candidates(mut, i + 1, ML)[:4]:
                    if cand == mut:
                        continue
                    TL = ML[:]; TL[i] = cand
                    if cand == orig:
                        if suite.green(rel, TL):
                            restoring.append(code); greening += 1
                    elif suite.green(rel, TL, fast=True):
                        greening += 1
            b["RESTORES"] = int(bool(restoring))
            b["UNIQUE"] = int(len(set(restoring)) == 1 and greening == 1)
            if b["UNIQUE"]:
                RL = ML[:]; RL[i] = orig
                b["STABLE"] = int((not suite.green(rel, ML, fast=True)) and suite.green(rel, RL))
        act = HL.harvest(HL.word(b))
        if act == HL.RECHECK:
            b["RECHECKED"] = 1
            act = HL.harvest(HL.word(b))
        if act == HL.TAKE:
            taken.append((k, restoring[0]))
        else:
            skips[k] += 1
        entry = {"class": vocab[k].name, "site": f"{rel}:{i + 1}", "pick": best_r,
                 "act": ["SKIP", "TAKE", "STOP", "RECHECK"][act], "suite_runs": suite.runs}
        log.append(entry)
        print("   ", json.dumps(entry), flush=True)
    return taken, log, suite.runs


def route4d5_scorer():
    """The k = 5 router, once authored: laws/router4d5.c, int64_t route4d5(int64_t). None until it exists."""
    src = KERNELS / "router4d5.c"
    if not src.exists():
        return None
    so = BUILD / "route4d5.so"
    subprocess.run(["cc", "-O2", "-shared", "-fPIC", "-fwrapv", "-o", str(so), str(src)], check=True)
    f = ctypes.CDLL(str(so)).route4d5
    f.argtypes, f.restype = [ctypes.c_int64], ctypes.c_int64

    def score(taken, code_of, decs):
        right = refused = wrong = 0
        for _s, q in decs:
            x = 0
            for i, (fk, a) in enumerate(taken[:5]):
                x |= fk << (8 * i) | a << (8 * i + 4)
            v = int(f(x | q << 40)) & 31
            if v >= 16:
                refused += 1
            elif v == code_of[q]:
                right += 1
            else:
                wrong += 1
        return right, refused, wrong
    return score


def main() -> int:
    full_vocab = CB.vocabulary()
    vocab = {k: c for k, c in full_vocab.items() if c.shipped}
    kinds = list(vocab)
    decs = [(s, k) for s, k in CB.decisions(full_vocab) if k in vocab]
    before = json.load(open(ROOT / "results/harvest_live.json"))
    HL.Suite()                                        # a fresh copy of click to read candidates from
    t0 = time.time()
    cands = candidates(vocab)
    print(f"  {len(cands)} candidate trials measured in {time.time() - t0:.1f}s", flush=True)
    rows = []
    for prev in before:
        code_of = {int(k): v for k, v in prev["truth"].items()}
        t0 = time.time()
        print(f"  renumbering {prev['renumbering']} (the same secret map): PICK + HARVEST ...", flush=True)
        taken, log, runs = run(code_of, vocab, cands, budget=90)
        sc = HL.score(taken, code_of, decs, kinds)
        law5 = route4d5_scorer()
        if law5 and len(taken) == 5:
            sc["route4d5"] = law5(taken, code_of, decs)
        rows.append({"renumbering": prev["renumbering"], "body_rule_runs": prev["suite_runs"],
                     "body_rule_trials": sum(1 for e in prev["log"] if "site" in e),
                     "pick_runs": runs, "pick_trials": sum(1 for e in log if "site" in e),
                     "taken": taken, "score": sc, "secs": round(time.time() - t0, 1), "log": log})
        print(f"  -> {len(taken)} examples, {runs} suite runs (body rule: {prev['suite_runs']}); {sc}", flush=True)
    out = ["# PICK + HARVEST - the self-learning loop with both laws authored, live on click", "",
           f"Generated by `harvest_pick.py`. {len(cands):,} candidate (kind, site) trials in click's source, each "
           "measured into PICK's bits; PICK (`laws/pick.c`) chooses every trial, HARVEST (`laws/harvest.c`) decides "
           "it. Same two secret affine renumberings and budget as the body-rule run (`results/HARVEST_LIVE.md`).", "",
           "| secret renumbering | body rule: trials / suite runs | PICK: trials / suite runs | examples | "
           f"the nine kinds | the {len(decs)} real decisions |",
           "|---|---|---|---|---|---|"]
    for r in rows:
        k, d = r["score"]["kinds"], r["score"]["decisions"]
        out.append(f"| {r['renumbering']} | {r['body_rule_trials']} / {r['body_rule_runs']} | "
                   f"**{r['pick_trials']} / {r['pick_runs']}** | {len(r['taken'])} | {k[0]} right, {k[2]} wrong | "
                   f"{d[0]} right, {d[1]} refused, **{d[2]} wrong** |")
    if any("route4d5" in r["score"] for r in rows):
        out += ["", "With the authored k = 5 router scoring in place of the version space (`laws/router4d5.c`):", "",
                "| secret renumbering | route4d5 on the 60 real decisions: right / refused / wrong |", "|---|---|"]
        for r in rows:
            if "route4d5" in r["score"]:
                a, b, c = r["score"]["route4d5"]
                out.append(f"| {r['renumbering']} | {a} / {b} / **{c}** |")
    (ROOT / "results/HARVEST_PICK.md").write_text("\n".join(out) + "\n")
    (ROOT / "results/harvest_pick.json").write_text(json.dumps(rows, indent=1, default=str))
    print("\n" + "\n".join(out))
    return 0


if __name__ == "__main__":
    sys.exit(main())
