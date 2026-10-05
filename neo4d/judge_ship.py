"""Judge a SHIP kernel against the principles of prompts/SHIP_LAW_PROMPT.md - every principle a predicate.

    python -m neo4d.judge_ship laws/ship.c
    python -m neo4d.judge_ship --selfcheck     prove the SPEC complete (the one table the principles allow is built only
                                               to be perturbed - not a law, not handed over)
"""
from __future__ import annotations

import ctypes
import os
import subprocess
import sys
import tempfile

REFUSE, ASK, SHIP, SHIP_PROVEN = 0, 1, 2, 3
B = lambda x, i: (x >> i) & 1
WAS_RED, GREEN, STABLE, UNIQUE, PROVEN, REFUTED, THIN, ROUTED = range(8)


def reachable(x):
    if B(x, PROVEN) and B(x, REFUTED):
        return False                     # a property either proves or refutes a rewrite
    if B(x, UNIQUE) and not B(x, GREEN):
        return False                     # "the only candidate that turns the suite green" needs green
    return True


R = [x for x in range(256) if reachable(x)]
gate = lambda x: (B(x, WAS_RED) and B(x, GREEN) and B(x, STABLE) and not B(x, REFUTED) and B(x, ROUTED))
shippable = lambda x: gate(x) and B(x, UNIQUE) and (B(x, PROVEN) or not B(x, THIN))

PRINCIPLES = {
    "R0 no premise, no repair": lambda t: [x for x in R if not B(x, WAS_RED) and t[x] != REFUSE],
    "R1 only a stable green ships": lambda t: [x for x in R if (not B(x, GREEN) or not B(x, STABLE)) and t[x] != REFUSE],
    "R2 a refuted rewrite never ships": lambda t: [x for x in R if B(x, REFUTED) and t[x] != REFUSE],
    "R3 an undetermined act never ships": lambda t: [x for x in R if not B(x, ROUTED) and t[x] != REFUSE],
    "R4 ambiguity asks": lambda t: [x for x in R if gate(x) and not B(x, UNIQUE) and t[x] != ASK],
    "R5 thin evidence needs proof": lambda t: [x for x in R if gate(x) and B(x, UNIQUE) and B(x, THIN)
                                               and not B(x, PROVEN) and t[x] != ASK],
    "R6 ship, graded": lambda t: [x for x in R if shippable(x) and t[x] != (SHIP_PROVEN if B(x, PROVEN) else SHIP)],
    "R7 nothing ships outside R6": lambda t: [x for x in R if t[x] in (SHIP, SHIP_PROVEN) and not shippable(x)],
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


def load(path, name="ship"):
    out = os.path.join(tempfile.mkdtemp(prefix="judge_s_"), "s.so")
    r = subprocess.run(["cc", "-O2", "-Wall", "-Wextra", "-std=c99", "-shared", "-fPIC", "-o", out, path],
                       capture_output=True, text=True)
    if r.returncode:
        sys.exit(r.stderr)
    f = getattr(ctypes.CDLL(out), name)
    f.argtypes, f.restype = [ctypes.c_int32], ctypes.c_int32
    return [f(x) for x in range(256)]


def report(t, label):
    total = 0
    print(f"\n  THE SHIP LAW - {label}\n  reachable words {len(R)}")
    for name, bad in violations(t).items():
        total += len(bad)
        print(f"  {name:44} {len(bad)}  {bad[:4] if bad else ''}")
    rng = [x for x in range(256) if not 0 <= t[x] <= 3]
    total += len(rng)
    print(f"  {'lands in 0..3 on all 256':44} {len(rng)}")
    lc = loose_cells(t)
    total += len(lc)
    print(f"  {'single-cell changes no principle catches':44} {len(lc)}  {lc[:4] if lc else ''}")
    print(f"\n  TOTAL  {total} violations")
    return total


def selfcheck():
    t = [0] * 256
    for x in R:
        if not gate(x):
            t[x] = REFUSE
        elif not B(x, UNIQUE) or (B(x, THIN) and not B(x, PROVEN)):
            t[x] = ASK
        else:
            t[x] = SHIP_PROVEN if B(x, PROVEN) else SHIP
    from collections import Counter
    print("  verdicts on reachable words:", dict(Counter(["REFUSE", "ASK", "SHIP", "SHIP_PROVEN"][t[x]] for x in R)))
    return report(t, "SPEC SELFCHECK (the unique table the principles allow; not shipped)")


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--selfcheck":
        sys.exit(int(selfcheck() != 0))
    sys.exit(int(report(load(sys.argv[1] if len(sys.argv) > 1 else "laws/ship.c"), sys.argv[-1]) != 0))
