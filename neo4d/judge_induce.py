"""Judge an INDUCE kernel against the principles of prompts/INDUCE_LAW_PROMPT.md - every principle a predicate.

    .venv/bin/python judge_induce.py laws/induce.c
    .venv/bin/python judge_induce.py --selfcheck      prove the SPEC complete (the one table the principles allow is
                                                      built only to be perturbed - not a law, not handed over)
"""
from __future__ import annotations

import ctypes
import os
import subprocess
import sys
import tempfile

REJECT, KEEP, ADMIT, RETIRE = 0, 1, 2, 3
B = lambda x, i: (x >> i) & 1
SEEN2, SEEN5, CONFIRMED, REFUTED, PROVABLE, CONFLICT, NOISY, ADMITTED = range(8)


def reachable(x):
    if B(x, SEEN5) and not B(x, SEEN2):
        return False
    if B(x, CONFIRMED) and not B(x, SEEN2):
        return False
    return True


R = [x for x in range(256) if reachable(x)]
admissible = lambda x: (B(x, CONFIRMED) and B(x, PROVABLE) and B(x, SEEN2) and not B(x, CONFLICT)
                        and (not B(x, NOISY) or B(x, SEEN5)))

PRINCIPLES = {
    "I0 a refuted class never stays":
        lambda t: [x for x in R if B(x, REFUTED) and t[x] != (RETIRE if B(x, ADMITTED) else REJECT)],
    "I1 ADMIT iff proven prospectively, guarded, uncontested":
        lambda t: [x for x in R if (t[x] == ADMIT) != bool(not B(x, ADMITTED) and not B(x, REFUTED) and admissible(x))],
    "I2 an admitted, unrefuted class stays":
        lambda t: [x for x in R if B(x, ADMITTED) and not B(x, REFUTED) and t[x] != KEEP],
    "I3 otherwise keep watching":
        lambda t: [x for x in R if not B(x, ADMITTED) and not B(x, REFUTED) and not admissible(x) and t[x] != KEEP],
    "I4 RETIRE only an admitted, refuted class":
        lambda t: [x for x in R if t[x] == RETIRE and not (B(x, ADMITTED) and B(x, REFUTED))],
    "I5 REJECT only a refuted candidate":
        lambda t: [x for x in R if t[x] == REJECT and not (B(x, REFUTED) and not B(x, ADMITTED))],
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


def load(path, name="induce"):
    out = os.path.join(tempfile.mkdtemp(prefix="judge_i_"), "i.so")
    r = subprocess.run(["cc", "-O2", "-Wall", "-Wextra", "-std=c99", "-shared", "-fPIC", "-o", out, path],
                       capture_output=True, text=True)
    if r.returncode:
        sys.exit(r.stderr)
    f = getattr(ctypes.CDLL(out), name)
    f.argtypes, f.restype = [ctypes.c_int32], ctypes.c_int32
    return [f(x) for x in range(256)]


def report(t, label):
    total = 0
    print(f"\n  THE INDUCE LAW - {label}\n  reachable words {len(R)}")
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


def selfcheck():
    t = [0] * 256
    for x in R:
        if B(x, REFUTED):
            t[x] = RETIRE if B(x, ADMITTED) else REJECT
        elif B(x, ADMITTED):
            t[x] = KEEP
        else:
            t[x] = ADMIT if admissible(x) else KEEP
    return report(t, "SPEC SELFCHECK (the unique table the principles allow; not shipped)")


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--selfcheck":
        sys.exit(int(selfcheck() != 0))
    sys.exit(int(report(load(sys.argv[1] if len(sys.argv) > 1 else str(KERNELS / "induce.c")), sys.argv[-1]) != 0))
