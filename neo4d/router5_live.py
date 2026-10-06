"""route5 live at 32 kinds - the kit's federation and degeneracy tests rerun with the authored law (neo4d/kernels/
router5.c) in place of the reference, against the exact values of results/ROUTER5_MATH.md.

    FEDERATION   party A knows the act for all 32 kinds; party B numbers them its own way. They share only k anchors
                 (A's code, B's code); the law learns the correspondence and B translates A's table. B's numbering
                 affine (inside the structure) or arbitrary (a random permutation); anchors random or span-aware;
                 k = 6 plus validation anchors 7..9 that must agree with the fit, or B refuses.
    DEGENERACY   12 examples on an affine plane of rank 2 or 3 (the suite says the same thing several times); the law
                 takes 6 that span it: queries inside answered and right, outside refused, and a different 6 of the
                 same 12 must give the same answers.
    ADVERSARY    5 examples of an affine truth plus a 6th one bit wrong - a repeated case with one action bit flipped,
                 or a dependent case one bit off its combination: every query refused.

    python -m neo4d.router5_live   -> results/ROUTER5_LIVE.md
"""
from __future__ import annotations

import ctypes
import math
import random
import sys
from collections import Counter

from neo4d import REPO, build_kernel
from neo4d.router5_math import affine32, answered_as_they_come, outside, rank, span_aware


def law():
    f = ctypes.CDLL(str(build_kernel("router5"))).route5
    f.argtypes, f.restype = [ctypes.c_int64], ctypes.c_int64

    def route(ex, q):
        """The body: example 1 to the origin, ask the law, move the answer back."""
        (F1, A1), rest = ex[0], ex[1:]
        rest = (list(rest) + [ex[0]] * 5)[:5]
        x = 0
        for i, (f_, a) in enumerate(rest):
            x |= (f_ ^ F1) << (10 * i) | (a ^ A1) << (10 * i + 5)
        v = int(f(x | (q ^ F1) << 50)) & 63
        return None if v >= 32 else v ^ A1
    return route


def federation(rng, route, n):
    rows, bad = [], 0
    a_rand = answered_as_they_come(5, 6)
    for affine_b, anchors, k in ((True, "random", 6), (True, "span-aware", 6), (False, "span-aware", 6),
                                 (False, "span-aware", 7), (False, "span-aware", 8), (False, "span-aware", 9)):
        c = Counter()
        for _ in range(n):
            NA = affine32(rng)
            NB = affine32(rng) if affine_b else rng.sample(range(32), 32)
            kind = [0] * 32
            for f_, v in enumerate(NA):
                kind[v] = f_
            M = [NB[kind[a]] for a in range(32)]
            acts = [rng.randrange(32) for _ in range(32)]
            codes = span_aware(rng, 6) if anchors == "span-aware" else rng.sample(range(32), 6)
            extra = rng.sample([a for a in range(32) if a not in codes], k - 6)
            ex = [(a, M[a]) for a in codes]
            ok = all(route(ex, a) == M[a] for a in extra)
            for a in range(32):
                b = route(ex, a) if ok else None
                if b is not None and a in extra:
                    b = M[a]
                c["refused" if b is None else ("right" if b == M[a] else "wrong")] += 1
        sh = {x: c[x] / (32 * n) for x in ("right", "refused", "wrong")}
        if affine_b:
            exact = (a_rand if anchors == "random" else 1, 0)
            bad += c["wrong"] != 0 or abs(sh["right"] - float(exact[0])) > 0.01
        else:
            r, _, w = outside(5, k)
            exact = (r, w)
            bad += abs(sh["wrong"] - float(w)) > 6 * math.sqrt(float(w) * (1 - float(w)) / n) + 0.002
        rows.append(("affine" if affine_b else "arbitrary", anchors, k, sh, exact))
        print(f"  federation {rows[-1][0]:9} {anchors:10} k={k}  {sh}", flush=True)
    return rows, bad


def plane(rng, r):
    """An affine subspace of rank r: a point and r independent directions; returns its points."""
    base = rng.randrange(32)
    dirs = []
    while len(dirs) < r:
        v = rng.randrange(1, 32)
        if rank(dirs + [v]) == len(dirs) + 1:
            dirs.append(v)
    pts = set()
    for m in range(2 ** r):
        p = base
        for j in range(r):
            if m >> j & 1:
                p ^= dirs[j]
        pts.add(p)
    return sorted(pts)


