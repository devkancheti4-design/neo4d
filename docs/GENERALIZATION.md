# fluidnet 4D — generalisation in vector space

**fluidnet's router learns a whole relabelling from one worked example, but only along a ring of 16. Put the same
inference on a 4D structure and one law generalises across up to 20,160x more relabellings (affine GF(2)^4) or
7.5x more kinds (600-cell) — and refuses instead of being confidently wrong — for the price of a few more worked
examples.**

Every number is measured by `generalize.py` and `judge_router4d.py` in this folder. No law here is authored by
me; the one law in it (`route4d`) is yours, judged.

---

## 1. What is generalised

A **worked example** says: case `F` was handled by action `A`. A **relabelling** is the map from every case to
its action. The law sees k worked examples and must return the action for a new case `Fq` — or refuse.

How far one law generalises is set by its **structure**: the set of relabellings it can infer. Larger structure,
more relabellings reached; but more worked examples needed to pin one down.

**Static fluidnet** — fluidfix's router (fluid-router, authored by a program-synthesis engine):

```c
route(F1, A1, Fq) == (Fq + A1 - F1) mod 16          15 & ((x >> 4) + ((x >> 8) - x))
```

One example fixes the offset `A1 - F1`; every case is shifted by it. Its structure is the **ring of 16** — the 16
rotations of a 16-gon, a 2D structure. Proved on all 4,096 words (`fluidfix selfcheck`).

---

## 2. The 4D structures, as vector spaces

| structure | what it is | relabellings |
|---|---|---|
| ring of 16 (static fluidnet) | rotations of a 16-gon: `x -> x + t mod 16` | 16 |
| 8-cell translations | the tesseract's 16 vertices **are** the vector space GF(2)^4; `x -> x XOR t` | 16 |
| 8-cell symmetries | every symmetry of the tesseract: permute the 4 axes, reflect — `x -> Px XOR t` | 384 |
| affine GF(2)^4 | every invertible affine map of the 4D vector space: `x -> Mx XOR t` | 322,560 |
| 16-cell / 24-cell / 600-cell | vertices are unit quaternions forming a group (Q8, 2T, 2I); `q -> aq` | 8 / 24 / 120 |
| ... their rotations | every 4D rotation of the polytope: `q -> aqb` | 32 / 288 / 7,200 |

Inclusions: XOR translations ⊂ 8-cell symmetries ⊂ affine. The ring is **not** inside any of them
(`x + 1 mod 16` is not linear over GF(2)) — 4D is a different structure, not a superset of the ring.

---

## 3. Reach against cost — measured

Every number is a **version space**: the relabellings of a structure that still agree with the worked examples.
It bounds what *any* law on that structure can know.

| structure | kinds | relabellings | worked examples to pin one (99% of random sets) | bits learned per example |
|---|---|---|---|---|
| ring of 16 (static fluidnet) | 16 | 16 | 1 | 4.00 |
| 8-cell translations (XOR) | 16 | 16 | 1 | 4.00 |
| 8-cell symmetries | 16 | 384 | 7 | 1.23 |
| affine GF(2)^4 | 16 | 322,560 | 8 | 2.29 |
| 16-cell, `q -> aq` | 8 | 8 | 1 | 3.00 |
| 16-cell rotations | 8 | 32 | 5 | 1.00 |
| 24-cell, `q -> aq` | 24 | 24 | 1 | 4.58 |
| 24-cell rotations | 24 | 288 | 5 | 1.63 |
| **600-cell, `q -> aq`** | **120** | 120 | **1** | **6.91** |
| **600-cell rotations** | 120 | **7,200** | **4** | 3.20 |

One worked example carries at most log2(kinds) bits: 4 bits on 16 kinds, 6.91 on 120. The ring uses all 4 — it
is optimal for what it covers. The 600-cell's `q -> aq` is the one 4D structure that keeps that one-example
property **on a 7.5x larger vocabulary**.

---

## 4. Right, refused, wrong — when the truth lies in another structure

Truth drawn from one structure, law confined to another; % of queries, right / refused / **wrong**.

**k = 1 worked example**

