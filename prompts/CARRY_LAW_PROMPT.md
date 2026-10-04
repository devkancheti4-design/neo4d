# Superoptimizer task - the CARRY law

**Shape:** every shape - fluidnet's nets on the polytope.  
**Decides:** After one net has worked on a job, what travels on: the partial repair, the certified module, a recheck, or nothing - decided from eight measured bits and nothing else.

---

The swarm lives on a regular 4D polytope: every vertex is a node, every edge a link, and data flows
node to node along the links. The shape is the advantage - every node is identical (the polytopes are
vertex-transitive), many pairs have more than one shortest route, and every node has as many
node-disjoint routes to any other as it has links (all measured, by `polytopes.py`).

The rule of this repository: **the law decides and the body only measures.** The body turns what it measured
about one decision into one byte, the situation word. The law turns that byte into the decision. No weights,
no `if`s in the law, no number that is a guess.

## What the shape supplies

fluidnet as built never lets a net hand anything on: each net starts from the original code and the first
green wins. So a job whose faults need taught classes from two different nets is refused, though the swarm
holds both answers. On the polytope a job travels, and what it carries is this law's decision. Measured
here on the 8-cell, 30 jobs whose two taught faults live in two different dictionaries (plus one shipped
fault), every law at its reference table:

| | repaired |
|---|---|
| fluidnet as built (overseer, each net alone) | 0/30 |
| on the 8-cell, partial repairs carried | 30/30 |

Acceptance did not loosen to get there: the only state ever accepted is green, no step in it was refuted by
its class property, and under `STRICT` every step must be proven - a class with no property (all nine
shipped ones) is UNPROVEN, which fluidfix lets pass and `STRICT` does not.

## What must not be done

Do not ship partial progress - ever. Do not carry an edit that broke a passing test. Do not treat a flaky green as green. Do not loosen acceptance to make travel pay.

---

## The measurement the body will supply

Eight bits. Every one is measured mechanically; none is a judgement.

| bit | name | set when |
|---|---|---|
| 0 | `GREEN` | no test fails now |
| 1 | `STABLE` | re-running the suite on the current code gave the same failing set |
| 2 | `BROKE` | a test that passed when the job left its edge node fails now |
| 3 | `UNPROVEN` | some step in the carried repair rests on a class with no property proof (fluidfix fails open: no property is UNPROVEN, not REFUTED) |
| 4 | `STRICT` | the job's policy demands every step proven |
| 5 | `PLAN_LEFT` | the code still shows the signals of a dictionary not yet visited, and a copy of it is live |
| 6 | `SPENT` | the job's visit budget is spent |
| 7 | `RECHECKED` | this state was already re-run once for stability |

**Situation word:** `x = GREEN | STABLE << 1 | BROKE << 2 | UNPROVEN << 3 | STRICT << 4 | PLAN_LEFT << 5 | SPENT << 6 | RECHECKED << 7`

**Unreachable, so the law may return anything there (but must still land in 0..3):**
- `GREEN` with `BROKE` - green means no test fails, so none that passed fails.

That leaves **192 reachable values of 256.**

---

## The law to find

```
carry(x) -> 0..3
   0              REFUSE - the original returns to the edge, untouched
   1              CARRY - the partial repair travels to the next net
   2              ACCEPT - certified; ship it
   3              RECHECK - re-run the suite once
```

### The principles that fix the table

- **C0** - **Accept exactly the certifiable.** ACCEPT (2) when, and only when, `GREEN`, `STABLE`, not `BROKE`, and not (`STRICT` and `UNPROVEN`). Partial progress travels; only a green, stable, provable module ever ships.
- **C1** - **Fail closed.** `BROKE`: REFUSE (0) - an edit that broke a passing test neither travels nor ships; the original returns to the edge untouched.
- **C2** - **Instability is not evidence.** Not `STABLE` (and not `BROKE`): RECHECK (3) once; once `RECHECKED`, REFUSE - flaky.
- **C3** - **A green that cannot be certified is refused.** `GREEN`, `STABLE`, `STRICT` and `UNPROVEN`: REFUSE - no later net can prove a step already taken.
- **C4** - **Carry while there is somewhere to go.** Red, `STABLE`, not `BROKE`, `PLAN_LEFT`, not `SPENT`: CARRY (1) - whether or not this visit helped, another net may.
- **C5** - **Partial never ships.** Red, `STABLE`, not `BROKE`, and no plan left or the budget spent: REFUSE.
- **C6** - **RECHECK only for instability.** A stable state is never rechecked, and `RECHECKED` never yields RECHECK again.

