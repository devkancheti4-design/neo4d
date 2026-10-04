# Superoptimizer task - the QUORUM law

**Shape:** 5-cell only.  
**Decides:** Whether this node commits, aborts, or keeps waiting on one proposal - decided from the votes it has heard this round and nothing else.

---

The swarm lives on a regular 4D polytope: every vertex is a node, every edge a link, and data flows
node to node along the links. The shape is the advantage - every node is identical (the polytopes are
vertex-transitive), many pairs have more than one shortest route, and every node has as many
node-disjoint routes to any other as it has links (all measured, by `polytopes.py`).

The rule of this repository: **the law decides and the body only measures.** The body turns what it measured
about one decision into one byte, the situation word. The law turns that byte into the decision. No weights,
no `if`s in the law, no number that is a guess.

## What the shape supplies

Measured on the 5-cell (`polytopes.py`): 5 nodes, 4 links each, diameter **1** - every node
is linked to every other, the only regular 4D polytope where that holds. A vote broadcast once reaches every
peer in one hop, so a proposal is decided in **one round**, with no relays and no leader. The symmetry group of
the 5-cell is every permutation of its five vertices, so the four peers of a node are interchangeable (Q5).

## What must not be done

Do not count a peer that has not answered as either vote. Do not add a timeout to the law - waiting is always safe, deciding on silence is not. Do not weight peers: they are interchangeable.

---

## The measurement the body will supply

Eight bits. Every one is measured mechanically; none is a judgement.

| bit | name | set when |
|---|---|---|
| 0 | `HEARD1` | peer 1's vote arrived this round |
| 1 | `HEARD2` | peer 2's vote arrived |
| 2 | `HEARD3` | peer 3's vote arrived |
| 3 | `HEARD4` | peer 4's vote arrived |
| 4 | `YES1` | peer 1 voted yes |
| 5 | `YES2` | peer 2 voted yes |
| 6 | `YES3` | peer 3 voted yes |
| 7 | `YES4` | peer 4 voted yes |

**Situation word:** `x = HEARD | YES << 4   (this node itself voted yes: a node that votes no aborts on its own and never consults the law)`

**Unreachable, so the law may return anything there (but must still land in 0..3):**
- `YES` bit i without `HEARD` bit i - an unheard vote is unmeasured, and an unmeasured lane is silent, not set.

That leaves **81 reachable values of 256.**

---

## The law to find

```
quorum(x) -> 0..3
   0              WAIT
   1              COMMIT
   2              ABORT
   3              never produced on a reachable word
```

### The principles that fix the table

- **Q0** - **Three yes of five commit.** This node's yes and at least two peers' yes: COMMIT (1).
- **Q1** - **Three no of five abort.** At least three peers heard voting no: ABORT (2).
- **Q2** - **Silence is not a vote.** Otherwise WAIT (0). An unheard peer is neither yes nor no; no verdict rests on who has not answered.
- **Q3** - **Agreement.** For any one assignment of votes, no two partial views of it - two nodes hearing different subsets of the peers - may yield COMMIT for one and ABORT for the other. Two majorities of five always share a voter, and a voter votes once. Checked over all 16 vote assignments and all 16 x 16 pairs of heard sets.
- **Q4** - **Hearing more never un-decides.** If a view yields COMMIT or ABORT, every view that has heard a superset of the same votes yields the same verdict.
- **Q5** - **Peers are interchangeable.** Every permutation of the four peers is a symmetry of the 5-cell, so permuting the peer indices (in HEARD and YES together) never changes the verdict. Checked on all 24 permutations.

**They fix every cell.** Each of the 243 single-cell changes to the table below - every reachable word,
every other value in 0..3 - breaks at least one principle, checked by enumeration
(`judge.py --selftest`). The table is the principles' consequence, not a choice beside them.

### Truth table - all 256 values

Row `r`, column `c` is `x = 16r + c`. `.` is unreachable.

```
x=  0..15   0 0 0 0 0 0 0 2 0 0 0 2 0 2 2 2
x= 16..31   . 0 . 0 . 0 . 0 . 0 . 0 . 0 . 2
x= 32..47   . . 0 0 . . 0 0 . . 0 0 . . 0 2
x= 48..63   . . . 1 . . . 1 . . . 1 . . . 1
x= 64..79   . . . . 0 0 0 0 . . . . 0 0 0 2
x= 80..95   . . . . . 1 . 1 . . . . . 1 . 1
x= 96..111  . . . . . . 1 1 . . . . . . 1 1
x=112..127  . . . . . . . 1 . . . . . . . 1
x=128..143  . . . . . . . . 0 0 0 0 0 0 0 2
x=144..159  . . . . . . . . . 1 . 1 . 1 . 1
x=160..175  . . . . . . . . . . 1 1 . . 1 1
x=176..191  . . . . . . . . . . . 1 . . . 1
x=192..207  . . . . . . . . . . . . 1 1 1 1
x=208..223  . . . . . . . . . . . . . 1 . 1
x=224..239  . . . . . . . . . . . . . . 1 1
x=240..255  . . . . . . . . . . . . . . . 1
```

(Reachable: WAIT 39, COMMIT 33, ABORT 9.)

Anchors, so the table can be read against reality - every shape-dependent bit is computed from the real shape
(`anchors.py`):

| situation | x | quorum |
|---|---|---|
| all four peers heard, all yes | 255 | **1** COMMIT |
| only peers 1 and 3 heard, both yes - three of five, no need to hear 2 and 4 | 85 | **1** COMMIT |
| peers 1 and 2 heard, 1 yes and 2 no - two yes, one no, two silent | 19 | **0** WAIT |
| peers 1, 2, 3 heard, all no | 7 | **2** ABORT |
| all heard, only peer 1 yes - two yes, three no | 31 | **2** ABORT |
| nobody heard yet | 0 | **0** WAIT |

---

## Constraints

- **Branchless integer arithmetic over `x`.** No conditionals, no lookup table - the same character as the
  existing laws: lanes of shifts and masks, counted, then ranked.
- Shifts, masks, adds, subtracts, and popcount and `ntzb` if your engine has them. Fewer operations is better.
- **Total** on 0..255 and **exact** on every reachable word. The judge compiles the file **on its own**
  (`cc -O2 -shared`), so define every helper it uses - popcount, `ntzb` - in the file itself, the way the
  existing laws define their lanes. A `main()` that checks itself is welcome and is not run by the judge.
- Signature: `int32_t quorum(int32_t x)`; or a Python port, `def quorum(x)`.

## How it will be judged

```
.venv/bin/python judge.py quorum laws/quorum.c
```

1. **Exhaustively against the table**, all 81 reachable `x`, and the range on all 256.
2. **Every principle re-checked by enumeration on the kernel itself**, not only through the table -
   Q0, Q1, Q2, Q3, Q4, Q5.
3. **The anchors.**

Zero violations or it is not the law.

**What the superoptimizer does not decide:** Liveness when fewer than three matching votes ever arrive: the law WAITs forever, which is safe. Re-running the round is the body's job, and it never decides.
