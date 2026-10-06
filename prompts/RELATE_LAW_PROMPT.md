# Superoptimizer task - the RELATE law: a swarm learning fix relations like neurons

**Not authored here.** This file gives the defect, the measurement, the bits and the principles; it gives no formula
and no table. Your engine authors the expression, and `python -m neo4d.judge_relate laws/relate.c` judges it by
enumeration.

---

## The defect - neo4d memorises, it does not generalise

| measured | coverage of real fixes |
|---|---|
| fluidfix's 9 shipped classes, on 706 small real fixes (BugsInPy, Defects4J, Defects4C) | **3.4%** |
| INDUCE learning literal one-token patterns on click's history | **1.2%**, flat (`results/INDUCE_LIVE.md`) |
| literal edits learned in other projects, tried on a new one | **7.5%** (`results/RELATIONS.md`) |
| **relations** learned in other projects, tried on a new one | **21.2%** - generalisation nearly triples it |

A **relation** is a fix with the project-specific parts abstracted (`neo4d/relations.py`):
- Operators and keywords stay literal.
- Identifiers become placeholders. A new identifier becomes a near-copy of an old one, or another name already in
  scope.
- Integers become placeholders. A new integer becomes the old one plus or minus one, or a number in scope.

So `count + 1 -> count + 2` and `size - 1 -> size - 2` are one relation with two literal forms. Applied to a buggy
line, a relation generates every line it can make.

**But using every relation floods the repair.** On the live stream below, every relation at first sight covers 17.5%
and proposes 14,289 candidates on each fix line and 1.8 million on each unchanged line; each candidate is a suite run.
The relations that generalise best (a name becomes another name in scope) are also the ones that fire everywhere.
Which relations to use, and when, is the decision. Today nothing makes it.

---

## The decision - one relation is one neuron

Every relation the swarm has seen has a strength, set by the law on every event that touches it:

```
0 UNKNOWN    never seen
1 PRIMED     remembered, never used to propose
2 ACTIVE     proposes fixes, in every net of the swarm
3 PROVEN     active, and it predicted a real fix before it learned it
```

The swarm is the 49 projects of the three benchmarks, each one a net. The neurons are shared: a fix in any net is an
event for them, and a relation active anywhere proposes everywhere. That is how one project's fixes generalise to
another's.

## The measurement the body will supply

