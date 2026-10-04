"""Judge a PICK kernel against the principles of prompts/PICK_LAW_PROMPT.md - every principle a predicate.

    .venv/bin/python judge_pick.py laws/pick.c        judge a kernel
    .venv/bin/python judge_pick.py --selfcheck        prove the SPEC complete: exactly one table satisfies the
                                                      principles (built here only to be perturbed - it is not
                                                      a law, and it is not handed to the author)
"""
from __future__ import annotations

import ctypes
import os
import subprocess
import sys
import tempfile

B = lambda x, i: (x >> i) & 1
NEW_SPAN, EXECUTED, TRIED, ALT_NONE, MANY_TESTS, NAMED, COLD, RESERVED = range(8)


def reachable(x):
    if B(x, RESERVED):
        return False
    if B(x, MANY_TESTS) and not B(x, EXECUTED):
        return False
    return True


R = [x for x in range(256) if reachable(x)]
veto = lambda x: (not B(x, NEW_SPAN)) or (not B(x, EXECUTED)) or B(x, TRIED)
strong = lambda x: B(x, ALT_NONE)
weak = lambda x: B(x, MANY_TESTS) + B(x, NAMED)
live = lambda t: [x for x in R if not veto(x)]

PRINCIPLES = {
    "P0 the veto": lambda t: [x for x in R if veto(x) and t[x] != 0],
    "P1 one strong beats any number of weak":
        lambda t: sorted({x for x in live(t) for y in live(t) if strong(x) > strong(y) and t[x] <= t[y]}),
    "P2 weak counted, not weighted":
        lambda t: sorted({x for x in live(t) for y in live(t) if strong(x) == strong(y) and
                          ((weak(x) > weak(y) and t[x] <= t[y]) or
                           (weak(x) == weak(y) and B(x, COLD) == B(y, COLD) and t[x] != t[y]))}),
    "P3 history breaks ties only":
        lambda t: sorted({x for x in live(t) for y in live(t) if strong(x) == strong(y) and weak(x) == weak(y)
                          and not B(x, COLD) and B(y, COLD) and t[x] <= t[y]}),
    "P4 usable unless vetoed": lambda t: [x for x in live(t) if t[x] < 1],
    "P5 dense, 0..12": lambda t: [] if {t[x] for x in R} == set(range(13)) else [min(R)],
}


def violations(t):
    return {name: chk(t) for name, chk in PRINCIPLES.items()}


def load(path, name="pick"):
    out = os.path.join(tempfile.mkdtemp(prefix="judge_p_"), "p.so")
    r = subprocess.run(["cc", "-O2", "-Wall", "-Wextra", "-std=c99", "-shared", "-fPIC", "-o", out, path],
                       capture_output=True, text=True)
    if r.returncode:
        sys.exit(r.stderr)
    f = getattr(ctypes.CDLL(out), name)
    f.argtypes, f.restype = [ctypes.c_int32], ctypes.c_int32
    return [f(x) for x in range(256)]


def loose_cells(t):
    out = []
    for x in R:
        for v in range(16):
            if v == t[x]:
                continue
            t2 = t[:]
            t2[x] = v
            if not any(violations(t2).values()):
                out.append((x, v))
    return out


def report(t, label):
    total = 0
    print(f"\n  THE PICK LAW - {label}\n  reachable words {len(R)}")
    for name, bad in violations(t).items():
        total += len(bad)
        print(f"  {name:44} {len(bad)}  {bad[:4] if bad else ''}")
    rng = [x for x in range(256) if not 0 <= t[x] <= 15]
    total += len(rng)
    print(f"  {'lands in 0..15 on all 256':44} {len(rng)}")
    lc = loose_cells(t)
    total += len(lc)
    print(f"  {'single-cell changes no principle catches':44} {len(lc)}  {lc[:4] if lc else ''}")
    print(f"\n  TOTAL  {total} violations")
    return total


def selfcheck():
    """Is the spec complete? Construct the one table the principles allow and show nothing else passes."""
    order = sorted({(strong(x), weak(x), 1 - B(x, COLD)) for x in R if not veto(x)})
    t = [0] * 256
    for x in R:
        if not veto(x):
            t[x] = 1 + order.index((strong(x), weak(x), 1 - B(x, COLD)))
    return report(t, "SPEC SELFCHECK (the unique table the principles allow; not shipped)")


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--selfcheck":
        sys.exit(int(selfcheck() != 0))
    sys.exit(int(report(load(sys.argv[1] if len(sys.argv) > 1 else str(KERNELS / "pick.c")), sys.argv[-1]) != 0))
