"""neo4d's inductive bias, measured: where it holds, where it breaks, how many examples it needs, what it refuses.

    1  SHARD        truths that break affinity by degree: an affine map, then a random permutation of the action codes
                    applied to a fraction eps of them (eps = 0 affine ... 1 a uniformly random relabelling). Five
                    span-aware examples; right / refused / wrong for neo4d, and for an MLP at the same five examples.
    2  SHOOTOUT     N = 1 .. 16 examples of a random affine relabelling (distinct cases, chosen span-aware for neo4d's
                    five): neo4d (route4d5, the first five examples) against a 3-layer MLP and a small Transformer
                    trained on all N, scored on the codes not in the examples.
    3  ACTIVE       random distinct cases until the differences span GF(2)^4 (passive) against registering only cases
                    that add a new direction (active, PICK's NEW_SPAN): the exact distribution, and a simulation.
    4  OOD          five examples whose cases all have the top bit 0 (an isolated subspace); a query with the top bit 1.

    python -m neo4d.inductive   -> results/INDUCTIVE.md
The neural baselines run in neo4d/nn_baseline.py under any Python with torch ($NEO4D_TORCH_PYTHON, default python3).
"""
from __future__ import annotations

import ctypes
import itertools
import json
import math
import os
import random
import subprocess
import sys
import tempfile
from collections import Counter
from fractions import Fraction as Fr
from pathlib import Path

from neo4d import PKG, REPO, build_kernel
from neo4d import edge_cases as E
from neo4d import judge_router4d as R4

H = R4.CLASSES["affine"]()
TORCH_PY = os.environ.get("NEO4D_TORCH_PYTHON", "python3")


def router():
    f = ctypes.CDLL(str(build_kernel("router4d5"))).route4d5
    f.argtypes, f.restype = [ctypes.c_int64], ctypes.c_int64

    def route(ex, q):
        ex = (list(ex) + [ex[0]] * 5)[:5]
        x = sum(fk << (8 * i) | a << (8 * i + 4) for i, (fk, a) in enumerate(ex)) | q << 40
        v = int(f(x)) & 31
        return v if v < 16 else None
    return route


def span_aware(rng, k=5):
    """k distinct cases, each one a new direction while the span is not yet full."""
    F = [rng.randrange(16)]
    while len(F) < k:
        f = rng.randrange(16)
        if f in F:
            continue
        r_now = E.rank([x ^ F[0] for x in F[1:]])
        if r_now == 4 or E.rank([x ^ F[0] for x in F[1:]] + [f ^ F[0]]) > r_now:
            F.append(f)
    return F


def run_nn(tasks, models="mlp,transformer"):
    d = Path(tempfile.mkdtemp(prefix="neo4d_nn_"))
    json.dump(tasks, open(d / "t.json", "w"))
    subprocess.run([TORCH_PY, str(PKG / "nn_baseline.py"), str(d / "t.json"), str(d / "p.json"), models], check=True)
    return json.load(open(d / "p.json"))


def shard(rng, route, per_eps=10_000, nn_trials=100):
    rows = []
    for eps in [i / 10 for i in range(11)]:
        c = Counter()
        tasks, truths = [], []
        for t in range(per_eps):
            h = list(map(int, H[rng.randrange(len(H))]))
            moved = rng.sample(range(16), round(eps * 16))
            perm = moved[:]
            rng.shuffle(perm)
            remap = dict(zip(moved, perm))
            g = [remap.get(a, a) for a in h]                      # a fraction eps of the action codes scrambled
            F = span_aware(rng)
            q = rng.randrange(16)
            got = route([(f, g[f]) for f in F], q)
            c["refused" if got is None else ("right" if got == g[q] else "wrong")] += 1
            if t < nn_trials:
                tasks.append({"examples": [(f, g[f]) for f in F]})
                truths.append((g, F))
        preds = run_nn(tasks, "mlp")
        unseen = [(p["mlp"][q], g[q]) for p, (g, F) in zip(preds, truths) for q in range(16) if q not in F]
        mlp_err = sum(a != b for a, b in unseen) / len(unseen)
        n = sum(c.values())
        rows.append((eps, c["right"] / n, c["refused"] / n, c["wrong"] / n, mlp_err))
        print(f"  shard eps={eps:.1f}  neo4d right {c['right']/n:.3f} refused {c['refused']/n:.3f} wrong "
              f"{c['wrong']/n:.3f}   MLP wrong on unseen {mlp_err:.3f}", flush=True)
    return rows


