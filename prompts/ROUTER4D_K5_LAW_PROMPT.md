# Superoptimizer task - the 4D ROUTER at k = 5: the last law of the self-learning loop

**Not authored here.** The defect, the measurement and the requirements - no formula, no table. Your engine authors
the expression; `judge_router4d.py` judges it against the affine class.

---

## What exists - every piece authored by your engine and judged here with 0 violations

| law | does | judged | live |
|---|---|---|---|
| `route4d` (`laws/router4d.c`) | the router on affine GF(2)^4, **k = 3**, 32-bit | 0 violations; all 1,048,576 words of its difference space | - |
| `harvest` (`laws/harvest.c`) | keep / skip / recheck / stop for one mutation trial | 0 violations, the unique kernel | - |
| `pick` (`laws/pick.c`) | which mutation to try next | 0 violations, the unique kernel | - |
| PICK + HARVEST on click | fluidnet learns its own worked examples | - | **5 trials, 5 examples, 20 suite runs**, both secret renumberings |

## The defect - measured live (`harvest_pick.py`, `results/HARVEST_PICK.md`)

The loop now harvests **five** worked examples, each a new direction. The router can only use **three**:

| on click, the same secret renumbering | the 60 real decisions |
|---|---|
| `route4d`, fed the first three harvested examples | **37 / 60** right |
| the affine version space, fed all five | **60 / 60** right, 0 refused, 0 wrong |

The 32-bit word stops at k = 3 (8k + 4 bits). Five examples need 44.

## Why five is enough - measured (version space, no law; 60 real decisions, 400 affine renumberings)

| five worked examples | right | refused | wrong |
|---|---|---|---|
| taken as they come | 74.6% | 25.4% | 0% |
| **each a new direction - what HARVEST delivers** | **100%** | **0%** | **0%** |

Five affinely independent cases determine an affine map of GF(2)^4 exactly; every query is then answered. The judge's
harvest-shaped check confirms it on 3,000 words: answered 100%.

---

## The decision

Given k = 5 worked examples (case -> action) and a query case: the action every affine map of GF(2)^4 fitting all
five agrees on - or REFUSE when fitting maps disagree, or when no affine map fits.

## The measurement the body will supply - 64-bit packing

```
x = F1 | A1 << 4 | F2 << 8 | A2 << 12 | F3 << 16 | A3 << 20 | F4 << 24 | A4 << 28 | F5 << 32 | A5 << 36 | Fq << 40
                                                                         (44 bits of an int64_t; bits 44-63 are 0)
result & 31:   0..15 the action,   16..31 REFUSE
```

The first three examples sit where `route4d` reads them. Bits 44-63 never carry data; the law must still be total
on every 64-bit word.

## The requirements - checked against the affine class

- **G0 Identity.** A query equal to a worked case returns its action, whenever the class can explain the examples.
- **G1 Sound.** Two fitting affine maps that disagree on the query: REFUSE.
- **G2 Complete.** Every fitting affine map agrees on the query: that answer.
- **G3 Out of class.** No affine map fits the five examples: REFUSE - this is how the loop learns that a dictionary is
  not numbered 4D-natively.
- **G4 Renumber freely.** Relabel cases and actions by any affine map: the answer follows; a REFUSE stays a REFUSE.
- **G5** Total on every 64-bit word; branchless integer arithmetic; your operator budget.

Repeated cases among the five, and examples that span less than the whole space, are legal inputs: G1-G3 decide
them like any other.

## Constraints

- **Branchless integer arithmetic over `x`** (int64); shifts, masks, adds, subtracts, popcount and `ntzb` if your
  engine has them, defined in the file itself. Fewer operations is better.
- Signature: `int64_t route4d5(int64_t x)`.

## How it will be judged

```bash
.venv/bin/python judge_router4d.py --class affine --k 5 --bits 64 --name route4d5 --sample 200000 laws/router4d5.c
```

1. **G0-G5 on 200,000 seeded words** against a brute-force version space of all 322,560 affine maps (the 44-bit word
   space cannot be enumerated).
2. **G4 on 20,000 renumbering draws.**
3. **50,000 harvest-shaped words** - five independent cases, truth in the class - where every query must be answered.
4. **Live:** `harvest_pick.py` reruns with PICK choosing, HARVEST deciding, and **this router** scoring the 60 real
   decisions in place of the version space. The target is the version space's own: **60 / 60 right, 0 wrong**, on
   both secret renumberings - the loop, laws end to end.

**What the superoptimizer does not decide:** whether real dictionaries are numbered 4D-natively. G3 is the loop's
alarm for that - if the harvested examples fit no affine map, the router refuses everything and says why.
