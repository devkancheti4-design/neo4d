"""Judge a 4D router kernel against the class its author declared - G0-G4 of prompts/ROUTER4D_LAW_PROMPT.md.

    .venv/bin/python judge_router4d.py --class cube --k 3 laws/router4d.c     int32_t router4d(int32_t x)
    .venv/bin/python judge_router4d.py --class xor  --k 1 laws/router4d.py    def router4d(x)
    .venv/bin/python judge_router4d.py --calibrate      fluidfix's own router, judged as the ring law and as
                                                        the 4D ones - the measured defect, reproduced

The judge holds no law. For every word it computes the version space - the relabellings of the declared class
that fit the worked examples - and asks of the kernel only what G0-G4 ask: answer what the class determines,
refuse what it leaves open or cannot explain, and follow any renumbering by the class.

    packing   x = F1 | A1 << 4 | F2 << 8 | A2 << 12 | ... | Fq << 8k
    result    result & 31:  0..15 the action,  16..31 REFUSE
"""
from __future__ import annotations

import argparse
import ctypes
import importlib.util
import os
import random
import subprocess
import sys
import tempfile

from neo4d import generalize as G

CLASSES = {"ring": G.ring16, "xor": G.xor16, "cube": G.cube16, "affine": G.affine16}
REFUSE = 16


def load(path: str, name: str = "router4d", bits: int = 32):
    """Load the kernel; `name` is the function's name in the file; `bits` its word width (32 or 64)."""
    if path.endswith(".py"):
        spec = importlib.util.spec_from_file_location("kernel_router4d", path)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return getattr(mod, name)
    out = os.path.join(tempfile.mkdtemp(prefix="judge_r4d_"), "k.so")
    r = subprocess.run(["cc", "-O2", "-shared", "-fPIC", "-fwrapv", "-o", out, path], capture_output=True, text=True)
    if r.returncode:
        sys.exit(f"{path}: does not compile on its own\n{r.stderr}")
    f = getattr(ctypes.CDLL(out), name)
    t = ctypes.c_int64 if bits == 64 else ctypes.c_int32
    f.argtypes, f.restype = [t], t
    return f


class VersionSpace:
    def __init__(self, H):
        self.H = H
        self.m = len(H)
        self.all = (1 << self.m) - 1
        self.fit = {}
        for f in range(16):
            col = H[:, f]
            for a in range(16):
                bits = 0
                for i in (col == a).nonzero()[0]:
                    bits |= 1 << int(i)
                self.fit[(f, a)] = bits

    def expect(self, ex, q):
        """(expected result, why): the action every fitting relabelling agrees on, else REFUSE."""
        cand = self.all
        for f, a in ex:
            cand &= self.fit[(f, a)]
        if not cand:
            return REFUSE, "G3"
        for a in range(16):
            if cand & ~self.fit[(q, a)] == 0:
                return a, "G2"
        return REFUSE, "G1"


def unpack(x, k):
    ex = [((x >> (8 * i)) & 15, (x >> (8 * i + 4)) & 15) for i in range(k)]
    return ex, (x >> (8 * k)) & 15


def pack(ex, q):
    x = 0
    for i, (f, a) in enumerate(ex):
        x |= f << (8 * i) | a << (8 * i + 4)
    return x | q << (8 * len(ex))


def judge(kernel, cls: str, k: int, sample: int | None = None, seed: int = 2026, verbose: int = 3) -> int:
    H = CLASSES[cls]()
    vs = VersionSpace(H)
    n_words = 1 << (8 * k + 4)
    exhaustive = n_words <= (sample or 200_000) or (sample is None and n_words <= 1 << 20 and vs.m <= 4096)
    rng = random.Random(seed)
    words = range(n_words) if exhaustive else [rng.randrange(n_words) for _ in range(sample or 200_000)]
    bad = {"G0": [], "G1": [], "G2": [], "G3": [], "G4": [], "G5": []}
    checked = 0
    norm = lambda v: v & 15 if (v & 31) < 16 else REFUSE
    for x in words:
        checked += 1
        try:
            got = norm(kernel(x))
        except Exception:
            bad["G5"].append(x)
            continue
        ex, q = unpack(x, k)
        want, why = vs.expect(ex, q)
        if got != want:
            bad[why].append((x, got, want))
        if want != REFUSE and any(f == q for f, _ in ex) and got != want:
            bad["G0"].append((x, got, want))
    # G4: renumber cases by g and actions by h, both drawn from the class
    for _ in range(min(20_000, checked)):
        x = rng.randrange(n_words)
        ex, q = unpack(x, k)
        g, h = H[rng.randrange(vs.m)], H[rng.randrange(vs.m)]
        y = pack([(int(g[f]), int(h[a])) for f, a in ex], int(g[q]))
        a, b = norm(kernel(x)), norm(kernel(y))
        if b != (REFUSE if a == REFUSE else int(h[a])):
            bad["G4"].append((x, a, b))
    print(f"\n  THE 4D ROUTER - class {cls} ({vs.m:,} relabellings), k = {k}")
    print(f"  words judged {'(every one)' if exhaustive else '(seeded sample)':28} {checked:,}")
    names = {"G0": "G0 identity", "G1": "G1 sound - refuse what is open", "G2": "G2 complete - answer what is fixed",
             "G3": "G3 out of class - refuse", "G4": "G4 renumber freely (20,000 draws)", "G5": "G5 total"}
    total = 0
    for key, label in names.items():
        total += len(bad[key])
        print(f"  {label:44} {len(bad[key])}")
        for item in bad[key][:verbose]:
            print(f"      {item}")
    print(f"\n  TOTAL  {total} violations")
    return total