def shootout(rng, route, trials=60):
    rows = []
    for N in range(1, 16):
        tasks, meta = [], []
        neo = Counter()
        for _ in range(trials):
            h = list(map(int, H[rng.randrange(len(H))]))
            F = span_aware(rng, min(N, 5)) if N <= 5 else span_aware(rng, 5) + []
            while len(F) < N:
                f = rng.randrange(16)
                if f not in F:
                    F.append(f)
            ex = [(f, h[f]) for f in F]
            for q in range(16):
                if q in F:
                    continue
                got = route(ex[:5], q)
                neo["refused" if got is None else ("right" if got == h[q] else "wrong")] += 1
            tasks.append({"examples": ex})
            meta.append((h, F))
        preds = run_nn(tasks)
        acc = {}
        for model in ("mlp", "transformer"):
            pairs = [(p[model][q], h[q]) for p, (h, F) in zip(preds, meta) for q in range(16) if q not in F]
            acc[model] = sum(a == b for a, b in pairs) / len(pairs)
        n = sum(neo.values())
        rows.append((N, neo["right"] / n, neo["refused"] / n, neo["wrong"] / n, acc["mlp"], acc["transformer"]))
        print(f"  shootout N={N:2}  neo4d right {neo['right']/n:.3f} refused {neo['refused']/n:.3f} wrong "
              f"{neo['wrong']/n:.3f}   MLP right {acc['mlp']:.3f}   Transformer right {acc['transformer']:.3f}", flush=True)
    return rows


def active(rng, sims=200_000):
    def spans(S):
        return E.rank([s ^ S[0] for s in S[1:]]) == 4
    P = {k: Fr(sum(spans(S) for S in itertools.combinations(range(16), k)), math.comb(16, k)) for k in range(5, 10)}
    dist = {k: P[k] - (P[k - 1] if k > 5 else 0) for k in range(5, 10)}
    expected = sum(k * p for k, p in dist.items())
    sim = Counter()
    for _ in range(sims):
        order = rng.sample(range(16), 16)
        for k in range(5, 17):
            if spans(order[:k]):
                sim[k] += 1
                break
    return dist, expected, sim, sims


def ood(rng, route, n=50_000):
    c = Counter()
    inside = Counter()
    for _ in range(n):
        h = list(map(int, H[rng.randrange(len(H))]))
        F = rng.sample(range(8), 5)                              # every case has the top bit 0
        ex = [(f, h[f]) for f in F]
        q = rng.randrange(8, 16)                                 # the query has it set
        got = route(ex, q)
        c["refused" if got is None else ("right" if got == h[q] else "wrong")] += 1
        q2 = rng.randrange(8)                                    # a query inside the subspace, for contrast
        got2 = route(ex, q2)
        inside["refused" if got2 is None else ("right" if got2 == h[q2] else "wrong")] += 1
    return c, inside, n


