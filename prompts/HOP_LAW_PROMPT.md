# Superoptimizer task - the HOP law

**Shape:** 8-cell (the tesseract) only.  
**Decides:** Which of this node's four links a packet crosses next - decided for ONE packet at ONE node, from eight measured bits and nothing else.

---

The swarm lives on a regular 4D polytope: every vertex is a node, every edge a link, and data flows
node to node along the links. The shape is the advantage - every node is identical (the polytopes are
vertex-transitive), many pairs have more than one shortest route, and every node has as many
node-disjoint routes to any other as it has links (all measured, by `polytopes.py`).

The rule of this repository: **the law decides and the body only measures.** The body turns what it measured
about one decision into one byte, the situation word. The law turns that byte into the decision. No weights,
no `if`s in the law, no number that is a guess.

## What the shape supplies

Measured on the 8-cell (`polytopes.py`):

- **The node id is the address.** Number the 16 vertices by their sign pattern; two nodes are linked **exactly**
  when their ids differ in one bit, and their distance is **exactly** `popcount(a XOR b)` - checked on all 256
  pairs. So `here XOR destination` is the whole routing state, and link k flips bit k.
- At distance i there are exactly i nearer neighbours (c = [0, 1, 2, 3, 4]): a packet always has a
  choice of how to get closer, except on its last hop.
- 24 shortest routes from any node to its antipode; 4 node-disjoint routes between any two
  nodes - any 3 dead nodes leave the swarm connected.

No other shape has this: on the rest, routing needs a distance table (the STEP law). Here it needs one XOR.

## What must not be done

Do not route by a table of next hops - the address is the table. Do not choose a link by load or by a guess: HOP is the fixed, deadlock-free router; adaptive choice is the STEP law's job. Do not detour while any differing link is live.

---

## The measurement the body will supply

Eight bits. Every one is measured mechanically; none is a judgement.

| bit | name | set when |
|---|---|---|
| 0 | `DIFF0` | the destination's address differs from this node's in bit 0 - it lies across link 0 |
| 1 | `DIFF1` | ... in bit 1 - across link 1 |
| 2 | `DIFF2` | ... in bit 2 - across link 2 |
| 3 | `DIFF3` | ... in bit 3 - across link 3 |
| 4 | `DEAD0` | link 0 cannot be used: it missed its heartbeat, or it is the link this packet arrived on by a DETOUR (so a detour is never undone on the next hop) |
| 5 | `DEAD1` | the same, link 1 |
| 6 | `DEAD2` | the same, link 2 |
| 7 | `DEAD3` | the same, link 3 |

**Situation word:** `x = (here XOR destination) | DEAD << 4`

**Unreachable, so the law may return anything there (but must still land in 0..15):**
- None. Every combination of differing bits and dead links occurs.

That leaves **256 reachable values of 256.**

---

## The law to find

```
hop(x) -> 0..15
   0..3           FORWARD across link d - one hop nearer
   4..7           DETOUR across link d - 4 - one hop farther, only way on
   8              DELIVER - this node is the destination
   12             HOLD - keep the packet this tick, nothing is live
   9-11, 13-15    never produced
```

### The principles that fix the table

- **H0** - **Arrived.** `DIFF = 0`: DELIVER (8), whatever `DEAD` says.
- **H1** - **Minimal while possible.** Some differing link is live: FORWARD across a live differing link - the hop that lowers the distance (popcount of `DIFF`) by exactly one.
- **H2** - **Dimension order.** Of the live differing links, the LOWEST. On a whole cube this is e-cube routing: every route is minimal and every packet crosses dimensions in ascending order, so channel dependencies only ascend and routes cannot deadlock.
- **H3** - **Detour only when blocked.** Every differing link is dead but a non-differing link is live: DETOUR (4 + d) across the lowest live non-differing link. It costs two hops (out, and back across the same dimension later) and is the only way forward.
- **H4** - **Nothing live, hold.** `DIFF != 0` and every link dead: HOLD (12).
- **H5** - **Never across a dead link.** A FORWARD or DETOUR names a live link.
- **H6** - **Kinds are what they say.** FORWARD only across a differing link, DETOUR only across a non-differing one, DETOUR never while a differing link is live, DELIVER only at `DIFF = 0`, HOLD only when nothing is live.

**They fix every cell.** Each of the 3,840 single-cell changes to the table below - every reachable word,
every other value in 0..15 - breaks at least one principle, checked by enumeration
(`judge.py --selftest`). The table is the principles' consequence, not a choice beside them.

### Truth table - all 256 values

Row `r`, column `c` is `x = 16r + c`. `.` is unreachable.

