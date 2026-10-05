"""fluidnet harvests its own worked examples - live, on click, the HARVEST law deciding every trial.

The vocabulary is fluidfix's nine shipped classes, numbered 4D-natively (act = kind XOR 5) and then RENUMBERED BY
A SECRET AFFINE MAP g: act code c now runs the class whose 4D-native code g maps to c. Nobody tells fluidnet g.
It must discover it from its own mutants:

    1  pick a kind and a site in click's real source (a body rule for now - PICK is the next law)
    2  inject a fault of that kind (for a flip, the same act that repairs it; literal-off-by-one by its inverse)
    3  measure the eight HARVEST bits with click's own 2,240-test suite: KILLED, RESTORES (some act code restores
       the line byte-for-byte, suite green), UNIQUE (no other act code greens it), STABLE (re-run agrees),
       NEW_SPAN, RECHECKED, FULL, SPENT
    4  harvest(x) decides SKIP / TAKE / STOP / RECHECK - the authored law in laws/harvest.c, judged 0 violations
       Bits the law cannot be swayed by are never measured: if harvest() returns the same act for every
       completion of the unmeasured bits, no suite is run.

Then the harvested examples predict every act code it never harvested, and the 60 real decisions of
corpus4d_big.py, by the affine version space (route4d's class; a k >= 5 kernel is the open K7 prompt).

    python3 harvest_live.py [--renumberings 2] [--budget 90]   -> results/HARVEST_LIVE.md
"""
from __future__ import annotations

import argparse
import ctypes
import json
import os
import random
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

from neo4d import corpus4d_big as CB
from neo4d import generalize as G
from neo4d import judge_router4d as J
from neo4d.corpus4d import route4d, REFUSE

from neo4d import REPO as ROOT, KERNELS, BUILD
CLICK = ROOT / "bench" / "click"
TPY = ROOT / "bench" / "tvenv" / "bin" / "python"
WORK = ROOT / "bench" / "harvest_click"
SKIP, TAKE, STOP, RECHECK = 0, 1, 2, 3

from neo4d import build_kernel
_so = build_kernel("harvest")
_h = ctypes.CDLL(str(_so)).harvest
_h.argtypes, _h.restype = [ctypes.c_int32], ctypes.c_int32
harvest = lambda x: int(_h(x))


def word(b):
    return sum(int(bool(b.get(k))) << i for i, k in enumerate(
        ("KILLED", "RESTORES", "UNIQUE", "STABLE", "NEW_SPAN", "RECHECKED", "FULL", "SPENT")))


def decided_without(known: dict, unknown: list[str]):
    """If harvest() gives one act for every completion of the unmeasured bits, that act - else None."""
    acts = set()
    for m in range(1 << len(unknown)):
        b = dict(known)
        for i, k in enumerate(unknown):
            b[k] = (m >> i) & 1
        acts.add(harvest(word(b)))
    return acts.pop() if len(acts) == 1 else None


def rank(vecs):
    basis = []
    for v in vecs:
        for b in basis:
            v = min(v, v ^ b)
        if v:
            basis.append(v)
    return len(basis)


class Suite:
    def __init__(self):
        if WORK.exists():
            shutil.rmtree(WORK)
        subprocess.run(f"mkdir -p {WORK} && git -C {CLICK} archive HEAD | tar -x -C {WORK}", shell=True, check=True)
        self.env = dict(os.environ, PYTHONPATH=str(WORK / "src"))
        self.runs = 0

    def green(self, rel, lines, fast=False) -> bool:
        p = WORK / rel
        old = p.read_text()
        p.write_text("\n".join(lines))
        try:
            self.runs += 1
            r = subprocess.run([str(TPY), "-m", "pytest", "-q", "-p", "no:cacheprovider", "--tb=no"]
                               + (["-x"] if fast else []), cwd=WORK, env=self.env, capture_output=True, timeout=300)
            return r.returncode == 0
        finally:
            p.write_text(old)


def inject(kind, cls, line):
    """The mutant of this kind on this line, or None. Flips inject with their own act; kind 1 by its inverse."""
    if kind == 1:
        m = re.search(r"(?<![A-Za-z_\d.])(\d+)(?![\d.\w])", line)
        return None if not m else line[:m.start()] + str(int(m.group(1)) + 1) + line[m.end():]
    c = cls.candidates(line, 1, [line])
    return c[0] if c else None


