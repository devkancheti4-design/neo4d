"""Degenerate example sets, malicious contradictions, and validation points - route4d5 at its boundaries.

    5  DEGENERACY    10 examples whose case differences span only rank 2 (a 4-point affine plane: the test suite says
                     the same thing several times). The router takes any 5 of them: in-span queries must be answered
                     exactly, out-of-span queries refused - and every 5-subset must give the same answers.
    6  ADVERSARY     4 examples from an affine truth, plus a 5th that repeats one of their cases with ONE bit of its
                     action flipped (dF = 0, dA != 0); and a subtler one - a 5th case that is the XOR-combination of
                     the others, its action one bit off the combination. Brute force must find no map; the router
                     must refuse every query.
    7  VALIDATION    a truth outside the structure (a random permutation), k = 5 span-aware examples plus v extra
                     validation examples: the router fits the first five, and the body refuses unless every extra
                     example agrees with that fit (the same router, no new law). Exact and simulated, k = 5 .. 8.

    python -m neo4d.degeneracy   -> results/DEGENERACY.md
"""
from __future__ import annotations

import itertools
import math
import random
import sys
from collections import Counter
from fractions import Fraction as Fr

from neo4d import REPO
from neo4d import edge_cases as E
from neo4d.inductive import router, span_aware

H = E.H


def degeneracy(rng, route, n=5_000):
    c_in, c_out, subset_disagree, total_in, total_out = Counter(), Counter(), 0, 0, 0
    for _ in range(n):
        h = list(map(int, H[rng.randrange(len(H))]))
        F1 = rng.randrange(16)
        b1 = rng.randrange(1, 16)
        b2 = rng.choice([v for v in range(1, 16) if v != b1])
        plane = [F1, F1 ^ b1, F1 ^ b2, F1 ^ b1 ^ b2]
        cases = plane + [rng.choice(plane) for _ in range(6)]             # 10 examples, rank 2, redundant
        rng.shuffle(cases)
        ex10 = [(f, h[f]) for f in cases]
        ex5 = ex10[:5]
        while E.rank([f ^ ex5[0][0] for f, _ in ex5[1:]]) < 2:            # any 5 that still span the plane
            rng.shuffle(ex10)
            ex5 = ex10[:5]
        alt = ex10[5:] if E.rank([f ^ ex10[5][0] for f, _ in ex10[6:]]) == 2 else None
        for q in range(16):
            got = route(ex5, q)
            if q in plane:
                total_in += 1
                c_in["right" if got == h[q] else ("refused" if got is None else "wrong")] += 1
            else:
                total_out += 1
                c_out["refused" if got is None else ("right" if got == h[q] else "wrong")] += 1
            if alt is not None and route(alt, q) != got:
                subset_disagree += 1
    return c_in, total_in, c_out, total_out, subset_disagree


def adversary(rng, route, n=20_000):
    rows = []
    for kind in ("repeat a case, flip one action bit (dF = 0, dA != 0)",
                 "a dependent case, its action one bit off the combination"):
        no_map = refused = total = 0
        for _ in range(n):
            h = list(map(int, H[rng.randrange(len(H))]))
            F = span_aware(rng, 4)                                        # 4 independent-ish, perfectly affine
            ex = [(f, h[f]) for f in F]
            bit = 1 << rng.randrange(4)
            if kind.startswith("repeat"):
                f0, a0 = rng.choice(ex)
                ex.append((f0, a0 ^ bit))
            else:
                (fa, aa), (fb, ab), (fc, ac) = ex[0], ex[1], ex[2]
                ex.append((fa ^ fb ^ fc, (aa ^ ab ^ ac) ^ bit))           # the affine combination, one bit off
            no_map += E.survivors(ex) == 0
            for q in range(16):
                total += 1
                refused += route(ex, q) is None
        rows.append((kind, no_map, n, refused, total))
    return rows


def exact_validation(k):
    """Random-permutation truth, 5 affinely independent cases + (k-5) more, query uniform: P(right, refused, wrong)."""
    accept = Fr(8, 13)
    for j in range(k - 5):
        accept *= Fr(1, 11 - j)
    rest = 16 - k
    right = accept * (Fr(k, 16) + Fr(rest, 16) * Fr(1, rest))
    wrong = accept * Fr(rest, 16) * Fr(rest - 1, rest)
    return right, 1 - accept, wrong


