"""Can a 4D structure generalise better than the router's ring? - measured, no law authored.

fluidfix's router (fluid-router, authored by a program-synthesis engine) infers a whole relabelling from ONE worked
example: route(F1, A1, Fq) == (Fq + A1 - F1) mod 16. Its hypothesis class is the 16 translations of a ring
of 16 - the symmetry group of the regular 16-gon's rotations, a 2D structure.

A 4D structure offers other classes of relabellings to generalise along. This file measures them - it
authors no law. For each class H it asks only what the worked examples LEAVE OPEN:

    version space after k worked examples = every relabelling in H that agrees with all k of them

That is a bound on what ANY law confined to H can know - an upper bound on a law, not a law. A query is
DETERMINED when every relabelling left agrees on it; WRONG when they agree and the truth is outside H
(confidently wrong - the failure fluidnet must never have); REFUSED otherwise.

    python3 generalize.py      -> results/GENERALIZE.md
"""
from __future__ import annotations

import itertools
import os
import random
import sys

import numpy as np

from neo4d import polytopes as P

# ------------------------------------------------------------------------- the classes, as permutations


def ring16():
    return np.array([[(x + t) % 16 for x in range(16)] for t in range(16)], dtype=np.int16)


def xor16():
    return np.array([[x ^ t for x in range(16)] for t in range(16)], dtype=np.int16)


def _pb(x, p):
    return sum(((x >> i) & 1) << p[i] for i in range(4))


def cube16():
    """Every symmetry of the 8-cell: permute the four axes, then reflect - x -> pi(x) XOR t. 4! * 16 = 384."""
    maps = {tuple(_pb(x, p) ^ t for x in range(16)) for p in itertools.permutations(range(4)) for t in range(16)}
    return np.array(sorted(maps), dtype=np.int16)


def affine16():
    """Every invertible affine map of GF(2)^4 - the 8-cell's vertex set AS A VECTOR SPACE: x -> Mx XOR t."""
    mats = []
    for cols in itertools.product(range(1, 16), repeat=4):
        img = [0] * 16
        for x in range(16):
            v = 0
            for i in range(4):
                if x >> i & 1:
                    v ^= cols[i]
            img[x] = v
        if len(set(img)) == 16:
            mats.append(img)
    maps = [[m[x] ^ t for x in range(16)] for m in mats for t in range(16)]
    return np.array(maps, dtype=np.int16)


def _qmul(a, b):
    a0, a1, a2, a3 = a
    b0, b1, b2, b3 = b
    return (a0 * b0 - a1 * b1 - a2 * b2 - a3 * b3, a0 * b1 + a1 * b0 + a2 * b3 - a3 * b2,
            a0 * b2 - a1 * b3 + a2 * b0 + a3 * b1, a0 * b3 + a1 * b2 - a2 * b1 + a3 * b0)


def _quaternion_group(units: np.ndarray):
    """A finite group of unit quaternions given as the vertices of a polytope; checks closure."""
    key = lambda q: tuple(np.round(q, 6) + 0.0)
    idx = {key(q): i for i, q in enumerate(units)}
    n = len(units)
    mul = np.zeros((n, n), dtype=np.int16)
    for i in range(n):
        for j in range(n):
            k = idx.get(key(_qmul(units[i], units[j])))
            assert k is not None, "not closed under multiplication"
            mul[i, j] = k
    return mul


def left(mul):
    return mul.copy()                                       # q -> a q, one map per a


def left_right(mul):
    """q -> a q b: the rotations of the polytope in 4D (SO(4) is unit quaternions on both sides)."""
    n = len(mul)
    maps = {tuple(mul[mul[a, q], b] for q in range(n)) for a in range(n) for b in range(n)}
    return np.array(sorted(maps), dtype=np.int16)


def hurwitz():
    rows = []
    for k in range(4):
        for s in (1, -1):
            r = [0.0] * 4
            r[k] = s
            rows.append(r)
    rows += [list(s) for s in itertools.product((0.5, -0.5), repeat=4)]
    return np.array(rows)


def is_automorphism(H: np.ndarray, adj) -> bool:
    edges = {(u, w) for u in range(len(adj)) for w in adj[u]}
    return all((int(h[u]), int(h[w])) in edges for h in H for u, w in edges)


# ------------------------------------------------------------------------------------------- measuring

def version_space(H, F, A):
    mask = np.ones(len(H), dtype=bool)
    for f, a in zip(F, A):
        mask &= H[:, f] == a
    return H[mask]