```
x=  0..15    8  0  1  0  2  0  1  0  3  0  1  0  2  0  1  0
x= 16..31    8  5  1  1  2  2  1  1  3  3  1  1  2  2  1  1
x= 32..47    8  0  4  0  2  0  2  0  3  0  3  0  2  0  2  0
x= 48..63    8  6  6  6  2  2  2  2  3  3  3  3  2  2  2  2
x= 64..79    8  0  1  0  4  0  1  0  3  0  1  0  3  0  1  0
x= 80..95    8  5  1  1  5  5  1  1  3  3  1  1  3  3  1  1
x= 96..111   8  0  4  0  4  0  4  0  3  0  3  0  3  0  3  0
x=112..127   8  7  7  7  7  7  7  7  3  3  3  3  3  3  3  3
x=128..143   8  0  1  0  2  0  1  0  4  0  1  0  2  0  1  0
x=144..159   8  5  1  1  2  2  1  1  5  5  1  1  2  2  1  1
x=160..175   8  0  4  0  2  0  2  0  4  0  4  0  2  0  2  0
x=176..191   8  6  6  6  2  2  2  2  6  6  6  6  2  2  2  2
x=192..207   8  0  1  0  4  0  1  0  4  0  1  0  4  0  1  0
x=208..223   8  5  1  1  5  5  1  1  5  5  1  1  5  5  1  1
x=224..239   8  0  4  0  4  0  4  0  4  0  4  0  4  0  4  0
x=240..255   8 12 12 12 12 12 12 12 12 12 12 12 12 12 12 12
```

(Reachable: FWD0 64, FWD1 48, FWD2 36, FWD3 27, DET0 19, DELIVER 16, HOLD 15, DET1 14, DET2 10, DET3 7.)

Anchors, so the table can be read against reality - every shape-dependent bit is computed from the real shape
(`anchors.py`):

| situation | x | hop |
|---|---|---|
| node `0000` to its antipode `1111` (4 hops, 24 shortest routes), all links up - lowest dimension first | 15 | **0** FWD0 |
| node `0000` to `1011`, link 0 down - the next live differing dimension, 1 | 27 | **1** FWD1 |
| `0110` to `0111` (one hop), link 0 down - DETOUR across link 1 to `0100` | 17 | **5** DET1 |
| then at `0100`: link 1 is DEAD because the packet arrived on it by a detour - FORWARD across 0 | 35 | **0** FWD0 |
| then at `0101`: FORWARD across 1 to `0111` | 2 | **1** FWD1 |
| then at `0111`: DELIVER - three hops where one link failed | 0 | **8** DELIVER |
| at the destination with every link down - DELIVER still | 240 | **8** DELIVER |
| node `0101` to `1010`, every link down - HOLD | 255 | **12** HOLD |

## Judged before asking - replayed on the 8-cell

The table, replayed by `replay.py` on the real 8-cell with dead nodes (all links of a dead node dead): every set
of that many dead nodes, every pair of live nodes still connected, no traffic. A packet that HOLDs or runs past
16 hops counts as lost.

| dead nodes | delivered | mean stretch (hops / shortest live route) |
|---|---|---|
| 0 | 240 / 240 = 100.00% | 1.000 |
| 1 | 3,360 / 3,360 = 100.00% | 1.000 |
| 2 | 21,840 / 21,840 = 100.00% | 1.002 |
| 3 | 87,248 / 87,360 = 99.87% | 1.007 |

Every route is minimal with no faults. Up to 2 dead nodes, every packet arrives. With three, 112 of
87,360 connected pairs are lost - the table's one weakness, and it is the body's anti-bounce rule (a detour's
arrival link is DEAD), not the table, that would change if it matters.

---

## Constraints

- **Branchless integer arithmetic over `x`.** No conditionals, no lookup table - the same character as the
  existing laws: lanes of shifts and masks, counted, then ranked.
- Shifts, masks, adds, subtracts, and popcount and `ntzb` if your engine has them. Fewer operations is better.
- **Total** on 0..255 and **exact** on every reachable word. The judge compiles the file **on its own**
  (`cc -O2 -shared`), so define every helper it uses - popcount, `ntzb` - in the file itself, the way the
  existing laws define their lanes. A `main()` that checks itself is welcome and is not run by the judge.
- Signature: `int32_t hop(int32_t x)`; or a Python port, `def hop(x)`.

## How it will be judged

```
.venv/bin/python judge.py hop laws/hop.c
```

1. **Exhaustively against the table**, all 256 reachable `x`, and the range on all 256.
2. **Every principle re-checked by enumeration on the kernel itself**, not only through the table -
   H0, H1, H2, H3, H4, H5, H6.
3. **The anchors.**

Zero violations or it is not the law.

**What the superoptimizer does not decide:** Whether dimension order is the best fixed order under heavy load, and whether three-fault loss is worth a longer anti-bounce memory. Both are measured in the running swarm; if they say so, the body's measurement changes - never the table.
