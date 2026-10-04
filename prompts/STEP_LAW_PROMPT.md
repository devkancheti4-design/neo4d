# Superoptimizer task - the STEP law

**Shape:** every shape - 5-, 8-, 16-, 24-, 120- and 600-cell.  
**Decides:** How good ONE neighbour is as the next hop for ONE packet - decided from eight measured bits and nothing else. The body ranks every neighbour and sends to the highest; ties go to the lowest neighbour index; if every rank is 0 the packet stays this tick.

---

The swarm lives on a regular 4D polytope: every vertex is a node, every edge a link, and data flows
node to node along the links. The shape is the advantage - every node is identical (the polytopes are
vertex-transitive), many pairs have more than one shortest route, and every node has as many
node-disjoint routes to any other as it has links (all measured, by `polytopes.py`).

The rule of this repository: **the law decides and the body only measures.** The body turns what it measured
about one decision into one byte, the situation word. The law turns that byte into the decision. No weights,
no `if`s in the law, no number that is a guess.

## What the shape supplies

The law is the same on every shape; what changes is how many **nearer** neighbours a packet sees - the choices
the load lane gets to balance across. Measured (`polytopes.py`; where a shape is not distance-regular the count
depends on the angle to the destination, and every value seen is listed):

| shape | nodes | links each | diameter | node-disjoint routes | pairs with a choice of nearer neighbour | nearer neighbours at distance 1, 2, ... (every value seen) |
|---|---|---|---|---|---|---|
| 5-cell | 5 | 4 | 1 | 4 | 0% | 1 |
| 8-cell | 16 | 4 | 4 | 4 | 73% | 1, 2, 3, 4 |
| 16-cell | 8 | 6 | 2 | 6 | 14% | 1, 6 |
| 24-cell | 24 | 8 | 3 | 8 | 30% | 1, 1/4, 8 |
| 120-cell | 600 | 4 | 15 | 4 | 31% | 1, 1, 1, 1/2, 1/2/3, 1/2/3, 1/2, 1/2, 1/2/3, 1/2/3, 1/3, 1, 2, 3, 4 |
| 600-cell | 120 | 12 | 5 | 12 | 60% | 1, 1/3, 1/4, 1/6, 12 |

On every shape, **node-disjoint routes = links per node**: no small set of failures can cut the swarm. And
every node has the same distance profile, so one law serves every node.

## What must not be done

Do not weight the lanes: progress is ranked before load, and load is counted. Do not let a packet wander sideways because the way ahead is busy - it waits. Do not let `ROOM` or `FULL` speak when there was no heartbeat.

---

## The measurement the body will supply

Eight bits. Every one is measured mechanically; none is a judgement.

| bit | name | set when |
|---|---|---|
| 0 | `LIVE` | the link and the neighbour answered the last heartbeat |
| 1-2 | `DIST` | the neighbour's hops to the destination against this node's, from the shape's distance table: `0` one farther, `1` the same, `2` one nearer, `3` the neighbour IS the destination. (A neighbour's distance can differ by at most one, in any graph.) |
| 3 | `ROOM` | `LIVE`, and the neighbour reported its queue at most half full |
| 4 | `FULL` | `LIVE`, and the neighbour reported its queue full |
| 5 | `QUIET` | this node sent nothing across that link last tick (measured locally - known even when the link is down) |
| 6 | `VISITED` | the packet's path record already holds the neighbour |
| 7 | `AHEAD` | some neighbour of this node is `LIVE`, nearer (`DIST` 2 or 3) and not `VISITED` - full or not. The same value for every neighbour in one decision |

**Situation word:** `x = LIVE | DIST << 1 | ROOM << 3 | FULL << 4 | QUIET << 5 | VISITED << 6 | AHEAD << 7`

**Unreachable, so the law may return anything there (but must still land in 0..15):**
- `ROOM` and `FULL` together - at most half full and full.
- `ROOM` or `FULL` without `LIVE` - queue state rides on the heartbeat; with no heartbeat that lane is unmeasured, and an unmeasured lane is silent, not set.
- `DIST = 3` with `VISITED` - a packet that visited its destination was delivered there.
- `LIVE`, `DIST >= 2`, not `VISITED`, and not `AHEAD` - this neighbour is itself a live unvisited nearer neighbour, so `AHEAD` holds.