def validation(rng, route, n=200_000):
    rows = []
    for k in (5, 6, 7, 8):
        c = Counter()
        for _ in range(n):
            p = list(range(16))
            rng.shuffle(p)
            F = span_aware(rng, 5)
            extra = rng.sample([f for f in range(16) if f not in F], k - 5)
            ex = [(f, p[f]) for f in F]
            q = rng.randrange(16)
            ok = all(route(ex, f) == p[f] for f in extra)                  # the extra examples validate the fit
            got = route(ex, q) if ok else None
            if got is not None and q in extra:
                got = p[q]                                                 # an example case is known exactly
            c["refused" if got is None else ("right" if got == p[q] else "wrong")] += 1
        rows.append((k, exact_validation(k), {x: c[x] / n for x in ("right", "refused", "wrong")}))
        print(f"  validation k={k}  wrong {c['wrong'] / n:.5f} (exact {float(exact_validation(k)[2]):.5f})", flush=True)
    return rows


def main() -> int:
    rng = random.Random(2026)
    route = router()
    c_in, t_in, c_out, t_out, sub = degeneracy(rng, route)
    adv = adversary(rng, route)
    val = validation(rng, route)
    out = ["# route4d5 at its boundaries - degeneracy, adversaries, validation", "",
           "Generated by `neo4d/degeneracy.py`.", "",
           "## 5. Degenerate examples - 10 examples spanning only rank 2", "",
           "5,000 sets of 10 examples whose cases lie on a 4-point affine plane (redundant: the same facts repeated); "
           "the router takes 5 that still span the plane. All 16 codes queried.", "",
           "| query | right | refused | **wrong** |", "|---|---|---|---|",
           f"| inside the plane ({t_in:,}) | {c_in['right'] / t_in:.2%} | {c_in['refused'] / t_in:.2%} | **{c_in['wrong'] / t_in:.2%}** |",
           f"| outside it ({t_out:,}) | {c_out['right'] / t_out:.2%} | {c_out['refused'] / t_out:.2%} | **{c_out['wrong'] / t_out:.2%}** |",
           "", f"A different 5 of the same 10, wherever they also span the plane: answers differing **{sub}**.", "",
           "## 6. The perfect adversary - contradictions one bit wide", "",
           "| contradiction | brute force: no affine map fits | router refused |", "|---|---|---|"]
    for kind, nm, n, ref, tot in adv:
        out.append(f"| {kind} | {nm:,} / {n:,} | **{ref:,} / {tot:,}** |")
    out += ["", "## 7. Validation points against a truth outside the structure", "",
            "A random permutation of the 16 codes; 5 span-aware examples fit, k - 5 more examples must agree with the "
            "fit or the body refuses (the same router, no new law). Query uniform; 200,000 trials per k.", "",
            "| k examples | exact right | exact refused | **exact wrong** | simulated wrong |", "|---|---|---|---|---|"]
    for k, (r, f, w), sim in val:
        out.append(f"| {k} | {r} = {float(r):.3%} | {f} = {float(f):.3%} | **{w} = {float(w):.4%}** | {sim['wrong']:.4%} |")
    out += ["", "Each validation point leaves an accidental affine fit standing only if the permutation agrees with it "
            "there - about 1 chance in 11, then 10, then 9 - so the error falls by roughly 10x per extra test-verified "
            "example (4 suite runs each). It reaches exactly 0 only when every one of the 16 codes is an example; "
            "for a truth inside the structure the extra points always agree, so nothing right is lost."]
    bad = c_in["wrong"] + c_in["refused"] + c_out["wrong"] + c_out["right"] + sub \
        + sum(n - nm for _, nm, n, _, _ in adv) + sum(tot - ref for _, _, _, ref, tot in adv)
    for k, (r, f, w), sim in val:
        sd = math.sqrt(float(w) * (1 - float(w)) / 200_000) + 1e-9
        bad += abs(sim["wrong"] - float(w)) > 5 * sd
    out += ["", f"**Checks failed: {bad}.**"]
    (REPO / "results" / "DEGENERACY.md").write_text("\n".join(out) + "\n")
    print("\n".join(out))
    return int(bad != 0)


if __name__ == "__main__":
    sys.exit(main())