| bit | name | set when |
|---|---|---|
| 0-1 | `LEVEL` | the relation's current strength, 0..3 |
| 2 | `FIRE` | this fix instantiates the relation (the relation is this fix's edit, abstracted) - the neuron fires with the input |
| 3 | `NEWNET` | ... and it is the relation's first firing in this net |
| 4 | `PREDICTED` | applied to the buggy line before this fix was learned, the relation generated the fixed line exactly |
| 5 | `CHEAP` | it proposes at most 5 candidates on a line it fires on, and at most 0.5 per unchanged line |
| 6 | `COSTLY` | it proposes more than 30 on a line it fires on, or more than 35 per unchanged line |
| 7 | `BARREN` | while active, it fired on 10 or more fix lines and generated fewer than 5% of them |

**Situation word:** `x = LEVEL | FIRE << 2 | NEWNET << 3 | PREDICTED << 4 | CHEAP << 5 | COSTLY << 6 | BARREN << 7`

**Unreachable** (the law may return anything there, but must land in 0..3):
- `CHEAP` with `COSTLY`: one relation has one cost.
- `NEWNET` without `FIRE`: a first firing needs a firing.
- `LEVEL` 0 with `PREDICTED` or `BARREN`: only a remembered relation is applied ahead, or has a record.
- `LEVEL` 0 with `FIRE` and not `NEWNET`: an unknown relation's first firing is in a new net.

That leaves **114 reachable values of 256.**

## The law to find

```
relate(x) -> 0..3      the relation's new strength
```

## The principles - stated as "exactly when", so they force every cell

- **R1 A costly relation is never used.** `COSTLY`: 1 if it fires or is remembered, else 0. It is remembered as
  primed, and never active, whatever else happens.
- **R2 Silence keeps.** No `FIRE` and no `PREDICTED`: the strength is unchanged (unless R9).
- **R3 First sight primes.** An unknown relation that fires, and is not cheap: 1.
- **R4 A cheap relation is used at first sight.** `FIRE` and `CHEAP`: at least 2.
- **R5 A second net generalises.** A remembered relation that fires in a new net (`FIRE`, `NEWNET`, `LEVEL` >= 1): at
  least 2.
- **R6 A correct prediction potentiates by one.** `PREDICTED`: one step up, from 1 to 2, from 2 to 3, with 3 kept.
- **R7 Proven only by prediction.** 3 is reached from below only with `PREDICTED`.
- **R8 Nothing else raises.** Past R1, the new strength is exactly the highest of the current one and what R3-R6
  grant.
- **R9 A barren relation weakens unless cheap or proven.** `BARREN`, not `CHEAP`, not `PREDICTED`, and R8 would give
  2: 1. A connection that keeps firing without reward weakens. A cheap one costs too little to matter, and a proven
  one is consolidated.

**Checked before asking: the principles fix every cell.** `python -m neo4d.judge_relate --selfcheck` shows exactly one
table satisfies R1-R9 on the 114 reachable words. That table is built only to be perturbed and measured, and is not
handed over. Every single-cell change to it breaks at least one principle.

**Checked before asking: the table raises coverage** (`python -m neo4d.relate_live --spec`, `results/RELATE_LIVE.md`).
The 706 fixes arrive bug by bug, in a seeded random order (8 seeds averaged); each bug is scored before it is
learned from.

| policy | covers | first half -> second half | candidates on the fix line | per unchanged line |
|---|---|---|---|---|
| fluidfix's 9 shipped classes | 3.4% | 3.4% -> 3.4% | 0.6 | 0.3 |
| cheap literal edits at first sight (memorisation) | 5.1% | 2.7% -> 7.5% | 2.0 | 1.2 |
| cheap relations at first sight (no law) | 6.7% | 4.8% -> 8.6% | 3.8 | 2.1 |
| **the table R1-R9 allow** | **7.5%** | **5.3% -> 9.7%** | 18.9 | 25.5 |
| every relation at first sight (no law) | 17.5% | 13.5% -> 21.6% | 14,289 | 1.8 million |

It learns: coverage nearly doubles from the first half of the stream to the second. It costs more than the cheap-only
rule, because R6 lets mid-cost relations in once they predict. Measured honestly on this stream:
- R5 (a second net) changes nothing; R6 does all the work.
- If cost matters more than coverage, dropping mid-cost relations gives 6.7% at a tenth of the candidates. The
  principles here keep them.

## Constraints

- **Branchless integer arithmetic over `x`**: shifts, masks, adds, subtracts, and popcount and `ntzb` if your engine
  has them, defined in the file itself. Fewer operations is better.
- **Total** on 0..255, landing in 0..3; **exact** on every reachable word.
- Signature: `int32_t relate(int32_t x)`.

## How it will be judged

```bash
python -m neo4d.judge_relate laws/relate.c
```

R1-R9 are checked by enumeration on every reachable word, the range on all 256, and every single-cell change to the
kernel's own table must break a principle. Then live: `python -m neo4d.relate_live laws/relate.c` runs the swarm with
the law deciding every neuron, and we see whether coverage increases. The target is the table's row above, which the
law must equal.

**What the superoptimizer does not decide:**
- The body's measurement: what a relation abstracts, the cost thresholds behind `CHEAP` and `COSTLY` (5, 0.5, 30, 35),
  and the record behind `BARREN` (10 firings, 5%).
- Whether a fix the relations generate is right. Every candidate still goes through the suite and the SHIP law. If the
  live run says a threshold is wrong, the measurement changes, never the table.