def reduced(kernel, cls: str, k: int) -> int:
    """EVERY word with F1 = A1 = 0: all 16^(2k-1) difference-shapes. With the first example 0 -> 0, the version
    space lives in the maps fixing 0 (for affine: GL(4,2), the linear maps), computed here by brute force - not
    from any derivation of the law. G4, checked above, carries the result to every F1, A1."""
    H = CLASSES[cls]()
    S = H[H[:, 0] == 0]
    vs = VersionSpace(S)
    norm = lambda v: v & 15 if (v & 31) < 16 else REFUSE
    bad = {"G0": 0, "G1": 0, "G2": 0, "G3": 0}
    first = []
    n = 0
    det = und = out = 0
    for rest in range(1 << (8 * (k - 1) + 4)):
        x = rest << 8                               # F1 = A1 = 0
        ex, q = unpack(x, k)
        want, why = vs.expect(ex, q)
        got = norm(kernel(x))
        n += 1
        det += why == "G2"; und += why == "G1"; out += why == "G3"
        if got != want:
            bad[why] += 1
            if len(first) < 3:
                first.append((x, got, want))
        if want != REFUSE and any(f == q for f, _ in ex) and got != want:
            bad["G0"] += 1
    print(f"\n  EXHAUSTIVE over the difference space (F1 = A1 = 0), class {cls} fixing 0: {len(S):,} maps")
    print(f"  words judged (every one)                     {n:,}")
    print(f"  determined {det:,}   open inside the class {und:,}   no map fits {out:,}")
    for key in ("G0", "G1", "G2", "G3"):
        print(f"  {key:44} {bad[key]}")
    for item in first:
        print(f"      {item}")
    total = sum(bad.values())
    print(f"  TOTAL  {total} violations")
    return total


def harvest_shaped(kernel, cls: str, k: int, n: int = 50_000, seed: int = 7) -> int:
    """Words shaped like HARVEST's output: the k worked cases affinely independent (each a new direction), their
    actions from a relabelling of the class. There G2 must answer EVERY query once the cases span the space."""
    H = CLASSES[cls]()
    vs = VersionSpace(H)
    rng = random.Random(seed)
    norm = lambda v: v & 15 if (v & 31) < 16 else REFUSE
    bad, answered, total = [], 0, 0

    def rank(vecs):
        basis = []
        for v in vecs:
            for b in basis:
                v = min(v, v ^ b)
            if v:
                basis.append(v)
        return len(basis)

    for _ in range(n):
        F = [rng.randrange(16)]
        while len(F) < k:
            f = rng.randrange(16)
            if rank([x ^ F[0] for x in F[1:]] + [f ^ F[0]]) > len(F) - 1:
                F.append(f)
        h = H[rng.randrange(len(H))]
        q = rng.randrange(16)
        ex = [(f, int(h[f])) for f in F]
        want, why = vs.expect(ex, q)
        got = norm(kernel(pack(ex, q)))
        total += 1
        answered += got != REFUSE
        if got != want:
            bad.append((pack(ex, q), got, want, why))
    print(f"\n  HARVEST-SHAPED words (k = {k} independent cases, truth in the class): {total:,}")
    print(f"  answered {answered:,} ({100 * answered / total:.1f}%)   violations {len(bad)}")
    for item in bad[:3]:
        print(f"      {item}")
    return len(bad)


def calibrate() -> int:
    """fluidfix's router, verbatim, judged: it must be exactly the ring law at k = 1 - and not the 4D ones."""
    from fluidfix.router import route_packed
    print("  fluidfix's router, verbatim (route_packed), judged against each class at k = 1:")
    res = {c: judge(route_packed, c, 1, verbose=1) for c in CLASSES}
    ok = res["ring"] == 0 and all(res[c] > 0 for c in ("xor", "cube", "affine"))
    print(f"\n  CALIBRATION {'PASS' if ok else 'FAIL'}: the router is the ring law, and only the ring law")
    return 0 if ok else 1


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("kernel", nargs="?")
    ap.add_argument("--class", dest="cls", choices=list(CLASSES), default="cube")
    ap.add_argument("--k", type=int, default=1)
    ap.add_argument("--sample", type=int, default=None)
    ap.add_argument("--calibrate", action="store_true")
    ap.add_argument("--name", default="router4d", help="the kernel function's name in the file")
    ap.add_argument("--bits", type=int, choices=(32, 64), default=32, help="the kernel's word width")
    a = ap.parse_args(argv)
    if a.calibrate:
        return calibrate()
    if not a.kernel:
        ap.error("give a kernel file, or --calibrate")
    kernel = load(a.kernel, a.name, a.bits)
    total = judge(kernel, a.cls, a.k, a.sample)
    if 2 <= a.k <= 3:
        total += reduced(kernel, a.cls, a.k)
    if a.k >= 4:
        total += harvest_shaped(kernel, a.cls, a.k)
    print(f"\n  ALL CHECKS  {total} violations")
    return int(total != 0)


if __name__ == "__main__":
    sys.exit(main())
