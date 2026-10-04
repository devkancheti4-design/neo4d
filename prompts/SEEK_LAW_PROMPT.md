# Superoptimizer task - the SEEK law

**Shape:** every shape - fluidnet's nets on the polytope.  
**Decides:** How good ONE candidate net is as the next visit for ONE job - decided from eight measured bits and nothing else. The body ranks every live copy of every dictionary the job still wants and travels to the highest; ties go to the lowest node index; if every rank is 0 the job is done travelling.

---

The swarm lives on a regular 4D polytope: every vertex is a node, every edge a link, and data flows
node to node along the links. The shape is the advantage - every node is identical (the polytopes are
vertex-transitive), many pairs have more than one shortest route, and every node has as many
node-disjoint routes to any other as it has links (all measured, by `polytopes.py`).

The rule of this repository: **the law decides and the body only measures.** The body turns what it measured
about one decision into one byte, the situation word. The law turns that byte into the decision. No weights,
no `if`s in the law, no number that is a guess.

## What the shape supplies

The swarm knows every dictionary's signals (they are small) but each dictionary's appliers and properties
live only on its home node and its antipode. So the edge can see which nets the code calls for, and the
shape decides what reaching them costs. Measured on the same 8-cell jobs: a visit costs
**16.1 suite runs**, a hop costs **one message** (1.5 hops per visit). That is the whole
reason evidence outranks distance here. `NEAR` is banded against the shape's own diameter, so one law
serves the 16-cell (diameter 2) and the 120-cell (diameter 15) unchanged.

## What must not be done

Do not visit a net because it is near when another sees more of the code. Do not weight evidence against distance - evidence first, then distance, counted in bands. Do not send a job to a net that cannot be certified under the job's policy.

---

## The measurement the body will supply

Eight bits. Every one is measured mechanically; none is a judgement.

| bit | name | set when |
|---|---|---|
| 0 | `LIVE` | the copy answered - the MIRROR law chose it |
| 1-2 | `NEAR` | hops from here: `0` here, `1` one hop, `2` at most half the diameter, `3` farther |
| 3-4 | `HITS` | lines of the current code its taught signals match: `0`, `1`, `2`, `3` or more |
| 5 | `TRIED` | this dictionary already worked on this job |
| 6 | `UNCERTIFIABLE` | the job is `STRICT` and a class whose signal hits has no property |
| 7 | `FULL` | the net reported its queue full |

**Situation word:** `x = LIVE | NEAR << 1 | HITS << 3 | TRIED << 5 | UNCERTIFIABLE << 6 | FULL << 7`

**Unreachable, so the law may return anything there (but must still land in 0..15):**
- `NEAR = 0` without `TRIED` - the net here works on every job that reaches it, on arrival.
- `FULL` without `LIVE` - the queue report rides on the heartbeat; an unmeasured lane is silent.

That leaves **168 reachable values of 256.**

---

## The law to find

```
seek(x) -> 0..15
   0              never this net
   1..9           visit, higher first
   10-15          never produced on a reachable word
```

### The principles that fix the table

- **K0** - **The veto.** Not `LIVE`, `TRIED`, `HITS = 0`, `UNCERTIFIABLE`, or `FULL`: 0 - never visit a net that cannot answer, has had its turn, sees nothing in the code, cannot be certified, or cannot take the job.
- **K1** - **Evidence before distance.** Of two candidates ranked above 0, more `HITS` ranks strictly higher, however far. A visit costs suite runs; a hop costs one message.
- **K2** - **Then the nearer.** Same `HITS`: the nearer band ranks strictly higher; same band, equal rank.
- **K3** - **Usable unless vetoed.** A candidate that passes the veto ranks at least 1.
- **K4** - **Dense.** The ranks produced on reachable words are exactly 0..9, no gaps.

**They fix every cell.** Each of the 2,520 single-cell changes to the table below - every reachable word,
every other value in 0..15 - breaks at least one principle, checked by enumeration
(`judge.py --selftest`). The table is the principles' consequence, not a choice beside them.