def degeneracy(rng, route, n):
    rows, bad = [], 0
    for r in (2, 3):
        c_in, c_out, disagree, t_in, t_out = Counter(), Counter(), 0, 0, 0
        for _ in range(n):
            h = affine32(rng)
            pts = plane(rng, r)
            cases = pts + [rng.choice(pts) for _ in range(12 - len(pts))]
            rng.shuffle(cases)
            ex12 = [(f_, h[f_]) for f_ in cases]
            spans = lambda ex: rank([f_ ^ ex[0][0] for f_, _ in ex[1:]]) == r
            ex6 = ex12[:6]
            while not spans(ex6):
                rng.shuffle(ex12)
                ex6 = ex12[:6]
            alt = ex12[6:] if spans(ex12[6:]) else None
            for q in range(32):
                got = route(ex6, q)
                if q in pts:
                    t_in += 1
                    c_in["right" if got == h[q] else ("refused" if got is None else "wrong")] += 1
                else:
                    t_out += 1
                    c_out["refused" if got is None else ("right" if got == h[q] else "wrong")] += 1
                if alt is not None and route(alt, q) != got:
                    disagree += 1
        bad += c_in["wrong"] + c_in["refused"] + c_out["wrong"] + c_out["right"] + disagree
        rows.append((r, c_in, t_in, c_out, t_out, disagree))
    return rows, bad


def adversary(rng, route, n):
    rows, bad = [], 0
    for kind in ("a repeated case, one action bit flipped", "a dependent case, one bit off its combination"):
        refused = total = 0
        for _ in range(n):
            h = affine32(rng)
            F = span_aware(rng, 5)
            ex = [(f_, h[f_]) for f_ in F]
            bit = 1 << rng.randrange(5)
            if kind.startswith("a repeated"):
                f0, a0 = rng.choice(ex)
                ex.append((f0, a0 ^ bit))
            else:
                (fa, aa), (fb, ab), (fc, ac) = ex[0], ex[1], ex[2]
                ex.append((fa ^ fb ^ fc, aa ^ ab ^ ac ^ bit))
            for q in range(32):
                total += 1
                refused += route(ex, q) is None
        bad += total - refused
        rows.append((kind, refused, total))
    return rows, bad


def main() -> int:
    rng = random.Random(2026)
    route = law()
    fed, b1 = federation(rng, route, 20_000)
    deg, b2 = degeneracy(rng, route, 5_000)
    adv, b3 = adversary(rng, route, 20_000)
    out = ["# route5 live at 32 kinds", "",
           "Generated by `neo4d/router5_live.py`: the authored law (`neo4d/kernels/router5.c`) through the body's "
           "affine wrapper, against the exact values of `results/ROUTER5_MATH.md`.", "",
           "## Federation - two numberings merged from anchors alone (20,000 trials per row, all 32 codes)", "",
           "| B's numbering | anchors | k | right | refused | **wrong** | exact right | exact wrong |",
           "|---|---|---|---|---|---|---|---|"]
    for kind, anchors, k, sh, (er, ew) in fed:
        out.append(f"| {kind} | {anchors} | {k} | {sh['right']:.2%} | {sh['refused']:.2%} | **{sh['wrong']:.3%}** | "
                   f"{float(er):.2%} | {float(ew):.3%} |")
    out += ["", "## Degeneracy - 12 examples on an affine subspace of rank 2 or 3 (5,000 sets each)", "",
            "| rank | inside: right / refused / **wrong** | outside: refused / right / **wrong** | a different 6 disagrees |",
            "|---|---|---|---|"]
    for r, ci, ti, co, to, dis in deg:
        out.append(f"| {r} | {ci['right'] / ti:.2%} / {ci['refused'] / ti:.2%} / **{ci['wrong'] / ti:.2%}** | "
                   f"{co['refused'] / to:.2%} / {co['right'] / to:.2%} / **{co['wrong'] / to:.2%}** | {dis} |")
    out += ["", "## The adversary - a sixth example one bit wrong (20,000 sets each, all 32 queries)", "",
            "| contradiction | refused |", "|---|---|"]
    for kind, ref, tot in adv:
        out.append(f"| {kind} | **{ref:,} / {tot:,}** |")
    bad = b1 + b2 + b3
    out += ["", f"**Checks failed: {bad}.**"]
    (REPO / "results" / "ROUTER5_LIVE.md").write_text("\n".join(out) + "\n")
    print("\n".join(out))
    return int(bad != 0)


if __name__ == "__main__":
    sys.exit(main())