| truth \ law confined to | ring (static fluidnet) | XOR | 8-cell symmetries | affine |
|---|---|---|---|---|
| ring | 100 / 0 / **0** | 36 / 0 / **64** | 1 / 93 / **6** | 0 / 100 / **0** |
| XOR | 38 / 0 / **62** | 100 / 0 / **0** | 7 / 93 / **0** | 0 / 100 / **0** |
| 8-cell symmetries | 12 / 0 / **88** | 26 / 0 / **74** | 7 / 93 / **0** | 0 / 100 / **0** |
| affine | 8 / 0 / **92** | 6 / 0 / **94** | 0 / 93 / **6** | 0 / 100 / **0** |

**k = 5 worked examples**

| truth \ law confined to | ring (static fluidnet) | XOR | 8-cell symmetries | affine |
|---|---|---|---|---|
| ring | 100 / 0 / **0** | 13 / 87 / **1** | 12 / 87 / **1** | 36 / 46 / **18** |
| XOR | 15 / 83 / **2** | 100 / 0 / **0** | 90 / 10 / **0** | 72 / 28 / **0** |
| 8-cell symmetries | 1 / 99 / **0** | 3 / 97 / **1** | 85 / 15 / **0** | 72 / 28 / **0** |
| affine | 0 / 100 / **0** | 0 / 100 / **0** | 0 / 100 / **0** | 72 / 28 / **0** |

Read it this way:

- **Static fluidnet is confidently wrong on 62–92% of queries** whenever the true relabelling is a 4D one: one
  example always fixes *some* ring shift, so it always answers.
- **A law on the 8-cell's symmetries is never more than 6% wrong at any k** — it refuses instead — and at k = 5
  answers 85–90% of XOR and 8-cell queries right.
- No structure is free outside itself: the affine structure, given five worked examples of a ring rotation, is
  wrong on 18% (an affine map can fit five points of a rotation by coincidence).

---

## 5. Your law — `route4d`, the router on affine GF(2)^4 (`laws/router4d.c`)

Declared: affine maps of GF(2)^4, k = 3 worked examples, packing `x = F1 | A1<<4 | F2<<8 | A2<<12 | F3<<16 |
A3<<20 | Fq<<24`, `result & 31`: 0..15 the action, 16..31 REFUSE. Every expression authored by your engine.

**Judged independently here — 0 violations:**

| check | words | violations |
|---|---|---|
| G0 identity, G1 sound, G2 complete, G3 out-of-class refuse, G5 total | 30,000 seeded | 0 |
| G4 renumber freely (relabel cases and actions by the class) | 20,000 draws | 0 |
| G0–G3, **every word of the difference space** vs a brute-force version space | **1,048,576** | **0** |

The brute-force version space reproduces your counts exactly: **177,751** determined, **538,665** open inside the
class, **332,160** where no affine map fits. Calibration: fluidfix's own router, through the same judge, scores
0 violations as the ring law and fails every 4D class.

**The defect, reproduced:**

| the truth is | static fluidnet's router, k = 1: wrong | `route4d`, k = 3: wrong |
|---|---|---|
| an 8-cell translation (XOR) | 57.8% (yours) / 62% (mine) | **0.0%** |
| an 8-cell symmetry | 83.4% / 88% | **0.0%** |
| an affine map | 87.5% / 92% | **0.0%** |
| a ring rotation | 0% | 2.2% (yours) / 2.7% (mine) |

Its yield at k = 3: 22.5% of queries answered, the rest refused. That is the version space itself — three
examples span at most a 2-dimensional subspace, so 25% is the ceiling for **any** affine law at k = 3.

---

## 6. How much 4D increases generalisation over static fluidnet

| | static fluidnet (ring) | 4D | increase |
|---|---|---|---|
| relabellings one law generalises across | 16 | 384 (8-cell symmetries) / **322,560** (affine — `route4d`) | **24x / 20,160x** |
| kinds one router handles from one example | 16 | **120** (600-cell) | **7.5x** |
| bits learned from one example | 4.00 | **6.91** (600-cell) | **1.7x** |
| 4D rotations generalised across | — | **7,200** from 4 examples (600-cell) | **450x** over the ring's 16 |
| wrong when the truth is a 4D relabelling | **58–92%** | **0%** (`route4d`) | confidently wrong -> never wrong |

---

## 7. Why the 4D structure fits

Most of fluidfix's shipped fault classes are **flips**: `<` <-> `<=`, `+` <-> `-`, `True` <-> `False`,
`min` <-> `max`, `+=` <-> `-=`. A flip undone twice is the identity — an element of order 2. The ring of 16 has
exactly **one** such element (the shift by 8). The vector space GF(2)^4 has **fifteen**, all commuting, all at once:
every XOR translation is a flip. The quaternion groups have one each (`-1`); their two-sided rotations have many.