That leaves **100 reachable values of 256.**

---

## The law to find

```
step(x) -> 0..15
   0              never this neighbour
   1..9           a usable hop, higher first
   10             the destination itself
   11-15          never produced on a reachable word
```

### The principles that fix the table

- **S0** - **The veto.** Not `LIVE`, or `VISITED`: 0 - a path never revisits a node, so no packet loops. `FULL` and not the destination: 0 - backpressure; the destination consumes, it does not queue.
- **S1** - **The destination first.** A live neighbour that IS the destination: 10, strictly above every other rank.
- **S2** - **Wait for progress, never wander.** `AHEAD` and the neighbour is not nearer: 0. When a nearer neighbour is live but full, the packet waits for it - congestion passes, a detour's extra hops do not.
- **S3** - **Progress outranks load.** Of two neighbours both ranked above 0, the nearer one ranks strictly higher, whatever `ROOM` and `QUIET` say. Load chooses only among the nearer neighbours, wherever the shape offers more than one (table above) - it is never traded against progress.
- **S4** - **Load is counted, not weighted.** At the same `DIST`, the rank follows `ROOM + QUIET`: more ranks strictly higher, equal counts rank equal - `ROOM` alone ties `QUIET` alone.
- **S5** - **Usable unless vetoed.** A live, unvisited, not-full neighbour ranks at least 1 unless S2 forbids it. So a nearer neighbour is always usable, and when not `AHEAD` (every nearer neighbour dead or visited) one at the same distance or farther is too - a detour around faults, and the packet can still move.
- **S6** - **Dense.** The ranks produced on reachable words are exactly 0..10, no gaps.

**They fix every cell.** Each of the 1,500 single-cell changes to the table below - every reachable word,
every other value in 0..15 - breaks at least one principle, checked by enumeration
(`judge.py --selftest`). The table is the principles' consequence, not a choice beside them.

### Truth table - all 256 values

Row `r`, column `c` is `x = 16r + c`. `.` is unreachable.

```
x=  0..15    0  1  0  4  0  .  0  .  .  2  .  5  .  .  .  .
x= 16..31    .  0  .  0  .  .  .  .  .  .  .  .  .  .  .  .
x= 32..47    0  2  0  5  0  .  0  .  .  3  .  6  .  .  .  .
x= 48..63    .  0  .  0  .  .  .  .  .  .  .  .  .  .  .  .
x= 64..79    0  0  0  0  0  0  .  .  .  0  .  0  .  0  .  .
x= 80..95    .  0  .  0  .  0  .  .  .  .  .  .  .  .  .  .
x= 96..111   0  0  0  0  0  0  .  .  .  0  .  0  .  0  .  .
x=112..127   .  0  .  0  .  0  .  .  .  .  .  .  .  .  .  .
x=128..143   0  0  0  0  0  7  0 10  .  0  .  0  .  8  . 10
x=144..159   .  0  .  0  .  0  . 10  .  .  .  .  .  .  .  .
x=160..175   0  0  0  0  0  8  0 10  .  0  .  0  .  9  . 10
x=176..191   .  0  .  0  .  0  . 10  .  .  .  .  .  .  .  .
x=192..207   0  0  0  0  0  0  .  .  .  0  .  0  .  0  .  .
x=208..223   .  0  .  0  .  0  .  .  .  .  .  .  .  .  .  .
x=224..239   0  0  0  0  0  0  .  .  .  0  .  0  .  0  .  .
x=240..255   .  0  .  0  .  0  .  .  .  .  .  .  .  .  .  .
```

(Reachable: 0 82, 10 6, 2 2, 5 2, 8 2, 1 1, 3 1, 4 1, 6 1, 7 1, 9 1.)

Anchors, so the table can be read against reality - every shape-dependent bit is computed from the real shape
(`anchors.py`):

