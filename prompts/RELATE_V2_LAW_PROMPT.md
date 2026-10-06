# Superoptimizer task - the RELATE law, v2: a barren relation weakens even when it is cheap

**Not authored here.** This file gives the defect, the measurement, the bits and the principles; it gives no formula
and no table. Your engine authors the expression, and `python -m neo4d.judge_relate laws/relate_v2.c --v2` judges it
by enumeration.

v1 is authored, judged (0 violations, 54 instructions) and kept: `neo4d/kernels/relate_v1.c`,
`prompts/RELATE_LAW_PROMPT.md`. v2 has the same word, the same bits and the same reachable set. **One principle
changes**, and the table changes in exactly **5 of the 114 reachable cells**.

---

## The defect - v1 is gullible: one wrong lesson makes a cheap rule that never dies

v1's R9 reads "a barren relation weakens **unless cheap** or proven". A cheap relation therefore can never weaken,
however often it fires and however rarely it is right. With a perfect teacher that costs little. With a noisy
teacher - and any teacher that is a live system's own output is noisy - every wrong lesson about a cheap edit
becomes an active rule at once (R4), and stays active forever.

Measured on the mutation domain (`results/DOMAIN_HARD.md`, E4): 10,000 lessons from the standard library, a share of
them replaced by random wrong edits, tested on held-out modules against the true teacher, 3 seeds averaged:

| wrong lessons | v1: coverage | **v1: precision** | v2's table: coverage | **v2's table: precision** |
|---|---|---|---|---|
| 0% | 96.4% | 81.6% | 96.3% | **82.0%** |
| 10% | 96.3% | **1.9%** | 96.3% | **58.4%** |
| 30% | 96.1% | **1.1%** | 95.9% | **27.3%** |
| 50% | 95.5% | **0.9%** | 95.4% | **20.0%** |

At 10% wrong lessons, v1 activates about 400 junk rules. A typical one is "a name followed by a name: replace the
second by `None`", which fires on 31% of lines. Together they spray 75 junk candidates per line. Each junk rule is
individually cheap (one candidate where it fires, fewer than 0.5 per line), so v1's cost bits never catch them. Its
record is what catches them: such a rule fired on 1,679 of 10,000 taught lines and was right on none. v1 reads that
record and is not allowed to act on it.

