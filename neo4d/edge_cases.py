"""Edge cases of the 4D routers, against the brute-force group - the shortcut must mirror all 322,560 maps.

    1  AMBIGUITY MATRIX   example sets of every rank 0..4 (consistent, truth in the class). The brute-force count of
                          surviving maps must equal the group-theoretic count, a query outside the span must be
                          REFUSED (with 16 - 2^rank answers still open), and a query inside the span answered exactly.
    2  CONTRADICTIONS     three ways no affine map can fit: the same case with two actions (dF = 0, dA != 0), two
                          cases with one action (dF != 0, dA = 0), and a dependent case set whose actions are not
                          dependent. Brute force must find 0 maps, and the router must refuse every query.
    3  DIFFERENTIAL       200,000 random scenarios - examples from a random affine truth, from a random
                          non-affine map, or random noise - every query compared with the brute-force version space.

Run against route4d (k = 3, 32-bit) and route4d5 (k = 5, 64-bit); fewer examples are given by repeating one, which
adds no information.

    python -m neo4d.edge_cases       -> results/EDGE_CASES.md
"""
from __future__ import annotations

import random
import sys
from collections import Counter

from neo4d import KERNELS, REPO
from neo4d import judge_router4d as R4

H = R4.CLASSES["affine"]()
VS = R4.VersionSpace(H)
REF = R4.REFUSE
EXPECTED = {0: 20160, 1: 1344, 2: 96, 3: 8, 4: 1}


def rank(vecs):
    basis = []
    for v in vecs:
        for b in basis:
            v = min(v, v ^ b)
        if v:
            basis.append(v)
    return len(basis)


def survivors(ex):
    cand = VS.all
    for f, a in ex:
        cand &= VS.fit[(f, a)]
    return cand


def answers(cand, q):
    return {a for a in range(16) if cand & VS.fit[(q, a)]}


def kernels():
    k3 = R4.load(str(KERNELS / "router4d.c"), "route4d")
    k5 = R4.load(str(KERNELS / "router4d5.c"), "route4d5", 64)
    norm = lambda v: v & 15 if (v & 31) < 16 else REF

    def r3(ex, q):
        ex = (ex + [ex[0]] * 3)[:3]
        return norm(k3(R4.pack(ex, q)))

    def r5(ex, q):
        ex = (ex + [ex[0]] * 5)[:5]
        return norm(k5(R4.pack(ex, q)))
    return {"route4d (k=3)": (r3, 3), "route4d5 (k=5)": (r5, 5)}


def examples_of_rank(r, k, rng):
    """k examples from a random affine truth whose case differences span exactly dimension r (k >= r + 1)."""
    while True:
        h = H[rng.randrange(len(H))]
        F1 = rng.randrange(16)
        basis = []
        while len(basis) < r:
            v = rng.randrange(1, 16)
            if rank(basis + [v]) > len(basis):
                basis.append(v)
        span = [0]
        for b in basis:
            span += [s ^ b for s in span]
        Fs = [F1] + [F1 ^ b for b in basis]
        while len(Fs) < k:
            Fs.append(F1 ^ rng.choice(span))
        rng.shuffle(Fs)
        if rank([f ^ Fs[0] for f in Fs[1:]]) == r:
            return [(f, int(h[f])) for f in Fs], h, span, Fs[0]


def ambiguity(routers, rng, per=300):
    rows, bad = [], 0
    for name, (route, kmax) in routers.items():
        for r in range(0, min(4, kmax - 1) + 1):
            surv, open_ans, refused_out, right_in, n_out, n_in = Counter(), Counter(), 0, 0, 0, 0
            for _ in range(per):
                ex, h, span, F1 = examples_of_rank(r, min(kmax, r + 1 + rng.randrange(0, kmax - r)), rng)
                cand = survivors(ex)
                surv[bin(cand).count("1")] += 1
                for q in range(16):
                    got = route(ex, q)
                    if (q ^ F1) in span:
                        n_in += 1
                        right_in += got == int(h[q])
                    else:
                        n_out += 1
                        open_ans[len(answers(cand, q))] += 1
                        refused_out += got == REF
            ok = (set(surv) == {EXPECTED[r]} and refused_out == n_out and right_in == n_in
                  and (r == 4 or set(open_ans) == {16 - 2 ** r}))
            bad += not ok
            rows.append((name, r, dict(surv), EXPECTED[r], dict(open_ans), f"{refused_out}/{n_out}", f"{right_in}/{n_in}", ok))
    return rows, bad


