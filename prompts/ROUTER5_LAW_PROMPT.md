# Superoptimizer task - the 32-KIND ROUTER: route4d5 grown from 16 kinds to 32

**Not authored here.** This file gives the defect, the measurement and the requirements; it gives no formula and no
table. Your engine authors the expression, and `python -m neo4d.judge_router5 laws/route5.c --prove` judges it.

---

## What exists - authored by your engine, judged here

| law | does | judged |
|---|---|---|
| `route4d5` | the router on affine GF(2)^4: 16 kinds, k = 5, int64 | 0 violations; all 68,719,476,736 reduced words exhaustively; **CBMC proof on all 2^64 words** (`results/KIT_PROOF.md`) |
| `harvest`, `pick`, `induce`, `ship` | the self-learning loop and the ship decision | all 256 inputs enumerated |

## The defect - four bits name sixteen kinds

| measured | where |
|---|---|
| A fluidnet net has **16 kernel slots** (9 shipped, 7 taught); the numbering names 16 kinds | `neo4d/classes.py` |
| INDUCE, live on click's history, admitted **9 classes on top of fluidfix's 9 shipped: 18 kinds**. Two of them have no code, and route4d5 cannot route them | `results/INDUCE_LIVE.md` |
| Six affine examples of 32 kinds plus a query need **65 bits**; an int64 holds 64 | `results/KIT_SCALING.md` |

route4d5 is correct on every word it can be given (proved), but it can only be given 16 kinds.

## Why six examples are enough - exact (`results/ROUTER5_MATH.md`, checked by simulation)

| | 16 kinds | **32 kinds** |
|---|---|---|
| affine relabellings | 322,560 | **319,979,520** |
| examples that pin one | 5 | **6** |
| the minimum cases (5, 6), taken as they come, pin it | 8/13 = 61.5% | **128/261 = 49.0%** |
| ... share of queries then answered (never wrong) | 21/26 = 80.8% | **773/1044 = 74.0%** |
| **each case a new direction - what HARVEST delivers** | **100%** | **100%** |
| cases drawn at random until pinned, expected | 215/39 = 5.51 | **16833/2465 = 6.83** |
| a truth outside the structure, from the minimum examples: wrong | 5/13 = 38.5% | **100/261 = 38.3%** - and 1.4% with one validation example (7) |

Six affinely independent cases determine an affine map of GF(2)^5 exactly, and every query is then answered.

---

## The decision

Given k = 6 worked examples (case -> action, codes 0..31) and a query case, return the action that every affine
bijection of GF(2)^5 fitting all six agrees on. REFUSE when the fitting maps disagree, or when no affine bijection fits.

## The measurement the body will supply - example 1 moved to the origin

```
Di = Fi ^ F1,  Ei = Ai ^ A1   (i = 2..6),     Dq = Fq ^ F1

x = D2 | E2 << 5 | D3 << 10 | E3 << 15 | D4 << 20 | E4 << 25 | D5 << 30 | E5 << 35 | D6 << 40 | E6 << 45 | Dq << 50
                                                            (55 bits of an int64_t; bits 55-63 are 0)
result & 63:   0..31  the answer Eq - the body returns A1 ^ Eq,     32..63  REFUSE
```

**Why the body moves example 1, and why that loses nothing.** An affine bijection h fits the six examples exactly when
an **invertible linear map L** fits the five differences (L Di = Ei for every i), and then h(Fq) = A1 ^ L Dq. The
translation is an XOR, not a decision. It brings 65 bits down to 55, which fit an int64, and route4d5 begins with the
same XORs. The class the law answers to is therefore **GL(5,2): 9,999,360 maps**.

## The requirements - checked against GL(5,2)

- **G0 Identity.** Whenever an invertible map fits: Dq = 0 (the query is example 1) returns 0, and Dq = Di returns Ei.
- **G1 Sound.** Two fitting invertible maps disagree on Dq: REFUSE.
- **G2 Complete.** Every fitting invertible map agrees on Dq: that answer.
- **G3 Out of class.** No invertible linear map fits: REFUSE. This includes examples that only a singular map explains
  (two different cases sent to one action), and contradictions (one case sent to two actions). It is the loop's alarm
  that a dictionary is not numbered 32-natively.