**They fix every cell.** Each of the 576 single-cell changes to the table below - every reachable word,
every other value in 0..3 - breaks at least one principle, checked by enumeration
(`judge.py --selftest`). The table is the principles' consequence, not a choice beside them.

### Truth table - all 256 values

Row `r`, column `c` is `x = 16r + c`. `.` is unreachable.

```
x=  0..15   3 3 0 2 0 . 0 . 3 3 0 2 0 . 0 .
x= 16..31   3 3 0 2 0 . 0 . 3 3 0 0 0 . 0 .
x= 32..47   3 3 1 2 0 . 0 . 3 3 1 2 0 . 0 .
x= 48..63   3 3 1 2 0 . 0 . 3 3 1 0 0 . 0 .
x= 64..79   3 3 0 2 0 . 0 . 3 3 0 2 0 . 0 .
x= 80..95   3 3 0 2 0 . 0 . 3 3 0 0 0 . 0 .
x= 96..111  3 3 0 2 0 . 0 . 3 3 0 2 0 . 0 .
x=112..127  3 3 0 2 0 . 0 . 3 3 0 0 0 . 0 .
x=128..143  0 0 0 2 0 . 0 . 0 0 0 2 0 . 0 .
x=144..159  0 0 0 2 0 . 0 . 0 0 0 0 0 . 0 .
x=160..175  0 0 1 2 0 . 0 . 0 0 1 2 0 . 0 .
x=176..191  0 0 1 2 0 . 0 . 0 0 1 0 0 . 0 .
x=192..207  0 0 0 2 0 . 0 . 0 0 0 2 0 . 0 .
x=208..223  0 0 0 2 0 . 0 . 0 0 0 0 0 . 0 .
x=224..239  0 0 0 2 0 . 0 . 0 0 0 2 0 . 0 .
x=240..255  0 0 0 2 0 . 0 . 0 0 0 0 0 . 0 .
```

(Reachable: REFUSE 128, RECHECK 32, ACCEPT 24, CARRY 8.)

Anchors, so the table can be read against reality - every shape-dependent bit is computed from the real shape
(`anchors.py`):

| situation | x | carry |
|---|---|---|
| 8-cell, a job with faults rename-38, rename-5, rename-19, minmax-swap: after visit 1, at node `0000` | 42 | **1** CARRY |
| 8-cell, a job with faults rename-38, rename-5, rename-19, minmax-swap: after visit 2, at node `0001` | 42 | **1** CARRY |
| 8-cell, a job with faults rename-38, rename-5, rename-19, minmax-swap: after visit 3, at node `0011` | 42 | **1** CARRY |
| 8-cell, a job with faults rename-38, rename-5, rename-19, minmax-swap: after visit 4, at node `0101` | 11 | **2** ACCEPT |
| the same job under a STRICT policy, at the end: green, but a shipped class's step has no property | 27 | **0** REFUSE |
| red and the re-run disagreed - first time | 0 | **3** RECHECK |
| red and the re-run disagreed again | 128 | **0** REFUSE |
| a carried edit broke a test that passed at the edge | 38 | **0** REFUSE |
| red, a net left to try, visit budget spent | 98 | **0** REFUSE |

---

## Constraints

- **Branchless integer arithmetic over `x`.** No conditionals, no lookup table - the same character as the
  existing laws: lanes of shifts and masks, counted, then ranked.
- Shifts, masks, adds, subtracts, and popcount and `ntzb` if your engine has them. Fewer operations is better.
- **Total** on 0..255 and **exact** on every reachable word. The judge compiles the file **on its own**
  (`cc -O2 -shared`), so define every helper it uses - popcount, `ntzb` - in the file itself, the way the
  existing laws define their lanes. A `main()` that checks itself is welcome and is not run by the judge.
- Signature: `int32_t carry(int32_t x)`; or a Python port, `def carry(x)`.

## How it will be judged

```
.venv/bin/python judge.py carry laws/carry.c
```

1. **Exhaustively against the table**, all 192 reachable `x`, and the range on all 256.
2. **Every principle re-checked by enumeration on the kernel itself**, not only through the table -
   C0, C1, C2, C3, C4, C5, C6.
3. **The anchors.**

Zero violations or it is not the law.

**What the superoptimizer does not decide:** The visit budget behind `SPENT`, and whether a second recheck would rescue real work from a flaky suite. Both are measured in the swarm (`experiment.py`); the table follows from its principles.