def generalisation(H_true, H_assumed, k, trials, rng):
    """Truth drawn from H_true; the worked examples are k cases and the truth's actions for them; every other
    case is a query. Returns (determined-and-right, refused, wrong) as fractions of queries."""
    n = H_true.shape[1]
    right = refused = wrong = total = 0
    for _ in range(trials):
        h = H_true[rng.randrange(len(H_true))]
        F = rng.sample(range(n), k)
        A = [int(h[f]) for f in F]
        V = version_space(H_assumed, F, A)
        for q in range(n):
            if q in F:
                continue
            total += 1
            if len(V) == 0:
                refused += 1
                continue
            col = V[:, q]
            if (col == col[0]).all():
                if col[0] == h[q]:
                    right += 1
                else:
                    wrong += 1
            else:
                refused += 1
    return right / total, refused / total, wrong / total


def needed(H, rng, trials=400, kmax=12):
    """Smallest k at which a random set of k worked examples pins the relabelling, in at least 99% of trials."""
    n = H.shape[1]
    for k in range(1, kmax + 1):
        ok = 0
        for _ in range(trials):
            h = H[rng.randrange(len(H))]
            F = rng.sample(range(n), k)
            ok += len(version_space(H, F, [int(h[f]) for f in F])) == 1
        if ok >= 0.99 * trials:
            return k, ok / trials
    return None, 0.0


def main() -> int:
    rng = random.Random(2026)
    tess = P.build("8-cell")
    classes16 = {
        "ring of 16 - the router's (16-gon rotations)": ring16(),
        "8-cell translations (XOR)": xor16(),
        "8-cell symmetries (axes permuted + reflected)": cube16(),
        "8-cell as the vector space GF(2)^4, affine maps": affine16(),
    }
    q8 = _quaternion_group(P.build("16-cell").coords)
    t2 = _quaternion_group(hurwitz())
    i2 = _quaternion_group(P.build("600-cell").coords)
    sx, tw, six = P.build("16-cell"), None, P.build("600-cell")
    hz_adj = P._link_nearest(hurwitz())
    quats = {
        "16-cell, q -> aq (Q8)": (left(q8), sx.adj),
        "16-cell, q -> aqb (rotations)": (left_right(q8), sx.adj),
        "24-cell, q -> aq (2T)": (left(t2), hz_adj),
        "24-cell, q -> aqb (rotations)": (left_right(t2), hz_adj),
        "600-cell, q -> aq (2I)": (left(i2), six.adj),
        "600-cell, q -> aqb (rotations)": (left_right(i2), six.adj),
    }
    out = ["# Can a 4D structure generalise better than the router? - measured", "",
           "Generated by `generalize.py`. No law is authored here: every number is the **version space** - the "
           "relabellings of a class that still agree with the worked examples - so it bounds what any law "
           "confined to that class can know. The router's own class is the first row.", "",
           "## 1. The classes on fluidfix's own domain - 16 kinds", "",
           "| class | relabellings it covers | 8-cell symmetry? | worked examples to pin one (99% of random sets) |",
           "|---|---|---|---|"]
    data = {"classes16": [], "cross": {}, "quats": []}
    for name, H in classes16.items():
        k, frac = needed(H, rng)
        auto = is_automorphism(H, tess.adj)
        data["classes16"].append((name, len(H), auto, k))
        out.append(f"| {name} | {len(H):,} | {'yes' if auto else 'no'} | {k} |")
        print(f"  {name:52} |H|={len(H):7}  pinned by k={k}", flush=True)
    out += ["", "## 2. Truth from one class, law confined to another - 16 kinds", "",
            "Each cell: right / refused / **wrong** over every query, with k worked examples (300 trials). "
            "Wrong means every relabelling left in the assumed class agreed, and the truth was outside it.", ""]
    names = list(classes16)
    short = ["ring", "XOR", "8-cell sym", "affine"]
    for k in (1, 2, 3, 5):
        out += [f"**k = {k}**", "", "| truth \\ assumed | " + " | ".join(short) + " |",
                "|---|" + "---|" * len(short)]
        for i, tn in enumerate(names):
            cells = []
            for an in names:
                r, f, w = generalisation(classes16[tn], classes16[an], k, 300, rng)
                data["cross"][f"{k}|{short[i]}|{short[names.index(an)]}"] = (r, f, w)
                cells.append(f"{100*r:.0f} / {100*f:.0f} / **{100*w:.0f}**")
            out.append(f"| {short[i]} | " + " | ".join(cells) + " |")
        out.append("")
        print(f"  cross-class k={k} done", flush=True)
    out += ["## 3. The quaternion polytopes - vocabularies of 8, 24 and 120 kinds", "",
            "Their vertices are unit quaternions forming a group, so a worked example can fix a 4D rotation, not "
            "only a shift. `q -> aq` fixes one side; `q -> aqb` is every rotation of the polytope.", "",
            "| structure | kinds | relabellings | rotations of the polytope? | worked examples to pin one |",
            "|---|---|---|---|---|"]
    for name, (H, adj) in quats.items():
        k, frac = needed(H, rng)
        data["quats"].append((name, H.shape[1], len(H), is_automorphism(H, adj), k))
        out.append(f"| {name} | {H.shape[1]} | {len(H):,} | {'yes' if is_automorphism(H, adj) else 'no'} | {k} |")
        print(f"  {name:40} |H|={len(H):6}  pinned by k={k}", flush=True)
    os.makedirs("results", exist_ok=True)
    with open("results/GENERALIZE.md", "w") as fh:
        fh.write("\n".join(out) + "\n")
    import json
    with open("results/generalize.json", "w") as fh:
        json.dump(data, fh, indent=1)
    os.makedirs("prompts", exist_ok=True)
    with open("prompts/ROUTER4D_LAW_PROMPT.md", "w") as fh:
        fh.write(render_prompt(data))
    print("\n" + "\n".join(out))
    print("\n  wrote results/GENERALIZE.md, results/generalize.json, prompts/ROUTER4D_LAW_PROMPT.md")
    return 0