| situation | x | step |
|---|---|---|
| 600-cell, at the antipode of the destination (5 hops): all 12 neighbours are nearer; this one has room and a quiet link | 173 | **9**  |
| the same neighbour, full - the packet takes one of the other 11 nearer links | 181 | **0**  |
| 8-cell, one hop from the destination, which is down - its only nearer neighbour (c_1 = 1) | 38 | **0**  |
| the same node: a farther neighbour, live with room - the detour (the 8-cell has no level neighbours, a_i = 0, so the detour is farther) | 41 | **3**  |
| 24-cell, two hops away at 90 degrees (4 nearer neighbours; at 120 degrees there would be 1): a nearer one with room, link busy last tick | 141 | **8**  |
| the same node: a level neighbour with room and a quiet link - 0, the nearer ones are live | 171 | **0**  |
| 16-cell, at the destination's antipode (all 6 neighbours nearer): one the packet already visited | 237 | **0**  |
| 120-cell, 15 hops from the destination at its antipode: all 4 neighbours nearer (c_15 = 4) | 173 | **9**  |
| 8-cell, the neighbour IS the destination and reports full - 10, the destination consumes | 183 | **10**  |

## Judged before asking - replayed on every shape

The table, replayed by `replay.py` with no load (every live neighbour has room, every link quiet; ties to the
lowest index) and dead nodes up to links-per-node minus one - the most any shape is guaranteed to survive
connected. A packet with every rank 0 counts as lost.

| shape | dead nodes | delivered | mean stretch | |
|---|---|---|---|---|
| 5-cell | 0 | 20 / 20 = 100.00% | 1.000 | every fault set, every pair |
| 5-cell | 1 | 60 / 60 = 100.00% | 1.000 | every fault set, every pair |
| 5-cell | 3 | 20 / 20 = 100.00% | 1.000 | every fault set, every pair |
| 8-cell | 0 | 240 / 240 = 100.00% | 1.000 | every fault set, every pair |
| 8-cell | 1 | 3,360 / 3,360 = 100.00% | 1.000 | every fault set, every pair |
| 8-cell | 3 | 87,248 / 87,360 = 99.87% | 1.007 | every fault set, every pair |
| 16-cell | 0 | 56 / 56 = 100.00% | 1.000 | every fault set, every pair |
| 16-cell | 1 | 336 / 336 = 100.00% | 1.000 | every fault set, every pair |
| 16-cell | 5 | 336 / 336 = 100.00% | 1.000 | every fault set, every pair |
| 24-cell | 0 | 552 / 552 = 100.00% | 1.000 | every fault set, every pair |
| 24-cell | 1 | 12,144 / 12,144 = 100.00% | 1.001 | every fault set, every pair |
| 24-cell | 7 | 1,087,903 / 1,088,000 = 99.99% | 1.012 | sampled, seeded |
| 120-cell | 0 | 400 / 400 = 100.00% | 1.000 | sampled, seeded |
| 120-cell | 1 | 24,000 / 24,000 = 100.00% | 1.001 | sampled, seeded |
| 120-cell | 3 | 24,000 / 24,000 = 100.00% | 1.002 | sampled, seeded |
| 600-cell | 0 | 400 / 400 = 100.00% | 1.000 | sampled, seeded |
| 600-cell | 1 | 24,000 / 24,000 = 100.00% | 1.001 | sampled, seeded |
| 600-cell | 11 | 24,000 / 24,000 = 100.00% | 1.012 | sampled, seeded |

The load lane is constant here; this measures the veto, `AHEAD`, the detour and the `VISITED` record alone.
Load is judged in the swarm, not here.

---

## Constraints

- **Branchless integer arithmetic over `x`.** No conditionals, no lookup table - the same character as the
  existing laws: lanes of shifts and masks, counted, then ranked.
- Shifts, masks, adds, subtracts, and popcount and `ntzb` if your engine has them. Fewer operations is better.
- **Total** on 0..255 and **exact** on every reachable word. The judge compiles the file **on its own**
  (`cc -O2 -shared`), so define every helper it uses - popcount, `ntzb` - in the file itself, the way the
  existing laws define their lanes. A `main()` that checks itself is welcome and is not run by the judge.
- Signature: `int32_t step(int32_t x)`; or a Python port, `def step(x)`.

## How it will be judged

```
.venv/bin/python judge.py step laws/step.c
```

1. **Exhaustively against the table**, all 100 reachable `x`, and the range on all 256.
2. **Every principle re-checked by enumeration on the kernel itself**, not only through the table -
   S0, S1, S2, S3, S4, S5, S6.
3. **The anchors.**

Zero violations or it is not the law.

**What the superoptimizer does not decide:** Whether waiting for a full nearer neighbour beats deflecting under heavy load, and the queue threshold behind `ROOM`. Both are measured in the swarm; the table follows from its principles.