**What v2 costs** on the real-bug streams (`results/RELATE_LIVE.md`, literal edits and relations as neurons, the
body's barren record at 100 firings):

| stream | v1 | v2's table |
|---|---|---|
| bugs, 49 projects (8 seeds) | 10.3% (6.9% -> 13.7% as it learns) | 10.0% (6.9% -> 13.1%) |
| click's history, commit order | 17.4% (10.7% -> 24.0%) | 17.4% (10.7% -> 24.0%) |

---

## The decision - unchanged

One relation is one neuron; the law sets its new strength on every event that touches it:

```
0 UNKNOWN    never seen
1 PRIMED     remembered, never used to propose
2 ACTIVE     proposes fixes (or mutants), in every net of the swarm
3 PROVEN     active, and it predicted a real instance before it learned it
```

## The measurement - unchanged

| bit | name | set when |
|---|---|---|
| 0-1 | `LEVEL` | the relation's current strength, 0..3 |
| 2 | `FIRE` | this lesson instantiates the relation |
| 3 | `NEWNET` | ... and it is the relation's first firing in this net |
| 4 | `PREDICTED` | applied before this lesson was learned, the relation generated it exactly |
| 5 | `CHEAP` | it proposes at most 5 candidates on a line it fires on, and few on others (the body's budget) |
| 6 | `COSTLY` | it proposes more than 30 on a line it fires on, or too many on others (the body's budget) |
| 7 | `BARREN` | while active, it fired on enough lines (the body's record length) and was right on fewer than 5% |

**Situation word:** `x = LEVEL | FIRE << 2 | NEWNET << 3 | PREDICTED << 4 | CHEAP << 5 | COSTLY << 6 | BARREN << 7`

**Unreachable** (anything there, but land in 0..3), as in v1:
- `CHEAP` with `COSTLY`.
- `NEWNET` without `FIRE`.
- `LEVEL` 0 with `PREDICTED` or `BARREN`.
- `LEVEL` 0 with `FIRE` and not `NEWNET`.

That leaves **114 reachable values of 256.**

## The law to find

```
relate_v2(x) -> 0..3      the relation's new strength
```

## The principles - stated as "exactly when", so they force every cell

R1-R3 and R5-R8 are v1's, word for word. **R4 and R9 change.**

- **R1 A costly relation is never used.** `COSTLY`: 1 if it fires or is remembered, else 0.
- **R2 Silence keeps.** No `FIRE` and no `PREDICTED`: the strength is unchanged (unless R9).
- **R3 First sight primes.** An unknown relation that fires, and is not cheap: 1.
- **R4 A cheap relation is used at first sight - unless R9.** `FIRE` and `CHEAP`: at least 2, **except where R9
  weakens it**. (New: a cheap relation whose record is barren does not come back by firing again.)
- **R5 A second net generalises.** A remembered relation that fires in a new net: at least 2 (unless R9).
- **R6 A correct prediction potentiates by one.** `PREDICTED`: one step up, from 1 to 2, from 2 to 3, with 3 kept.
- **R7 Proven only by prediction.** 3 is reached from below only with `PREDICTED`.
- **R8 Nothing else raises.** Past R1, the new strength is exactly the highest of the current one and what R3-R6
  grant (unless R9).
- **R9 A barren relation weakens unless proven.** `BARREN`, not `PREDICTED`, and R8 would give 2: 1. **Changed: the
  "unless cheap" exemption is gone.** A connection that keeps firing without reward weakens, whatever it costs; only a
  proven one is consolidated.

**Checked before asking: the principles fix every cell.** `python -m neo4d.judge_relate --selfcheck --v2` shows
exactly one table satisfies R1-R9 on the 114 reachable words, and every single-cell change to it breaks at least one
principle. That table is built only to be perturbed and measured, and is not handed over.

**Checked before asking: the change is exactly the measured one.**
- The v2 table differs from v1's in **5 cells**, and every one is `BARREN` and `CHEAP` (`--selfcheck --v2` prints
  this).
- v1's authored kernel, judged as v2, fails exactly those 5 cells (`R9`: 162, 165, 166, 173, 174) and nothing else.
- The table behind the noise and bug measurements above is this table, cell for cell.

## Constraints

- **Branchless integer arithmetic over `x`**: shifts, masks, adds, subtracts, and popcount and `ntzb` if your engine
  has them, defined in the file itself. Fewer operations is better. For scale, v1 is 54 instructions with no branches
  and no memory operations; v2 moves 5 cells, so v1's lanes are a fair place to start.
- **Total** on 0..255, landing in 0..3; **exact** on every reachable word.
- Signature: `int32_t relate_v2(int32_t x)`.

## How it will be judged

```bash
python -m neo4d.judge_relate laws/relate_v2.c --v2
```

R1-R9 (v2) are checked by enumeration on every reachable word, the range on all 256, and every single-cell change to
the kernel's own table must break a principle. Then live, with the law deciding every neuron:
- the noisy teacher (`neo4d domain-hard`, E4): the target is the table's precision above, 58.4% at 10% wrong lessons;
- the bug streams (`neo4d relate-live`): the target is 10.0% across 49 projects and 17.4% on click.

The law must equal the table, so those are its numbers.

**What the superoptimizer does not decide:**
- The record length behind `BARREN`. Real bug relations hit rarely, so the bug runs judge a relation on 100 firings;
  mutation relations hit often, so the domain runs judge on 10. With v2, that length decides how fast a wrong rule
  dies and how long a rare right one survives. It is the body's per-domain setting, never a cell of the table.
- The cost budgets behind `CHEAP` and `COSTLY`, and what a relation abstracts.
- Whether a proposal is right: every candidate still goes through the tests and the SHIP law.
