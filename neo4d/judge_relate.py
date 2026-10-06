"""Judge a RELATE kernel against its principles - every principle a predicate.

    v1  prompts/RELATE_LAW_PROMPT.md       R9: a barren relation weakens unless cheap or proven
    v2  prompts/RELATE_V2_LAW_PROMPT.md    R9: a barren relation weakens unless proven (R4 yields to it)

    python -m neo4d.judge_relate laws/relate.c [--v2]
    python -m neo4d.judge_relate --selfcheck [--v2]   prove the SPEC complete (the one table the principles allow is
                                                      built only to be perturbed - not a law, not handed over)
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
live = lambda x: not B(x, COSTLY)


def weakens_for(version):
    if version == 1:
        return lambda x: B(x, BARREN) and not B(x, CHEAP) and not B(x, PREDICTED) and grant(x) == 2
    return lambda x: B(x, BARREN) and not B(x, PREDICTED) and grant(x) == 2


def principles(version=1):
    wk = weakens_for(version)
    r9 = "R9 a barren relation weakens unless cheap or proven" if version == 1 else \
        "R9 a barren relation weakens unless proven"
    r4 = "R4 a cheap relation is used at first sight" + ("" if version == 1 else " (unless R9)")
    return {
        "R1 a costly relation is never used": lambda t: [
            x for x in R if B(x, COSTLY) and t[x] != (1 if B(x, FIRE) or LV(x) >= 1 else 0)],
        "R2 silence keeps": lambda t: [
            x for x in R if live(x) and not B(x, FIRE) and not B(x, PREDICTED) and not wk(x) and t[x] != LV(x)],
        "R3 first sight primes": lambda t: [
            x for x in R if live(x) and LV(x) == 0 and B(x, FIRE) and not B(x, CHEAP) and t[x] != 1],
        r4: lambda t: [
            x for x in R if live(x) and B(x, FIRE) and B(x, CHEAP) and not wk(x) and t[x] < 2],
        "R5 a second net generalises": lambda t: [
            x for x in R if live(x) and B(x, FIRE) and B(x, NEWNET) and LV(x) >= 1 and not wk(x) and t[x] < 2],
        "R6 a correct prediction potentiates by one": lambda t: [
            x for x in R if live(x) and B(x, PREDICTED) and t[x] != max(grant(x), min(LV(x) + 1, 3))],
        "R7 proven only by prediction": lambda t: [
            x for x in R if t[x] == 3 and LV(x) < 3 and not B(x, PREDICTED)],
        "R8 nothing else raises": lambda t: [
            x for x in R if live(x) and not wk(x) and t[x] != grant(x)],
        r9: lambda t: [
            x for x in R if live(x) and wk(x) and t[x] != 1],
    }


weakens = weakens_for(1)
PRINCIPLES = principles(1)


def violations(t, version=1):
    return {name: chk(t) for name, chk in principles(version).items()}


def loose_cells(t, version=1):
    out = []
    for x in R:
        for v in range(4):
            if v != t[x]:
                t2 = t[:]
                t2[x] = v
                if not any(violations(t2, version).values()):
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


def report(t, label, version=1):
    total = 0
    print(f"\n  THE RELATE LAW v{version} - {label}\n  reachable words {len(R)}")
    for name, bad in violations(t, version).items():
        total += len(bad)
        print(f"  {name:52} {len(bad)}  {bad[:4] if bad else ''}")
    rng = [x for x in range(256) if not 0 <= t[x] <= 3]
    total += len(rng)
    print(f"  {'lands in 0..3 on all 256':52} {len(rng)}")
    lc = loose_cells(t, version)
    total += len(lc)
    print(f"  {'single-cell changes no principle catches':52} {len(lc)}  {lc[:4] if lc else ''}")
    print(f"\n  TOTAL  {total} violations")
    return total


def spec_table(version=1):
    """The one table R1-R9 allow - for the selfcheck and the pre-checks on the streams only."""
    wk = weakens_for(version)
    t = [0] * 256
    for x in R:
        if B(x, COSTLY):
            t[x] = 1 if B(x, FIRE) or LV(x) >= 1 else 0
        elif wk(x):
            t[x] = 1
        else:
            t[x] = grant(x)
    return t


def selfcheck(version=1):
    t = spec_table(version)
    moves = Counter((LV(x), t[x]) for x in R)
    print("  level -> new level on reachable words:", dict(sorted(moves.items())))
    if version == 2:
        t1 = spec_table(1)
        diff = [x for x in R if t[x] != t1[x]]
        print(f"  cells where v2 differs from v1: {len(diff)} - every one BARREN and CHEAP: "
              f"{all(B(x, BARREN) and B(x, CHEAP) for x in diff)}")
    return report(t, "SPEC SELFCHECK (the unique table the principles allow; not shipped)", version)


if __name__ == "__main__":
    args = sys.argv[1:]
    version = 2 if "--v2" in args else 1
    if "--selfcheck" in args:
        sys.exit(int(selfcheck(version) != 0))
    path = next((a for a in args if a.endswith(".c")), "laws/relate.c")
    sys.exit(int(report(load(path), path, version) != 0))
