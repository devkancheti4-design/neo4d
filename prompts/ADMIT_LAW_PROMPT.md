# Superoptimizer task - the ADMIT law

**Shape:** every shape.  
**Decides:** What a node does with ONE packet that just arrived - decided from eight measured bits and nothing else.

---

The swarm lives on a regular 4D polytope: every vertex is a node, every edge a link, and data flows
node to node along the links. The shape is the advantage - every node is identical (the polytopes are
vertex-transitive), many pairs have more than one shortest route, and every node has as many
node-disjoint routes to any other as it has links (all measured, by `polytopes.py`).

The rule of this repository: **the law decides and the body only measures.** The body turns what it measured
about one decision into one byte, the situation word. The law turns that byte into the decision. No weights,
no `if`s in the law, no number that is a guess.

## What the shape supplies

Every regular polytope is vertex-transitive: any node can be moved onto any other by a symmetry of the shape.
So no node is a hub, no node is a leaf, and one admission law serves every node unchanged - there is no
special case for the centre or the edge, because there is no centre or edge.

## What must not be done

Do not drop live traffic silently when the queue is full - bounce it while the retry budget lasts. Do not deliver twice. Do not let `SPENT` change anything but BOUNCE.

---

## The measurement the body will supply

Eight bits. Every one is measured mechanically; none is a judgement.

| bit | name | set when |
|---|---|---|
| 0 | `MINE` | this node is the packet's destination |
| 1 | `DUP` | this node already holds, or has delivered, this packet id |
| 2-3 | `Q` | this node's forwarding queue: `0` empty, `1` under half, `2` half or more, `3` full |
| 4 | `LAST_HOP` | the packet's hop budget is spent on arriving here |
| 5 | `COPY` | the packet is the antipodal mirror copy (MIRROR law), not the original |
| 6 | `URGENT` | the packet is marked urgent |
| 7 | `SPENT` | this packet has already been bounced the maximum number of times |

**Situation word:** `x = MINE | DUP << 1 | Q << 2 | LAST_HOP << 4 | COPY << 5 | URGENT << 6 | SPENT << 7`

**Unreachable, so the law may return anything there (but must still land in 0..3):**
- None - every combination occurs.

That leaves **256 reachable values of 256.**

---

## The law to find

```
admit(x) -> 0..3
   0              DROP
   1              ACCEPT - queue it for forwarding
   2              DELIVER - consume it here
   3              BOUNCE - refuse; the sender keeps it and retries
```

### The principles that fix the table

- **A0** - **At most once.** `DUP`: DROP, always - a packet is delivered or forwarded once, however many copies and retries reach a node.
- **A1** - **The destination consumes.** `MINE` and not `DUP`: DELIVER, whatever the queue, the budget and the flags say - delivery does not use the forwarding queue.
- **A2** - **The budget is respected.** Not `MINE` and `LAST_HOP`: DROP - it cannot go further, and holding it would keep a slot forever.
- **A3** - **Backpressure, never silent loss.** Forwardable and the queue is full (`Q = 3`): BOUNCE - the sender keeps it and retries - or DROP once `SPENT`.
- **A4** - **Copies yield first.** Forwardable, a `COPY`, not `URGENT`, queue half or more (`Q = 2`): BOUNCE, or DROP once `SPENT` - the original exists elsewhere; slots go to originals.
- **A5** - **Otherwise ACCEPT.** An original at half or more is accepted; an urgent copy is treated as an original.
- **A6** - **Never DELIVER what is not `MINE`; never ACCEPT into a full queue.**
- **A7** - **`SPENT` only turns BOUNCE into DROP.** Setting it changes no other verdict.

**They fix every cell.** Each of the 768 single-cell changes to the table below - every reachable word,
every other value in 0..3 - breaks at least one principle, checked by enumeration
(`judge.py --selftest`). The table is the principles' consequence, not a choice beside them.

### Truth table - all 256 values

Row `r`, column `c` is `x = 16r + c`. `.` is unreachable.

```
x=  0..15   1 2 0 0 1 2 0 0 1 2 0 0 3 2 0 0
x= 16..31   0 2 0 0 0 2 0 0 0 2 0 0 0 2 0 0
x= 32..47   1 2 0 0 1 2 0 0 3 2 0 0 3 2 0 0
x= 48..63   0 2 0 0 0 2 0 0 0 2 0 0 0 2 0 0
x= 64..79   1 2 0 0 1 2 0 0 1 2 0 0 3 2 0 0
x= 80..95   0 2 0 0 0 2 0 0 0 2 0 0 0 2 0 0
x= 96..111  1 2 0 0 1 2 0 0 1 2 0 0 3 2 0 0
x=112..127  0 2 0 0 0 2 0 0 0 2 0 0 0 2 0 0
x=128..143  1 2 0 0 1 2 0 0 1 2 0 0 0 2 0 0
x=144..159  0 2 0 0 0 2 0 0 0 2 0 0 0 2 0 0
x=160..175  1 2 0 0 1 2 0 0 0 2 0 0 0 2 0 0
x=176..191  0 2 0 0 0 2 0 0 0 2 0 0 0 2 0 0
x=192..207  1 2 0 0 1 2 0 0 1 2 0 0 0 2 0 0
x=208..223  0 2 0 0 0 2 0 0 0 2 0 0 0 2 0 0
x=224..239  1 2 0 0 1 2 0 0 1 2 0 0 0 2 0 0
x=240..255  0 2 0 0 0 2 0 0 0 2 0 0 0 2 0 0
```

(Reachable: DROP 165, DELIVER 64, ACCEPT 22, BOUNCE 5.)

Anchors, so the table can be read against reality - every shape-dependent bit is computed from the real shape
(`anchors.py`):

| situation | x | admit |
|---|---|---|
| arrives at its destination on its last hop, queue full | 29 | **2** DELIVER |
| a retry of a packet already delivered here | 3 | **0** DROP |
| in transit, queue full, first try | 12 | **3** BOUNCE |
| the same, retry budget spent | 140 | **0** DROP |
| an antipodal mirror copy, queue at half | 40 | **3** BOUNCE |
| the same copy, marked urgent | 104 | **1** ACCEPT |
| an original, queue at half | 8 | **1** ACCEPT |
| in transit, hop budget spent | 16 | **0** DROP |

---

## Constraints

- **Branchless integer arithmetic over `x`.** No conditionals, no lookup table - the same character as the
  existing laws: lanes of shifts and masks, counted, then ranked.
- Shifts, masks, adds, subtracts, and popcount and `ntzb` if your engine has them. Fewer operations is better.
- **Total** on 0..255 and **exact** on every reachable word. The judge compiles the file **on its own**
  (`cc -O2 -shared`), so define every helper it uses - popcount, `ntzb` - in the file itself, the way the
  existing laws define their lanes. A `main()` that checks itself is welcome and is not run by the judge.
- Signature: `int32_t admit(int32_t x)`; or a Python port, `def admit(x)`.

## How it will be judged

```
.venv/bin/python judge.py admit laws/admit.c
```

1. **Exhaustively against the table**, all 256 reachable `x`, and the range on all 256.
2. **Every principle re-checked by enumeration on the kernel itself**, not only through the table -
   A0, A1, A2, A3, A4, A5, A6, A7.
3. **The anchors.**

Zero violations or it is not the law.

**What the superoptimizer does not decide:** The queue thresholds behind `Q`, the hop budget and the retry budget. Measured in the swarm.