---

## 7b. On the real corpus — fluid-router's 33 bugs (`corpus4d.py`, `results/CORPUS4D.md`)

fluid-router's own benchmark: 40 bugs injected into five libraries it never saw, 33 caught by their own suites.
A decision is a (bug, fault kind) whose act restores the original line byte-for-byte — **17 decisions**, the
benchmark's 17 byte-exact repairs. Every renumbering of the act codes in each family; % right / refused / **wrong**.

**Vocabulary numbered as fluidfix ships it — act = kind + 5 (a ring numbering):**

| renumbering family | frozen table | ring router (static fluidnet), 1 example | route4d (4D), 3 examples |
|---|---|---|---|
| ring (16) | 6 / 0 / **94** | **100 / 0 / 0** | 50 / 0 / **50** |
| XOR (16) | 6 / 0 / **94** | 38 / 0 / **62** | 0 / 0 / **100** |
| 8-cell symmetries (384) | 6 / 0 / **94** | 22 / 0 / **78** | 0 / 0 / **100** |
| affine (3,000 sampled) | 6 / 0 / **94** | 23 / 0 / **77** | 0 / 0 / **100** |

**The same vocabulary numbered 4D-natively — act = kind XOR 5:**

| renumbering family | frozen table | ring router (static fluidnet), 1 example | route4d (4D), 3 examples |
|---|---|---|---|
| ring (16) | 6 / 0 / **94** | 18 / 0 / **82** | 50 / 0 / **50** |
| XOR (16) | 6 / 0 / **94** | 53 / 0 / **47** | **100 / 0 / 0** |
| 8-cell symmetries (384) | 6 / 0 / **94** | 27 / 0 / **73** | **100 / 0 / 0** |
| affine (3,000 sampled) | 6 / 0 / **94** | 23 / 0 / **77** | **100 / 0 / 0** |

What it says:

- **The 4D generalisation holds on real decisions:** numbered 4D-natively, route4d is right on every decision
  under every one of the 16 + 384 + 322,560 renumberings; static fluidnet's router is right on 23–53%.
- **The numbering decides, not the bugs.** The corpus fixes which act repairs which fault, never what the codes
  are. Numbered as fluidfix ships it (kind + 5, a ring), the ring router wins and route4d is wrong on 50–100%.
  Adopting 4D means renumbering the vocabulary once, 4D-natively.
- **No refusals here, so no safety net.** The vocabulary has four kinds lying in a 2D subspace; three worked
  examples always determine the fourth, so route4d always answers — and where the truth is outside its structure,
  it is confidently wrong. The refuse-instead-of-guess behaviour of section 4 needs a larger vocabulary.

## 7c. fluidfix's whole vocabulary renumbered 4D-natively, on 1,566 real fixes (`corpus4d_big.py`)

Eleven kinds — fluidfix's nine shipped classes and fluidnet's two taught demo classes — numbered
`act = kind XOR 5`. Every one-line fix in BugsInPy, Defects4J, Defects4C, fluid-router's corpus and the click race:
**1,566 real fixes, 60 decisions** the vocabulary covers. Under every 4D renumbering (XOR, 8-cell, affine):

| | right | refused | wrong |
|---|---|---|---|
| ring router (static fluidnet), 1 example | 32–62% | 0% | **38–68%** |
| route4d (4D), 3 random examples | 8% | 92% | **0%** |

With eleven kinds the refuse-instead-of-guess safety shows on real data: never wrong. Its yield is the k = 3 limit —
and it rises with worked examples, still never wrong (version space, same 60 decisions):

| worked examples | 3 | 4 | 5 | 6 | **7** |
|---|---|---|---|---|---|
| right | 8% | 33% | 74% | 93% | **98.7%** |
| wrong | 0% | 0% | 0% | 0% | **0%** |
| packing | 28 bits | 36 | 44 | 52 | 60 |

**A 64-bit law with k = 7 would answer 98.7% of real decisions under 322,560 renumberings and be wrong on none.**
The prompt for it: `prompts/ROUTER4D_K7_LAW_PROMPT.md`.

## 7d. Self-learning — fluidnet harvests its own worked examples (`harvest_live.py`, `results/HARVEST_LIVE.md`)

