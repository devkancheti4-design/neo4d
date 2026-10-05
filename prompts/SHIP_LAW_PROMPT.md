# Superoptimizer task - the SHIP law: when a candidate repair is good enough to ship

**Not authored here.** The defect, the measurement, the bits and the principles - no formula, no table. Your engine
authors the expression; `python -m neo4d.judge_ship laws/ship.c` judges it by enumeration.

---

## The defect - a green suite is not a good repair

Every repair neo4d proposes is judged by the project's own tests. But "the tests pass" has shipped wrong fixes, and
every one of these failures is measured:

| failure | measured where |
|---|---|
| **no premise**: the suite was already green, so any edit "passes" - the kernel edited an unrelated line and reported success | fluid-router's benchmark: **7 of 7** such cases corrupted working code (`BENCHMARK.md`) |
| **ambiguity**: two different programs pass the whole suite, and the first one found shipped | click race: `pass` at `_textwrap.py:168` passed all 2,240 tests and was *certified* - it drops a paragraph's first-line indent; the right fix was `+=` (fluidnet `docs/results/2026-09-25`) |
| **ambiguity, refused**: two green candidates at QuixBugs' quicksort | neo4d (`results/QUIXBUGS.md`): refused rather than choosing |
| **a weak suite**: the tests only ever ask one input, and a wrong rewrite passes | rich: `int(k * len(text) - 1)` accepted by a suite that only tests `k = 1`; the class property refuted it at zero suite runs (fluidnet `FLUIDNET.md`) |
| **a guessed act**: the router could not determine which act repairs this kind | neo4d: route4d5 refuses undetermined kinds (`results/EDGE_CASES.md`) - an act that came from a refusal is a guess |

So the decision to ship needs more than green: the premise, stability, uniqueness, the property, the depth of the
evidence, and a determined act. Today these are separate `if`s in separate tools. The law decides; the body only
measures.

---

## The decision

For ONE candidate repair, already run against the suite: refuse it, ask for one deciding fact, or ship it - and say
how strongly it is certified. Decided from eight measured bits and nothing else.

## The measurement the body will supply

| bit | name | set when |
|---|---|---|
| 0 | `WAS_RED` | at least one test failed before the edit - there was something to repair |
| 1 | `GREEN` | every test passes with the candidate applied |
| 2 | `STABLE` | re-running the suite, before and after, gave the same results |
| 3 | `UNIQUE` | no other candidate found at any searched site also turns the suite green |
| 4 | `PROVEN` | the candidate's class property proved the rewrite over its inputs |
| 5 | `REFUTED` | the class property found an input where the rewrite is wrong |
| 6 | `THIN` | the edited statement is executed by at most one test (per-test coverage) - little evidence either way |
| 7 | `ROUTED` | the act applied was determined by the router for this kind (route4d5 answered, did not refuse) |

**Situation word:** `x = WAS_RED | GREEN << 1 | STABLE << 2 | UNIQUE << 3 | PROVEN << 4 | REFUTED << 5 | THIN << 6 |
ROUTED << 7`

**Unreachable** (the law may return anything there, but must land in 0..3):
- `PROVEN` with `REFUTED` - a property proves a rewrite or refutes it, not both.
- `UNIQUE` without `GREEN` - "the only candidate that turns the suite green" needs this one to be green.

That leaves **144 reachable values of 256.**

## The law to find

```
ship(x) -> 0..3
   0  REFUSE        do not ship; the file is restored byte-for-byte
   1  ASK           one deciding fact first - a test that separates two green programs, or one that exercises a
                    thinly tested edit (fluidnet's oracle and EQUIV path supply it; the oracle never chooses)
   2  SHIP          certified by the suite
   3  SHIP_PROVEN   certified by the suite AND proved by the class property
```

## The principles - stated as "exactly when", so they force every cell

- **R0 No premise, no repair.** Not `WAS_RED`: REFUSE.
- **R1 Only a stable green ships.** Not `GREEN`, or not `STABLE`: REFUSE.
- **R2 A refuted rewrite never ships.** `REFUTED`: REFUSE, however green.
- **R3 An undetermined act never ships.** Not `ROUTED`: REFUSE - neo4d never ships a guess.
- **R4 Ambiguity asks.** Past R0-R3, not `UNIQUE`: ASK - the suite cannot choose between two programs; one fact can.
- **R5 Thin evidence needs proof.** Past R0-R3, `UNIQUE`, `THIN` and not `PROVEN`: ASK.
- **R6 Ship, graded.** Past R0-R3, `UNIQUE`, and (`PROVEN` or not `THIN`): SHIP_PROVEN if `PROVEN`, else SHIP.
- **R7 Nothing ships outside R6.**

**Checked before asking: the principles fix every cell.** `python -m neo4d.judge_ship --selfcheck` shows exactly one
table satisfies R0-R7 on the 144 reachable words (built only to be perturbed - not handed over); every single-cell
change to it breaks at least one principle. That table refuses 136 situations, asks in 5, ships in 3 - quality is
meant to be strict.

## Constraints

- **Branchless integer arithmetic over `x`**; shifts, masks, adds, subtracts, popcount and `ntzb` if your engine has
  them, defined in the file itself. Fewer operations is better.
- **Total** on 0..255, landing in 0..3; **exact** on every reachable word.
- Signature: `int32_t ship(int32_t x)`.

## How it will be judged

```bash
python -m neo4d.judge_ship laws/ship.c
```

R0-R7 by enumeration on every reachable word, the range on all 256, and every single-cell change to the kernel's own
table must break a principle. Then live: every green candidate neo4d finds on QuixBugs (original and obfuscated) and
on click is measured into these bits and decided by the law. Counted: repairs shipped, asks, refusals - and **wrong
repairs shipped, which must be 0**, checked against each program's correct version.

**What the superoptimizer does not decide:** the threshold behind `THIN` (one test today), how many candidates the
search tries before calling one `UNIQUE`, and what a deciding fact is. Those are the body's; if the live run says they
are wrong, the measurement changes, never the table.