def render_prompt(d: dict) -> str:
    """The superoptimizer task. It states the defect, the structures, the choices and the requirements - and
    NOT the law: no formula, no table. The class the author picks fixes the input/output pairs."""
    pct = lambda k, t, a, i: round(100 * d["cross"][f"{k}|{t}|{a}"][i])
    wrong1 = {t: pct(1, t, "ring", 2) for t in ("XOR", "8-cell sym", "affine")}
    c16 = "\n".join(f"| {n} | {h:,} | {'yes' if au else 'no'} | {k} |" for n, h, au, k in d["classes16"])
    q = "\n".join(f"| {n} | {kinds} | {h:,} | {k} |" for n, kinds, h, au, k in d["quats"])
    ks = (1, 2, 3, 5)
    ring_out = max(pct(k, t, "ring", 2) for k in ks for t in ("XOR", "8-cell sym", "affine"))
    cube_out = max(pct(k, t, "8-cell sym", 2) for k in ks for t in ("ring", "affine"))
    k5 = "\n".join(f"| {t} | {pct(5, t, 'ring', 0)} / {pct(5, t, 'ring', 1)} / **{pct(5, t, 'ring', 2)}** | "
                   f"{pct(5, t, '8-cell sym', 0)} / {pct(5, t, '8-cell sym', 1)} / **{pct(5, t, '8-cell sym', 2)}** |"
                   for t in ("ring", "XOR", "8-cell sym", "affine"))
    return f"""# Superoptimizer task - the ROUTER, on a 4D structure

**Not authored here.** This file states a defect, measures what 4D structures offer, and lists the requirements
a kernel must meet. It contains no formula and no truth table: the class you choose fixes the input/output pairs,
your engine authors the expression, and `judge_router4d.py` checks it against the class you declared.

---

## What exists

fluidfix's only decision-maker, vendored verbatim from fluid-router, authored by a program-synthesis engine
(verdict `minimal in D∩I`):

```c
15 & ((x >> 4) + ((x >> 8) - x))          x = F1 | A1 << 4 | Fq << 8
route(F1, A1, Fq) == (Fq + A1 - F1) mod 16
```

One worked example - case `F1` was handled by action `A1` - and it returns the action for any case `Fq`. It
generalises along one structure: the 16 translations of a ring of 16 (the rotations of a 16-gon, a 2D
structure). `fluidfix selfcheck` proves it on all 4096 words, identity 256/256, composition 4096/4096.

## The defect - measured (`generalize.py`, `results/GENERALIZE.md`)

The router always answers. When the true relabelling is a translation of the ring it is right every time. When
it is not, one worked example cannot tell it so, and it answers anyway:

| the true relabelling is | router's answers that are wrong, k = 1 |
|---|---|
| an 8-cell translation (XOR) | **{wrong1['XOR']}%** |
| an 8-cell symmetry (axes permuted, reflected) | **{wrong1['8-cell sym']}%** |
| an affine map of GF(2)^4 | **{wrong1['affine']}%** |

Confidently wrong - the one failure fluidnet's whole design refuses everywhere else.

## What a 4D structure supplies - measured

Every number is a **version space** - the relabellings of a class that still agree with the worked examples -
so it bounds what any law confined to that class can know; it is not a law.

On fluidfix's own domain, 16 kinds = the 8-cell's 16 vertices (bit i of a kind = coordinate i positive):

| class | relabellings it covers | a symmetry of the 8-cell? | worked examples to pin one (99% of random sets) |
|---|---|---|---|
{c16}

With k = 5 worked examples - right / refused / **wrong**, as % of queries:

| the truth is | a law confined to the ring | a law confined to the 8-cell's symmetries |
|---|---|---|
{k5}

Inside its own class no law is ever wrong - that is what a version space means. The measured difference is
OUTSIDE it: over every k measured (1, 2, 3, 5) and every truth outside the class, a law confined to the ring was
wrong on up to **{ring_out}%** of queries; one confined to the 8-cell's symmetries on at most **{cube_out}%** -
it refuses instead. And it covers 24 times the relabellings. The price: more worked examples than one.

For larger vocabularies - fluidnet on the shape carries 7 taught classes per dictionary - the quaternion
polytopes. Their vertices are unit quaternions forming a group, so a worked example can fix a 4D ROTATION:

| structure | kinds | relabellings | worked examples to pin one |
|---|---|---|---|
{q}

## The decision the law makes

Given k worked examples (case -> action) and a query case: return the query's action, or REFUSE when the
worked examples do not determine it within the structure.

## The measurement the body will supply - default packing

Extends fluid-router's `pack()`; four bits per kind on the 16-kind domain:

```
x = F1 | A1 << 4 | F2 << 8 | A2 << 12 | ... | Fq << 8k        k = 1: 12 bits (the router's own packing)
                                                               k = 2: 20 bits      k = 3: 28 bits
result & 31:  0..15 the action      16..31 REFUSE
```

## The choices that are yours

1. **The class** - XOR translations (16 relabellings, one example: the router's cost, the cube's geometry), the
   8-cell's symmetries (384), affine maps of GF(2)^4 (322,560), or a quaternion polytope for a larger vocabulary.
2. **k** - worked examples per decision.
3. **The packing and the refusal code**, if not the defaults above.
4. On the quaternion structures, **left or right**: `q -> aq` and `q -> qa` are different classes.

## The requirements any kernel must meet - checked by enumeration against your class

- **G0 Identity.** A query equal to a worked case returns that case's action, whenever the class can explain
  the worked examples - when it cannot, G3 decides (the router's 256/256; at k = 1 every class here explains
  every example).
- **G1 Sound.** If two relabellings in the class fit every worked example but disagree on the query: REFUSE.
- **G2 Complete.** If every relabelling in the class that fits the examples agrees on the query: that answer.
- **G3 Out of class, refuse.** If no relabelling in the class fits the worked examples: REFUSE - the case the
  router answers wrongly is exactly the case a sound law can detect.
- **G4 Renumber freely.** Relabel the cases by any element of the class and the actions by any element: the
  answer follows (a REFUSE stays a REFUSE) - fluid-router's renumbering property, on the 4D structure.
- **G5** Total on every word; branchless integer arithmetic; your operator budget.

## How it will be judged

```bash
.venv/bin/python judge_router4d.py --class cube --k 3 laws/router4d.c
```

Calibrated on the real thing: `judge_router4d.py --calibrate` judges fluidfix's `route_packed`, verbatim. As the
ring law at k = 1 it scores **0 violations on all 4096 words**; against every 4D class it fails - the defect above,
reproduced by the same judge your kernel will face.

G0-G4 by enumeration on every word (or a seeded sample where the word space or the class is too large to
enumerate, and the judge says so). Zero violations or it is not the law.

**What the superoptimizer does not decide:** which class real fault vocabularies actually follow. The measured
trade is above; the real one is measured on fluid-router's 33-bug benchmark corpus, renumbered by each class
in turn. If the corpus says the ring is enough, the router stands unchanged.
"""


if __name__ == "__main__":
    sys.exit(main())
