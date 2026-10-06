"""Judge a RELATE kernel against the principles of prompts/RELATE_LAW_PROMPT.md - every principle a predicate.

    python -m neo4d.judge_relate laws/relate.c
    python -m neo4d.judge_relate --selfcheck     prove the SPEC complete (the one table the principles allow is built
                                                 only to be perturbed - not a law, not handed over)
"""
from __future__ import annotations

import ctypes
import os
import subprocess
import sys
import tempfile
from collections import Counter

B = lambda x, i: (x >> i) & 1
FIRE, NEWNET, PREDICTED, CHEAP, COSTLY, BARREN = 2, 3, 4, 5, 6, 7
LV = lambda x: x & 3


def reachable(x):
    if B(x, CHEAP) and B(x, COSTLY):
        return False                     # one relation, one cost tier
    if B(x, NEWNET) and not B(x, FIRE):
        return False                     # "first firing in this net" needs a firing
    if LV(x) == 0 and (B(x, PREDICTED) or B(x, BARREN)):
        return False                     # only a remembered relation is applied ahead, or has a record
    if LV(x) == 0 and B(x, FIRE) and not B(x, NEWNET):
        return False                     # an unknown relation's first firing is in a new net
    return True


R = [x for x in range(256) if reachable(x)]
grant = lambda x: max([LV(x)]
                      + ([1] if B(x, FIRE) else [])
                      + ([2] if B(x, FIRE) and B(x, CHEAP) else [])
                      + ([2] if B(x, FIRE) and B(x, NEWNET) and LV(x) >= 1 else [])
                      + ([min(LV(x) + 1, 3)] if B(x, PREDICTED) else []))
weakens = lambda x: B(x, BARREN) and not B(x, CHEAP) and not B(x, PREDICTED) and grant(x) == 2
live = lambda x: not B(x, COSTLY)

PRINCIPLES = {
    "R1 a costly relation is never used": lambda t: [
        x for x in R if B(x, COSTLY) and t[x] != (1 if B(x, FIRE) or LV(x) >= 1 else 0)],
    "R2 silence keeps": lambda t: [
        x for x in R if live(x) and not B(x, FIRE) and not B(x, PREDICTED) and not weakens(x) and t[x] != LV(x)],
    "R3 first sight primes": lambda t: [
        x for x in R if live(x) and LV(x) == 0 and B(x, FIRE) and not B(x, CHEAP) and t[x] != 1],
    "R4 a cheap relation is used at first sight": lambda t: [
        x for x in R if live(x) and B(x, FIRE) and B(x, CHEAP) and t[x] < 2],
    "R5 a second net generalises": lambda t: [
        x for x in R if live(x) and B(x, FIRE) and B(x, NEWNET) and LV(x) >= 1 and not weakens(x) and t[x] < 2],
    "R6 a correct prediction potentiates by one": lambda t: [
        x for x in R if live(x) and B(x, PREDICTED) and t[x] != max(grant(x), min(LV(x) + 1, 3))],
    "R7 proven only by prediction": lambda t: [
        x for x in R if t[x] == 3 and LV(x) < 3 and not B(x, PREDICTED)],
    "R8 nothing else raises": lambda t: [
        x for x in R if live(x) and not weakens(x) and t[x] != grant(x)],
    "R9 a barren relation weakens unless cheap or proven": lambda t: [
        x for x in R if live(x) and weakens(x) and t[x] != 1],
}


def violations(t):
    return {name: chk(t) for name, chk in PRINCIPLES.items()}


def loose_cells(t):
    out = []
    for x in R:
        for v in range(4):
            if v != t[x]:
                t2 = t[:]
                t2[x] = v
                if not any(violations(t2).values()):
                    out.append((x, v))
    return out


def load(path, name="relate"):
    out = os.path.join(tempfile.mkdtemp(prefix="judge_rel_"), "r.so")
    r = subprocess.run(["cc", "-O2", "-Wall", "-Wextra", "-std=c99", "-shared", "-fPIC", "-o", out, path],
                       capture_output=True, text=True)
    if r.returncode:
        sys.exit(r.stderr)
    f = getattr(ctypes.CDLL(out), name)
    f.argtypes, f.restype = [ctypes.c_int32], ctypes.c_int32
    return [f(x) for x in range(256)]


def report(t, label):
    total = 0
    print(f"\n  THE RELATE LAW - {label}\n  reachable words {len(R)}")
    for name, bad in violations(t).items():
        total += len(bad)
        print(f"  {name:52} {len(bad)}  {bad[:4] if bad else ''}")
    rng = [x for x in range(256) if not 0 <= t[x] <= 3]
    total += len(rng)
    print(f"  {'lands in 0..3 on all 256':52} {len(rng)}")
    lc = loose_cells(t)
    total += len(lc)
    print(f"  {'single-cell changes no principle catches':52} {len(lc)}  {lc[:4] if lc else ''}")
    print(f"\n  TOTAL  {total} violations")
    return total


def spec_table():
    """The one table R1-R9 allow - for the selfcheck and the pre-check on the fix stream only."""
    t = [0] * 256
    for x in R:
        if B(x, COSTLY):
            t[x] = 1 if B(x, FIRE) or LV(x) >= 1 else 0
        elif weakens(x):
            t[x] = 1
        else:
            t[x] = grant(x)
    return t


def selfcheck():
    t = spec_table()
    moves = Counter((LV(x), t[x]) for x in R)
    print("  level -> new level on reachable words:", dict(sorted(moves.items())))
    return report(t, "SPEC SELFCHECK (the unique table the principles allow; not shipped)")


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--selfcheck":
        sys.exit(int(selfcheck() != 0))
    sys.exit(int(report(load(sys.argv[1] if len(sys.argv) > 1 else "laws/relate.c"), sys.argv[-1]) != 0))