def harvest_run(g, vocab, suite, rng, budget):
    code_of = {k: int(g[k ^ 5]) for k in vocab}               # the secret numbering: kind -> act code
    kind_at = {c: k for k, c in code_of.items()}
    files = sorted(p for p in (WORK / "src" / "click").glob("*.py"))
    lines_of = {str(p.relative_to(WORK)): p.read_text().split("\n") for p in files}
    taken, log = [], []
    kinds = list(vocab)
    tries = 0
    while True:
        F = [k for k, _ in taken]
        full = len(F) >= 1 and rank([f ^ F[0] for f in F[1:]]) == 4
        spent = suite.runs >= budget
        if full or spent:
            log.append({"act": "STOP", "why": "FULL" if full else "SPENT"})
            break
        tries += 1
        if tries > 400:
            log.append({"act": "STOP", "why": "no more trials"})
            break
        k = kinds[(tries - 1) % len(kinds)]
        new = not F or rank([f ^ F[0] for f in F[1:]] + [k ^ F[0]]) > rank([f ^ F[0] for f in F[1:]])
        known = {"NEW_SPAN": int(new), "FULL": 0, "SPENT": 0, "RECHECKED": 0}
        pre = decided_without(known, ["KILLED", "RESTORES", "UNIQUE", "STABLE"])
        if pre == SKIP:                                         # the law cannot TAKE it - measure nothing
            continue
        sites = [(rel, i) for rel, L in lines_of.items() for i, l in enumerate(L)
                 if l.strip() and not l.lstrip().startswith("#") and inject(k, vocab[k], l) not in (None, l)]
        if not sites:
            continue
        rel, i = rng.choice(sites)
        L = lines_of[rel]
        orig, mut = L[i], inject(k, vocab[k], L[i])
        ML = L[:]; ML[i] = mut
        b = dict(known)
        b["KILLED"] = int(not suite.green(rel, ML, fast=True))
        if b["KILLED"]:
            restoring, greening = [], 0
            for c in range(16):
                kk = kind_at.get(c)
                if kk is None:
                    continue
                for cand in vocab[kk].candidates(mut, i + 1, ML)[:4]:
                    if cand == mut:
                        continue
                    TL = ML[:]; TL[i] = cand
                    if cand == orig:
                        if suite.green(rel, TL):
                            restoring.append(c)
                            greening += 1
                    elif suite.green(rel, TL, fast=True):
                        greening += 1
                if suite.runs >= budget:
                    break
            b["RESTORES"] = int(bool(restoring))
            b["UNIQUE"] = int(len(set(restoring)) == 1 and greening == 1)
            if b["UNIQUE"]:
                RL = ML[:]; RL[i] = orig
                b["STABLE"] = int((not suite.green(rel, ML, fast=True)) and suite.green(rel, RL))
        act = harvest(word(b))
        if act == RECHECK:
            b["RECHECKED"] = 1
            act = harvest(word(b))
        entry = {"kind": k, "class": vocab[k].name, "site": f"{rel}:{i + 1}", "mut": mut.strip()[:60],
                 "bits": {kk: b.get(kk, 0) for kk in ("KILLED", "RESTORES", "UNIQUE", "STABLE", "NEW_SPAN")},
                 "act": ["SKIP", "TAKE", "STOP", "RECHECK"][act], "suite_runs": suite.runs}
        log.append(entry)
        if act == TAKE:
            taken.append((k, restoring[0]))
        print("   ", json.dumps({kk: entry[kk] for kk in ("class", "site", "act", "suite_runs")}), flush=True)
    return taken, code_of, log


def score(taken, code_of, decs, kinds):
    vs = J.VersionSpace(G.affine16())
    pred = {}
    for q in kinds:
        want, _ = vs.expect(taken, q)
        pred[q] = want
    kinds_right = sum(pred[q] == code_of[q] for q in kinds)
    kinds_ref = sum(pred[q] == J.REFUSE for q in kinds)
    d_right = sum(pred[q] == code_of[q] for _, q in decs)
    d_ref = sum(pred[q] == J.REFUSE for _, q in decs)
    d_wrong = len(decs) - d_right - d_ref
    r4 = None
    if len(taken) >= 3:
        r4 = sum(route4d(taken[:3], q) == code_of[q] for _, q in decs)
    return {"kinds": (kinds_right, kinds_ref, len(kinds) - kinds_right - kinds_ref),
            "decisions": (d_right, d_ref, d_wrong, len(decs)), "route4d_first3_right": r4}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--renumberings", type=int, default=2)
    ap.add_argument("--budget", type=int, default=90)
    a = ap.parse_args(argv)
    full_vocab = CB.vocabulary()
    vocab = {k: c for k, c in full_vocab.items() if c.shipped}       # the nine shipped classes
    kinds = list(vocab)
    decs = [(s, k) for s, k in CB.decisions(full_vocab) if k in vocab]
    rng = random.Random(2026)
    H = G.affine16()
    rows = []
    for r in range(a.renumberings):
        g = H[rng.randrange(len(H))]
        suite = Suite()
        t0 = time.time()
        print(f"  renumbering {r + 1}: a secret affine map; harvesting from click ...", flush=True)
        taken, code_of, log = harvest_run(g, vocab, suite, rng, a.budget)
        sc = score(taken, code_of, decs, kinds)
        rows.append({"renumbering": r + 1, "taken": taken, "truth": code_of, "suite_runs": suite.runs,
                     "secs": round(time.time() - t0, 1), "score": sc, "log": log})
        print(f"  -> {len(taken)} examples in {suite.runs} suite runs, {time.time() - t0:.0f}s; {sc}", flush=True)
    out = ["# fluidnet harvests its own worked examples - live, on click", "",
           "Generated by `harvest_live.py`. fluidfix's nine shipped classes, numbered 4D-natively and then renumbered "
           "by a secret affine map; fluidnet discovers the map from its own mutants of click's real source, judged by "
           "click's own 2,240-test suite, with the authored HARVEST law (`laws/harvest.c`) deciding every trial. The "
           "harvested examples then predict every act code by the affine version space (route4d's class).", "",
           "| renumbering | examples harvested | suite runs | seconds | the nine kinds: right / refused / wrong | "
           f"the {len(decs)} real decisions: right / refused / wrong | route4d with the first three |",
           "|---|---|---|---|---|---|---|"]
    for row in rows:
        k, d = row["score"]["kinds"], row["score"]["decisions"]
        out.append(f"| {row['renumbering']} | {len(row['taken'])} | {row['suite_runs']} | {row['secs']} | "
                   f"{k[0]} / {k[1]} / **{k[2]}** | {d[0]} / {d[1]} / **{d[2]}** | "
                   f"{row['score']['route4d_first3_right']}/{d[3]} right |")
    out += ["", "Every trial, in order (`results/harvest_live.json`)."]
    (ROOT / "results/HARVEST_LIVE.md").write_text("\n".join(out) + "\n")
    (ROOT / "results/harvest_live.json").write_text(json.dumps(rows, indent=1, default=str))
    print("\n" + "\n".join(out))
    return 0


if __name__ == "__main__":
    sys.exit(main())
