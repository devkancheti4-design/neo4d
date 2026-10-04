# Superoptimizer task - the HARVEST law: fluidnet learns its own worked examples by mutation

**Not authored here.** The defect, the measurement, the bits and the principles - no formula, no table. Your engine
authors the expression; it will be judged by enumeration against the principles below.

---

## The defect

The 4D router needs worked examples - *case F was handled by action A* - and fluidfix ships exactly one, typed by
a person: `WORKED_EXAMPLE = (0, 5)`. A one-example ring router can live on that. A 4D router cannot: measured on
1,566 real fixes (`corpus4d_big.py`), `route4d` with three examples answers 8% of real decisions; the structure
answers **98.7%** with seven random examples and **100% with five chosen ones**. Nobody should type five.

## Why fluidnet can harvest them itself

Most of fluidfix's classes are **flips** - `<` <-> `<=`, `+` <-> `-`, `True` <-> `False`, `min` <-> `max`, `+=`
<-> `-=`. A flip is its own inverse, so **the act that injects a fault of kind F is the act that repairs it**.
Take green code, mutate one line with an act, let the suite go red, try the acts: the one that restores the line
byte-for-byte and greens the suite *is* a worked example (F -> A). buggy, fluidnet's locator, already runs this
mutation lane. Measured on fluid-router's corpus: **33 of 40** seeded mutations in five unseen libraries were caught
by the libraries' own suites - most mutants make valid examples.

## What choosing them well buys - measured (version space, no law; 60 real decisions, 4D-native vocabulary)

| 5 harvested examples | right | refused | wrong |
|---|---|---|---|
| taken as they come | 74.6% | 25.4% | 0% |
| **each one adding a new direction** | **100%** | **0%** | **0%** |

An example only teaches the affine router if its difference from the first example leaves the span of the ones
already taken. Five that span GF(2)^4 pin the relabelling exactly. The harvest's job is to find those five, prove
each one, and stop.

---

## The decision

For ONE mutation trial - one kind's mutant at one site, already run - what to do with it, decided from eight
measured bits and nothing else.

## The measurement the body will supply

| bit | name | set when |
|---|---|---|
| 0 | `KILLED` | the mutant turned the suite red - at least one test fails |
| 1 | `RESTORES` | some act restores the original line byte-for-byte and the full suite is green again |
| 2 | `UNIQUE` | exactly one act does - no second act also greens the suite |
| 3 | `STABLE` | re-running both suites (red with the mutant, green restored) gave the same results |
| 4 | `NEW_SPAN` | the example's difference from the first harvested example lies outside the span of the harvested differences (the first example always sets it) |
| 5 | `RECHECKED` | this trial was already re-run once for stability |
| 6 | `FULL` | the harvested differences already span GF(2)^4 - five affinely independent examples, the relabelling pinned |
| 7 | `SPENT` | the harvest's budget of suite runs is spent |

**Situation word:** `x = KILLED | RESTORES << 1 | UNIQUE << 2 | STABLE << 3 | NEW_SPAN << 4 | RECHECKED << 5 |
FULL << 6 | SPENT << 7`

**Unreachable** (the law may return anything there, but must land in 0..3). Note they already give
`UNIQUE => RESTORES`, so `RESTORES` never changes the decision - found by the first authored kernel, confirmed by
the judge:
- `RESTORES`, `UNIQUE` or `STABLE` without `KILLED` - with no red suite there is nothing to restore or re-run.
- `UNIQUE` without `RESTORES`.
- `FULL` with `NEW_SPAN` - once the span is full nothing is outside it.

## The law to find

```
harvest(x) -> 0..3
   0  SKIP      discard this trial; mutate another site or kind
   1  TAKE      record (kind -> act) as a worked example
   2  STOP      hand the harvested examples to the router
   3  RECHECK   re-run this trial once
```

## The principles

- **H0 No oracle, no example.** Not `KILLED`: never TAKE. A mutant the suite cannot see proves nothing - measured on
  fluid-router's benchmark, a kernel searching without a failing test corrupted working code 7 times in 7.
- **H1+H3 TAKE exactly when it teaches.** Not stopping (H4, H5), and `KILLED`, `RESTORES`, `UNIQUE`, `STABLE` and
  `NEW_SPAN` all hold: TAKE - and TAKE in no other case. Two acts that both green the suite are a choice, not a fact;
  an example inside the span teaches the router nothing (the measured gap between 74.6% and 100%).
  *Corrected after the first authored kernel: phrased only as requirements, nothing ever forced a TAKE, so a kernel
  that takes nothing passed every principle and cells x = 31, 63 came loose. The iff reading fixes every cell.*
- **H2 Instability is rechecked once.** `KILLED` and not `STABLE`, not yet `RECHECKED`: RECHECK. Once `RECHECKED`:
  SKIP - flaky.
- **H4 Stop when pinned.** `FULL`: STOP, whatever the trial says. Five independent examples determine the
  relabelling; a sixth adds nothing.
- **H5 The budget is respected.** `SPENT` and not `FULL`: STOP - hand over what there is; the router refuses what
  stays open.
- **H6 Otherwise SKIP.** A trial that is neither taken, rechecked, nor a reason to stop is discarded.
- **H7 RECHECK only for instability.** A stable trial is never rechecked; `RECHECKED` never yields RECHECK again.

## Constraints

- **Branchless integer arithmetic over `x`**; shifts, masks, adds, subtracts, popcount and `ntzb` if your engine has
  them, defined in the file itself. Fewer operations is better.
- **Total** on 0..255, landing in 0..3; **exact** on every reachable word.
- Signature: `int32_t harvest(int32_t x)`.

## How it will be judged

`judge_harvest.py`: by enumeration against H0-H7 on every reachable word, and the check that the principles alone fix every reachable
cell (each single-cell change to the kernel's table must break at least one principle). Then the harvest runs for
real: mutate the click and fluid-router corpora with fluidfix's flips, harvest five examples per renumbering, hand
them to the router, and score the 60 real decisions of `corpus4d_big.py` - the target is the measured 100% right,
0% wrong.

**What the superoptimizer does not decide:** which kind to mutate next, or where. That is a second decision - a PICK
law ranking candidate (kind, site) trials by how likely they are to be killed, unique and new in span - and it gets
its own prompt once HARVEST is judged.
