# Superoptimizer task - the ROUTER, on a 4D structure

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
| an 8-cell translation (XOR) | **62%** |
| an 8-cell symmetry (axes permuted, reflected) | **88%** |
| an affine map of GF(2)^4 | **92%** |

Confidently wrong - the one failure fluidnet's whole design refuses everywhere else.

## What a 4D structure supplies - measured

Every number is a **version space** - the relabellings of a class that still agree with the worked examples -
so it bounds what any law confined to that class can know; it is not a law.

On fluidfix's own domain, 16 kinds = the 8-cell's 16 vertices (bit i of a kind = coordinate i positive):

| class | relabellings it covers | a symmetry of the 8-cell? | worked examples to pin one (99% of random sets) |
|---|---|---|---|
| ring of 16 - the router's (16-gon rotations) | 16 | no | 1 |
| 8-cell translations (XOR) | 16 | yes | 1 |
| 8-cell symmetries (axes permuted + reflected) | 384 | yes | 7 |
| 8-cell as the vector space GF(2)^4, affine maps | 322,560 | no | 8 |

With k = 5 worked examples - right / refused / **wrong**, as % of queries:

| the truth is | a law confined to the ring | a law confined to the 8-cell's symmetries |
|---|---|---|
| ring | 100 / 0 / **0** | 12 / 87 / **1** |
| XOR | 15 / 83 / **2** | 90 / 10 / **0** |
| 8-cell sym | 1 / 99 / **0** | 85 / 15 / **0** |
| affine | 0 / 100 / **0** | 0 / 100 / **0** |

Inside its own class no law is ever wrong - that is what a version space means. The measured difference is
OUTSIDE it: over every k measured (1, 2, 3, 5) and every truth outside the class, a law confined to the ring was
wrong on up to **92%** of queries; one confined to the 8-cell's symmetries on at most **6%** -
it refuses instead. And it covers 24 times the relabellings. The price: more worked examples than one.

For larger vocabularies - fluidnet on the shape carries 7 taught classes per dictionary - the quaternion
polytopes. Their vertices are unit quaternions forming a group, so a worked example can fix a 4D ROTATION:

| structure | kinds | relabellings | worked examples to pin one |
|---|---|---|---|
| 16-cell, q -> aq (Q8) | 8 | 8 | 1 |
| 16-cell, q -> aqb (rotations) | 8 | 32 | 5 |
| 24-cell, q -> aq (2T) | 24 | 24 | 1 |
| 24-cell, q -> aqb (rotations) | 24 | 288 | 5 |
| 600-cell, q -> aq (2I) | 120 | 120 | 1 |
| 600-cell, q -> aqb (rotations) | 120 | 7,200 | 4 |

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
