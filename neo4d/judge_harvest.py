"""Judge a HARVEST kernel against the principles of prompts/HARVEST_LAW_PROMPT.md - no truth table, no oracle.

Every principle is a predicate on (x, harvest(x)); the iff reading (as corrected) is the one checked. Then the test
that the principles FIX the table is run on the kernel's own table: every single-cell change to it, on every
reachable word, must break at least one principle.

    .venv/bin/python judge_harvest.py laws/harvest.c
"""
from __future__ import annotations

import ctypes
import os
import subprocess
import sys
import tempfile

SKIP, TAKE, STOP, RECHECK = 0, 1, 2, 3
B = lambda x, i: (x >> i) & 1
KILLED, RESTORES, UNIQUE, STABLE, NEW, RECHECKED, FULL, SPENT = range(8)


def reachable(x):
    if not B(x, KILLED) and (B(x, RESTORES) or B(x, UNIQUE) or B(x, STABLE)):
        return False
    if B(x, UNIQUE) and not B(x, RESTORES):
        return False
    if B(x, FULL) and B(x, NEW):
        return False
    return True


R = [x for x in range(256) if reachable(x)]
stopping = lambda x: B(x, FULL) or B(x, SPENT)
takeable = lambda x: (B(x, KILLED) and B(x, RESTORES) and B(x, UNIQUE) and B(x, STABLE) and B(x, NEW))

PRINCIPLES = {
    "H0 no oracle, no example": lambda t: [x for x in R if not B(x, KILLED) and t[x] == TAKE],
    "H1+H3 TAKE iff unambiguous, stable, new (not stopping)":
        lambda t: [x for x in R if (t[x] == TAKE) != bool(not stopping(x) and takeable(x))],
    "H2 unstable: RECHECK once, then SKIP":
        lambda t: [x for x in R if not stopping(x) and B(x, KILLED) and not B(x, STABLE)
                   and t[x] != (SKIP if B(x, RECHECKED) else RECHECK)],
    "H4 FULL: STOP": lambda t: [x for x in R if B(x, FULL) and t[x] != STOP],
    "H5 SPENT and not FULL: STOP": lambda t: [x for x in R if B(x, SPENT) and not B(x, FULL) and t[x] != STOP],
    "H6 otherwise SKIP": lambda t: [x for x in R if not stopping(x) and not takeable(x)
                                    and not (B(x, KILLED) and not B(x, STABLE)) and t[x] != SKIP],
    "H7 RECHECK only for instability": lambda t: [x for x in R if t[x] == RECHECK
                                                  and (B(x, STABLE) or B(x, RECHECKED) or not B(x, KILLED))],
    "STOP only when FULL or SPENT": lambda t: [x for x in R if t[x] == STOP and not stopping(x)],
}


def load(path, name="harvest"):
    out = os.path.join(tempfile.mkdtemp(prefix="judge_h_"), "h.so")
    r = subprocess.run(["cc", "-O2", "-Wall", "-Wextra", "-Werror", "-std=c99", "-shared", "-fPIC", "-o", out, path],
                       capture_output=True, text=True)
    if r.returncode:
        sys.exit(r.stderr)
    f = getattr(ctypes.CDLL(out), name)
    f.argtypes, f.restype = [ctypes.c_int32], ctypes.c_int32
    return [f(x) for x in range(256)]


def main(path):
    t = load(path)
    total = 0
    print(f"\n  THE HARVEST LAW - {path}\n  reachable words {len(R)}")
    for name, chk in PRINCIPLES.items():
        bad = chk(t)
        total += len(bad)
        print(f"  {name:56} {len(bad)}  {bad[:4] if bad else ''}")
    rng = [x for x in range(256) if not 0 <= t[x] <= 3]
    total += len(rng)
    print(f"  {'lands in 0..3 on all 256':56} {len(rng)}")
    loose = []
    for x in R:
        for v in range(4):
            if v == t[x]:
                continue
            t2 = t[:]
            t2[x] = v
            if not any(chk(t2) for chk in PRINCIPLES.values()):
                loose.append((x, v))
    total += len(loose)
    print(f"  {'single-cell changes no principle catches':56} {len(loose)}  {loose[:4] if loose else ''}")
    inert = [x for x in R if reachable(x ^ 2) and t[x] != t[x ^ 2]]
    print(f"  {'reachable words where RESTORES changes the act':56} {len(inert)}   (the author's claim: 0)")
    print(f"\n  TOTAL  {total} violations")
    return int(total != 0)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1] if len(sys.argv) > 1 else str(KERNELS / "harvest.c")))
