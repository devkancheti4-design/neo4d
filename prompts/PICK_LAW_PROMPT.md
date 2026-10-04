# Superoptimizer task - the PICK law: which mutation fluidnet tries next

**Not authored here.** The defect, the measurement, the bits and the principles - no formula, no table. Your engine
authors the expression; `judge_pick.py` judges it by enumeration.

---

## What exists

The self-learning loop works (`harvest_live.py`, `results/HARVEST_LIVE.md`): fluidnet mutates click's real source,
click's 2,240-test suite judges each mutant, and your **HARVEST** law (`laws/harvest.c`, judged 0 violations)
decides each trial - SKIP, TAKE, STOP, RECHECK. Two secret affine renumberings, five examples each, every one of
the 60 real decisions right and none wrong, in 79 and 39 suite runs.

## The defect - measured on the 36 real trials of that run (`results/pick_motivation.json`)

Which kind to mutate next, and where, was a plain body rule: cycle the kinds, pick a random site. **26 of the 36
trials were skipped** - each one paid suite runs and taught nothing. Measured, before any suite runs, from facts
the body can know cheaply (one coverage run of click's suite, a text search, the vocabulary itself):

| fact known before the trial | taken | caught by the suite |
|---|---|---|
| the statement holding the line is **never executed** by the suite | **0/8** | **0/8** |
| executed, and **no other act** proposes a candidate on the mutant | **7/12 (58%)** | 11/12 |
| executed, and other acts compete on the mutant | 3/16 (19%) | 10/16 |
| ... of those, the line run by 10+ tests, or its function named in the tests | 1/2 and 2/10 (weak, small sample) | |

One fact gates (a statement the suite never runs was never caught), one fact dominates (no competing act: the
uniqueness check costs no extra run and almost always passes), and two weak facts follow. Rank by them and the
harvest stops paying for trials that cannot teach.

---

## The decision

How good ONE candidate trial - a (kind, site) pair - is as the next mutation, decided from eight measured bits and
nothing else. The body ranks every candidate and runs the highest; ties go to the lowest (kind, file, line); if
every rank is 0, no useful trial is left and the harvest hands over what it has.

## The measurement the body will supply

| bit | name | set when |
|---|---|---|
| 0 | `NEW_SPAN` | the kind's direction leaves the span of the examples already taken (else HARVEST skips it) |
| 1 | `EXECUTED` | the statement holding the line - its innermost enclosing statement, so a continuation line of a multi-line call or signature counts - is executed by the suite, at import or in a test (one coverage run) |
| 2 | `TRIED` | this kind was already tried at this site in this harvest |
| 3 | `ALT_NONE` | on the mutant, no act code other than the restoring one proposes any candidate - uniqueness needs no extra suite run |
| 4 | `MANY_TESTS` | ten or more tests execute the line (per-test coverage contexts) |
| 5 | `NAMED` | the enclosing function's name occurs in the test source |
| 6 | `COLD` | trials of this kind have already been skipped twice or more in this harvest |
| 7 | - | reserved, always 0 |

**Situation word:** `x = NEW_SPAN | EXECUTED << 1 | TRIED << 2 | ALT_NONE << 3 | MANY_TESTS << 4 | NAMED << 5 |
COLD << 6`

**Unreachable** (the law may return anything there, but must land in 0..15):
- bit 7 set.
- `MANY_TESTS` without `EXECUTED` - a line ten tests run is executed.

That leaves **96 reachable values of 256.**

## The law to find

```
pick(x) -> 0..15
   0       never this trial
   1..12   run it, higher first
   13-15   never produced on a reachable word
```

## The principles

- **P0 The veto.** Not `NEW_SPAN`, or not `EXECUTED`, or `TRIED`: 0. HARVEST would skip a trial that adds no
  direction; a statement the suite never runs was never caught (0 of 8 measured); a trial already run is not run
  again.
- **P1 One strong beats any number of weak.** Of two candidates past the veto, the one with `ALT_NONE` ranks
  strictly higher than the one without, whatever the other bits say.
- **P2 Weak evidence is counted, not weighted.** Same `ALT_NONE`: the rank follows how many of `MANY_TESTS`, `NAMED`
  hold - more ranks strictly higher; equal counts with equal `COLD` rank equal (`MANY_TESTS` alone ties `NAMED`
  alone).
- **P3 History breaks ties only.** Same `ALT_NONE` and the same weak count: not `COLD` ranks strictly above `COLD`.
  What happened to other sites of a kind is weaker evidence than what is measured about this site.
- **P4 Usable unless vetoed.** Every candidate past the veto ranks at least 1.
- **P5 Dense.** The ranks produced on reachable words are exactly 0..12, no gaps.

**Checked before asking: the principles fix every cell.** `judge_pick.py --selfcheck` shows exactly one table
satisfies P0-P5 - it builds that table only to perturb it, and every one of the single-cell changes to it, on every
reachable word, breaks at least one principle. (Unlike the first HARVEST prompt, which left two cells loose until
your kernel found them.)

## Constraints

- **Branchless integer arithmetic over `x`**; shifts, masks, adds, subtracts, popcount and `ntzb` if your engine has
  them, defined in the file itself. Fewer operations is better.
- **Total** on 0..255, landing in 0..15; **exact** on every reachable word.
- Signature: `int32_t pick(int32_t x)`.

## How it will be judged

```bash
.venv/bin/python judge_pick.py laws/pick.c
```

P0-P5 by enumeration on every reachable word, the range on all 256, and every single-cell change to the kernel's
own table must break a principle. Then live: `harvest_live.py` reruns with PICK choosing every trial and HARVEST
deciding it - the measure is suite runs per harvest (79 and 39 with the body rule) at the same 60/60 right, 0 wrong.

**What the superoptimizer does not decide:** the thresholds behind the bits - ten tests for `MANY_TESTS`, two skips
for `COLD` - and how candidates are enumerated. Those are the body's measurements; if the live run says they are
wrong, the measurement changes, never the table.