- **G4 Renumber freely.** Relabel the cases by any P in GL(5,2) and the actions by any Q in GL(5,2): the answer becomes
  Q of the answer, and a REFUSE stays a REFUSE. Translations are the body's; its wrapper is judged end to end.
- **G5 Total.** Defined on every 64-bit word, with no undefined behaviour: no signed overflow, no shift out of range.
  On words with bits 55-63 set, the answer may be anything, but there must be no undefined behaviour.

Repeated cases, zero differences, and examples that span less than the whole space are legal inputs; G1-G3 decide
them like any other.

**Checked before asking: the requirements fix every word.** On each word, G2 forces the one answer or G1/G3 force
REFUSE, so exactly one function satisfies them (up to which of 32..63 encodes REFUSE). `python -m neo4d.judge_router5
--selfcheck` checks the judge itself:
- Both of its oracles (the elimination reference and the proof oracle) against brute force over all 9,999,360 maps:
  48,000 words, 0 differences.
- Three correct routers as kernels - the reference, a differently built elimination, and the proof oracle: 0
  violations each.
- Six wrong routers, each caught by the sample and again by the proof: one that reads five examples, one that guesses
  undetermined queries, one that admits singular maps, one that refuses unless the span is full, one that is the
  16-kind router reused, and one that skips the consistency check.

## Constraints

- **Branchless integer arithmetic over `x`** (int64): shifts, masks, adds, subtracts, and popcount and `ntzb` if your
  engine has them, defined in the file itself. Fewer operations is better. For scale, route4d5 compiles to 91 machine
  instructions with no branches and no memory operations (`results/SILICON.md`).
- Signature: `int64_t route5(int64_t x)`.

## How it will be judged

```bash
python -m neo4d.judge_router5 laws/route5.c --prove
```

1. **G0-G3 on 12 million seeded, stratified words** against the reference. Uniform words are almost all out of class,
   so most strata are built from a truth and then bent: one action bit flipped, one case bit flipped, repeated cases,
   singular truths, and queries inside the span, outside it, and equal to a case.
2. **G4 on 2 million renumbering draws** (P, Q from GL(5,2)).
3. **2 million harvest-shaped sets, end to end** through the body's affine wrapper (six cases each a new direction,
   truth any affine bijection). All 64 million queries must be answered, and right.
4. **G5:** every call made under UBSan.
5. **The proof**, by CBMC (bit-precise model checking, no sampling), split into 32 slices, one per query, run in
   parallel:
   - equal to the judge's proof oracle on all 2^55 words with bits 55-63 clear;
   - free of undefined behaviour on all 2^64 words.

   The proof oracle is a second oracle, independent of the elimination reference, chosen because a SAT solver handles
   it far better. Measured on route4d5 (`results/KIT_PROOF.md`): all 2^64 words proved in 8 seconds against it, and
   in 4 to 16 minutes against elimination (two runs). Both oracles agree with brute force over all of GL(5,2) on
   48,000 sampled words, and both are proved equal to route4d5 at 16 kinds. At 32 kinds, proving one elimination equal
   to another did not finish in 56 minutes.

   How long your law takes depends on its form. A slice unfinished after the time limit is reported **OPEN**, never
   as proved, and any counterexample is a violation. The selfcheck shows the proof catches all six wrong routers.
6. **Then live:** the kit's federation and degeneracy tests rerun at 32 kinds with this law in place of the reference.
   The targets are `results/ROUTER5_MATH.md`'s exact values, with 0 wrong whenever the truth is in the class.

**What the superoptimizer does not decide:**
- Whether real dictionaries are numbered 32-natively; G3 is the alarm for that.
- The body's side: the XOR with example 1, a net with 32 slots, and switching from route4d5 once the vocabulary passes
  16 kinds.