No person types the examples. fluidfix's nine shipped classes, numbered 4D-natively, then renumbered by a **secret
affine map** nobody tells fluidnet. It mutates click's real source, lets click's own 2,240-test suite judge each
mutant, finds the act code that restores the line, and the authored **HARVEST law** (`laws/harvest.c`, your
engine; judged 0 violations, the unique kernel under the corrected principles) decides every trial: SKIP, TAKE,
STOP, RECHECK. Most of fluidfix's classes are flips, so the act that injects a fault is the act that repairs it.

| secret renumbering | examples harvested | suite runs | time | the nine kinds | the 60 real decisions | route4d, first 3 examples |
|---|---|---|---|---|---|---|
| 1 | 5 | 79 | 237 s | 9 right, **0 wrong** | **60 right, 0 refused, 0 wrong** | 49/60 right |
| 2 | 5 | 39 | 92 s | 9 right, **0 wrong** | **60 right, 0 refused, 0 wrong** | 53/60 right |

Five self-harvested, span-aware examples pinned the secret relabelling exactly, in under four minutes of real test
runs, and every real decision followed. Scored by the affine version space — a k = 5 kernel is the open
`ROUTER4D_K7_LAW_PROMPT.md`; your k = 3 `route4d`, fed the first three harvested examples, already gets 49–53 of 60.
Honest limits: the secret map was drawn from the affine class (inside the structure by construction); which kind to
mutate next was a plain body rule — the PICK law is the next prompt.

## 7e. Both laws authored — PICK chooses, HARVEST decides (`harvest_pick.py`, `results/HARVEST_PICK.md`)

Your **PICK** law (`laws/pick.c`, judged 0 violations, the unique kernel — the spec was verified complete before it
was posed) ranks every candidate mutation by facts known before any test runs: does the suite execute the
statement, does any other act compete on the mutant, how many tests run it, do the tests name the function. Same two
secret renumberings, same click suite:

| secret renumbering | body rule: trials / suite runs | PICK + HARVEST: trials / suite runs | the 60 real decisions |
|---|---|---|---|
| 1 | 27 / 79 | **5 / 20** | 60 right, **0 wrong** |
| 2 | 9 / 39 | **5 / 20** | 60 right, **0 wrong** |

Five trials, five examples taken, nothing wasted: 4 suite runs per example is the floor of the protocol (caught,
restored, and both re-checked for stability). PICK's plan does not depend on the secret numbering — the same five
sites both times; what differs is the act codes the harvest discovers there. One coverage run and a static pass over
1,720 candidate trials (73 s, no test runs) is the whole cost of picking.

---

## 8. The price, and what is open

- **Worked examples:** 1 for the ring; 3 for `route4d`; 7–8 to pin a single 8-cell or affine relabelling; 4 for the
  600-cell's rotations. Refusing is how a 4D law pays when it has too few.
- **Packing:** the 32-bit word holds k = 3 at most (8k + 4 bits); more examples need a wider word.
- **Not yet authored:** a 600-cell router (120 kinds, one example) — the structure with the most bits per example.
- **Measured on fluid-router's 33-bug corpus (section 7b):** the 4D law is right on every real decision when the
  vocabulary is numbered 4D-natively, and wrong on 50–100% when it keeps fluidfix's ring numbering. The corpus
  cannot say which numbering is "real" — it is a convention, chosen once.
- **Still open:** a corpus with more than four fault kinds, where the refuse-instead-of-guess safety can show.
- The 4D advantage above is **structural** — it holds whatever is taught; what it is worth in practice is the
  open measurement.

---

## 9. Reproduce

```bash
.venv/bin/python generalize.py                      # sections 2-4, 6 -> results/GENERALIZE.md
.venv/bin/python judge_router4d.py --calibrate      # fluidfix's router through the judge
.venv/bin/python judge_router4d.py --class affine --k 3 --name route4d --sample 30000 laws/router4d.c
```

| file | what |
|---|---|
| `generalize.py` | builds every structure, measures version spaces, writes the ROUTER4D prompt |
| `prompts/ROUTER4D_LAW_PROMPT.md` | the superoptimizer task: defect, structures, choices, G0–G5 — no law in it |
| `laws/router4d.c` | your law, verbatim |
| `judge_router4d.py` | judges a kernel against the structure its author declares |
| `polytopes.py` | the 4D polytopes, measured from coordinates |
| `results/GENERALIZE.md`, `results/generalize.json` | the measurements quoted here |