def main() -> int:
    rng = random.Random(2026)
    route = router()
    sh = shard(rng, route)
    so = shootout(rng, route)
    dist, expected, sim, sims = active(rng)
    oc, oi, on = ood(rng, route)
    pct = lambda x: f"{100 * x:.1f}%"
    out = ["# neo4d's inductive bias - measured", "", "Generated by `neo4d/inductive.py`.", "",
           "## 1. The shard test - breaking affinity by degree", "",
           "Truth: an affine map with a fraction eps of its action codes randomly re-scrambled (eps = 0 affine, 1 a "
           "uniformly random relabelling). Five span-aware examples, 10,000 queries per eps; the MLP trained on the "
           "same five examples (100 tasks per eps).", "",
           "| eps | neo4d right | neo4d refused | **neo4d wrong** | MLP wrong (unseen codes; it cannot refuse) |",
           "|---|---|---|---|---|"]
    for eps, r, f, w, m in sh:
        out.append(f"| {eps:.1f} | {pct(r)} | {pct(f)} | **{pct(w)}** | {pct(m)} |")
    out += ["", f"At eps = 1 the exact values are right 3/13 = 23.1%, refused 5/13 = 38.5%, wrong 5/13 = 38.5% "
            "(`results/EXACT_MATH.md`). At eps = 0 neo4d is exact.", "",
            "## 2. Sample-efficiency shootout - a random affine relabelling from N examples", "",
            "Scored on the codes not among the examples; 60 tasks per N. neo4d reads the first five examples "
            "(chosen span-aware); the networks train on all N until they fit them, predict the 4 output bits, and always "
            "answer.", "",
            "| N | neo4d right | neo4d refused | **neo4d wrong** | MLP right | Transformer right |",
            "|---|---|---|---|---|---|"]
    for N, r, f, w, m, t in so:
        out.append(f"| {N} | {pct(r)} | {pct(f)} | **{pct(w)}** | {pct(m)} | {pct(t)} |")
    out += ["", "Below N = 5 neo4d answers exactly what its examples determine and refuses the rest; from N = 5 "
            "(span-aware) it is exact. The networks have no affine bias, so a handful of examples cannot tell them "
            "which relabelling it is - they guess. This measures the value of the right structure, not general "
            "intelligence.", "",
            "## 3. Active vs passive - examples until the relabelling is pinned", "",
            "| examples | passive (random distinct cases): exact | passive: simulated, 200,000 | active (new direction only) |",
            "|---|---|---|---|"]
    for k in range(5, 10):
        out.append(f"| {k} | {dist[k]} = {float(dist[k]):.4f} | {sim[k] / sims:.4f} | {'1' if k == 5 else '0'} |")
    out += ["", f"Expected examples, passive: **{expected}** = {float(expected):.4f} (simulated "
            f"{sum(k * v for k, v in sim.items()) / sims:.4f}); active: **5**, always. Five is the minimum any learner "
            "can achieve here - pinning M needs four independent differences, so five points. In test runs (4 per "
            f"example): active 20, passive {4 * float(expected):.2f} on average. Span alone is a modest saving in 4D; "
            "PICK's larger measured win (79 and 39 test runs down to 20) came from skipping trials the suite cannot "
            "catch or several edits would repair.", "",
            "## 4. Out-of-distribution queries - an isolated subspace", "",
            "Five examples whose cases all have the top bit 0; the query has it set - its difference lies outside "
            f"every combination of the example differences. {on:,} trials.", "",
            "| query | right | refused | wrong |", "|---|---|---|---|",
            f"| top bit 1 (outside the subspace) | {pct(oc['right'] / on)} | **{pct(oc['refused'] / on)}** | **{pct(oc['wrong'] / on)}** |",
            f"| top bit 0 (inside, for contrast) | {pct(oi['right'] / on)} | {pct(oi['refused'] / on)} | {pct(oi['wrong'] / on)} |"]
    bad = int(oc["refused"] != on) + int(sh[0][3] != 0) + sum(1 for row in so if row[3] != 0)
    out += ["", f"**Checks failed: {bad}** (OOD refused every time; zero errors at eps = 0; zero errors in the shootout)."]
    (REPO / "results" / "INDUCTIVE.md").write_text("\n".join(out) + "\n")
    print("\n".join(out))
    return int(bad != 0)


if __name__ == "__main__":
    sys.exit(main())