def contradictions(routers, rng, per=2000):
    rows, bad = [], 0
    for name, (route, kmax) in routers.items():
        for kind in ("same case, two actions (dF = 0, dA != 0)", "two cases, one action (dF != 0, dA = 0)",
                     "dependent cases, independent actions"):
            zero_maps, refused, total = 0, 0, 0
            for _ in range(per):
                ex, h, span, F1 = examples_of_rank(min(2, kmax - 2), kmax - 1, rng)
                f0, a0 = ex[0]
                if kind.startswith("same case"):
                    ex = ex + [(f0, a0 ^ rng.randrange(1, 16))]
                elif kind.startswith("two cases"):
                    f1 = rng.choice([f for f in range(16) if f != f0])
                    ex = [(f0, a0), (f1, a0)] + ex[1:kmax - 1]
                else:
                    (fa, aa), (fb, ab) = ex[1], ex[2] if len(ex) > 2 else ex[1]
                    if kmax < 4 or fa == fb:
                        fa, aa = ex[1]
                        ex = [(f0, a0), (fa, aa), (f0 ^ fa ^ f0, aa ^ rng.randrange(1, 16))]
                    else:
                        ex = ex[:3] + [(f0 ^ fa ^ fb, a0 ^ aa ^ ab ^ rng.randrange(1, 16))]
                ex = ex[:kmax]
                cand = survivors(ex)
                zero_maps += cand == 0
                for q in range(16):
                    total += 1
                    refused += route(ex, q) == REF
            ok = zero_maps == per and refused == total
            bad += not ok
            rows.append((name, kind, f"{zero_maps}/{per}", f"{refused}/{total}", ok))
    return rows, bad


def differential(routers, rng, n=200_000):
    rows, bad = [], 0
    nonaffine = [list(rng.sample(range(16), 16)) for _ in range(500)]
    for name, (route, kmax) in routers.items():
        dis = Counter()
        kinds = Counter()
        for i in range(n):
            mode = i % 3
            Fs = [rng.randrange(16) for _ in range(kmax)]
            if mode == 0:
                h = H[rng.randrange(len(H))]
                ex = [(f, int(h[f])) for f in Fs]
            elif mode == 1:
                p = nonaffine[i % 500]
                ex = [(f, p[f]) for f in Fs]
            else:
                ex = [(f, rng.randrange(16)) for f in Fs]
            q = rng.randrange(16)
            cand = survivors(ex)
            ans = answers(cand, q)
            want = next(iter(ans)) if len(ans) == 1 else REF
            got = route(ex, q)
            kinds["determined" if want != REF else ("no map fits" if not cand else "open")] += 1
            if got != want:
                dis[["affine truth", "non-affine truth", "noise"][mode]] += 1
        bad += sum(dis.values())
        rows.append((name, n, dict(kinds), sum(dis.values())))
    return rows, bad


def main() -> int:
    rng = random.Random(2026)
    routers = kernels()
    a_rows, a_bad = ambiguity(routers, rng)
    c_rows, c_bad = contradictions(routers, rng)
    d_rows, d_bad = differential(routers, rng)
    out = ["# The 4D routers against the brute-force group - edge cases", "",
           "Generated by `neo4d/edge_cases.py`. Every count is brute force over all 322,560 affine maps of GF(2)^4.", "",
           "## 1. Ambiguity matrix - example sets of every rank", "",
           "| router | rank | maps surviving (brute force) | group count | answers still open (out of span) | "
           "out-of-span queries refused | in-span queries right | |",
           "|---|---|---|---|---|---|---|---|"]
    for name, r, surv, exp, op, ref, rin, ok in a_rows:
        out.append(f"| {name} | {r} | {surv} | {exp:,} | {op or '-'} | {ref} | {rin} | {'PASS' if ok else 'FAIL'} |")
    out += ["", "## 2. Contradiction injection", "",
            "| router | contradiction | brute force: no map fits | queries refused | |", "|---|---|---|---|---|"]
    for name, kind, z, ref, ok in c_rows:
        out.append(f"| {name} | {kind} | {z} | {ref} | {'PASS' if ok else 'FAIL'} |")
    out += ["", "## 3. Differential - router vs brute force, every query", "",
            "| router | scenarios | kinds of query | disagreements |", "|---|---|---|---|"]
    for name, n, kinds, d in d_rows:
        out.append(f"| {name} | {n:,} | {kinds} | **{d}** |")
    total = a_bad + c_bad + d_bad
    out += ["", f"**TOTAL: {total} failures.**"]
    (REPO / "results" / "EDGE_CASES.md").write_text("\n".join(out) + "\n")
    print("\n".join(out))
    return int(total != 0)


if __name__ == "__main__":
    sys.exit(main())
