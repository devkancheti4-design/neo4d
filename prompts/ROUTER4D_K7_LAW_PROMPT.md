# Superoptimizer task - the 4D ROUTER, seven worked examples, 64 bits

**Not authored here.** The defect, the measurement and the requirements - no formula, no table. Your engine authors
the expression; `judge_router4d.py` judges it against the class you declare.

---

## What exists

`route4d` (`laws/router4d.c`, authored by your engine): the router on **affine maps of GF(2)^4**, k = 3 worked
examples, 32-bit packing. Judged here with **0 violations**, every word of its difference space enumerated.

## The defect - measured on real fixes (`corpus4d_big.py`, `results/CORPUS4D_BIG.md`)

fluidfix's eleven kinds (nine shipped classes, two taught), numbered 4D-natively (`act = kind XOR 5`), on every
one-line fix on disk - 1,566 real fixes, 60 decisions the vocabulary covers - under every 4D renumbering:

| | right | refused | wrong |
|---|---|---|---|
| fluidfix's ring router, 1 example | 32-62% | 0% | 38-68% |
| route4d, 3 examples | **8%** | 92% | **0%** |

Never wrong - but three examples span at most a plane of four codes, so it answers 8%. The 32-bit word stops at
k = 3 (8k + 4 bits).

## What more examples buy - measured (version space, no law; same 60 real decisions)

| worked examples k | 3 | 4 | 5 | 6 | **7** |
|---|---|---|---|---|---|
| right | 8.2% | 32.9% | 74.1% | 93.0% | **98.7%** |
| refused | 91.8% | 67.2% | 25.9% | 7.0% | **1.3%** |
| wrong | 0% | 0% | 0% | 0% | **0%** |
| bits | 28 | 36 | 44 | 52 | **60** |

With the HARVEST law's span-aware examples (each adds a new direction), **five** examples already reach 100% right,
0% wrong on the same 60 decisions - so k = 5 (44 bits) is enough when the examples come from HARVEST; k = 7 covers
examples taken as they come.

## The decision

Given k = 7 worked examples (case -> action) and a query case: the action every affine map of GF(2)^4 fitting all
seven examples agrees on - or REFUSE when they disagree, or when no affine map fits.

## The measurement the body will supply - 64-bit packing

```
x = F1 | A1 << 4 | F2 << 8 | A2 << 12 | ... | F7 << 48 | A7 << 52 | Fq << 56        (60 bits, int64_t)
result & 31:   0..15 the action,   16..31 REFUSE
```

## The requirements - checked by enumeration against the affine class

- **G0 Identity.** A query equal to a worked case returns its action, whenever the class can explain the examples.
- **G1 Sound.** Two fitting affine maps that disagree on the query: REFUSE.
- **G2 Complete.** Every fitting affine map agrees on the query: that answer.
- **G3 Out of class.** No affine map fits the seven examples: REFUSE.
- **G4 Renumber freely.** Relabel cases and actions by any affine map: the answer follows; a REFUSE stays a REFUSE.
- **G5** Total on every 64-bit word; branchless integer arithmetic; your operator budget.

Repeated cases among the seven examples are allowed; they add no information and must not break G0-G3.

## How it will be judged

```bash
.venv/bin/python judge_router4d.py --class affine --k 7 --bits 64 --name route4d7 laws/router4d7.c
```

G0-G5 on a seeded sample of words (the 60-bit word space cannot be enumerated), and G4 on 20,000 renumbering
draws. Zero violations or it is not the law. The same `corpus4d_big.py` then reruns the 60 real decisions with
the new law in place of the version space.

**What the superoptimizer does not decide:** whether real dictionaries are numbered 4D-natively. On fluid-router's
corpus the numbering decided the winner (`results/CORPUS4D.md`): the ring router wins under fluidfix's ring
numbering, the 4D law under a 4D-native one. Renumbering the vocabulary once is a convention change, not a law.