### Truth table - all 256 values

Row `r`, column `c` is `x = 16r + c`. `.` is unreachable.

```
x=  0..15   . . 0 0 0 0 0 0 . . 0 3 0 2 0 1
x= 16..31   . . 0 6 0 5 0 4 . . 0 9 0 8 0 7
x= 32..47   0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0
x= 48..63   0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0
x= 64..79   . . 0 0 0 0 0 0 . . 0 0 0 0 0 0
x= 80..95   . . 0 0 0 0 0 0 . . 0 0 0 0 0 0
x= 96..111  0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0
x=112..127  0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0
x=128..143  . . . 0 . 0 . 0 . . . 0 . 0 . 0
x=144..159  . . . 0 . 0 . 0 . . . 0 . 0 . 0
x=160..175  . 0 . 0 . 0 . 0 . 0 . 0 . 0 . 0
x=176..191  . 0 . 0 . 0 . 0 . 0 . 0 . 0 . 0
x=192..207  . . . 0 . 0 . 0 . . . 0 . 0 . 0
x=208..223  . . . 0 . 0 . 0 . . . 0 . 0 . 0
x=224..239  . 0 . 0 . 0 . 0 . 0 . 0 . 0 . 0
x=240..255  . 0 . 0 . 0 . 0 . 0 . 0 . 0 . 0
```

(Reachable: 0 159, 1 1, 2 1, 3 1, 4 1, 5 1, 6 1, 7 1, 8 1, 9 1.)

Anchors, so the table can be read against reality - every shape-dependent bit is computed from the real shape
(`anchors.py`):

| situation | x | seek |
|---|---|---|
| 600-cell, a job with faults rename-200, rename-389, rename-246, minmax-swap, at its edge node 0: dictionary 28 at node 28, 2 hops away | 13 | **2**  |
| 600-cell, a job with faults rename-200, rename-389, rename-246, minmax-swap, at its edge node 0: dictionary 35 at node 35, 2 hops away | 13 | **2**  |
| 600-cell, a job with faults rename-200, rename-389, rename-246, minmax-swap, at its edge node 0: dictionary 55 at node 55, 3 hops away | 13 | **2**  |
| the same decision: the edge node's own dictionary - it has had its turn | 41 | **0**  |
| the same decision: a dictionary whose signals match no line of the code | 3 | **0**  |
| three or more lines match, farther than half the diameter | 31 | **7**  |
| two lines match, one hop away - fewer lines lose, however near | 19 | **6**  |
| the best candidate, but its queue is full | 155 | **0**  |
| a STRICT job, and a matching class has no property | 85 | **0**  |

---

## Constraints

- **Branchless integer arithmetic over `x`.** No conditionals, no lookup table - the same character as the
  existing laws: lanes of shifts and masks, counted, then ranked.
- Shifts, masks, adds, subtracts, and popcount and `ntzb` if your engine has them. Fewer operations is better.
- **Total** on 0..255 and **exact** on every reachable word. The judge compiles the file **on its own**
  (`cc -O2 -shared`), so define every helper it uses - popcount, `ntzb` - in the file itself, the way the
  existing laws define their lanes. A `main()` that checks itself is welcome and is not run by the judge.
- Signature: `int32_t seek(int32_t x)`; or a Python port, `def seek(x)`.

## How it will be judged

```
.venv/bin/python judge.py seek laws/seek.c
```

1. **Exhaustively against the table**, all 168 reachable `x`, and the range on all 256.
2. **Every principle re-checked by enumeration on the kernel itself**, not only through the table -
   K0, K1, K2, K3, K4.
3. **The anchors.**

Zero violations or it is not the law.

**What the superoptimizer does not decide:** Whether line counts are the right measure of evidence (against, say, failing tests a class could touch), and the band edges. Measured in the swarm; if they change, the body's measurement changes.
