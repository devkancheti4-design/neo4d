# Superoptimizer task - the MIRROR law

**Shape:** the centrally symmetric shapes - 8-, 16-, 24-, 120- and 600-cell (the 5-cell has no antipodes).  
**Decides:** Where ONE read or write of ONE key goes, and whether it starts a repair - decided from eight measured bits and nothing else. Every key lives on its home node and on the home's antipode, the mirror.

---

The swarm lives on a regular 4D polytope: every vertex is a node, every edge a link, and data flows
node to node along the links. The shape is the advantage - every node is identical (the polytopes are
vertex-transitive), many pairs have more than one shortest route, and every node has as many
node-disjoint routes to any other as it has links (all measured, by `polytopes.py`).

The rule of this repository: **the law decides and the body only measures.** The body turns what it measured
about one decision into one byte, the situation word. The law turns that byte into the decision. No weights,
no `if`s in the law, no number that is a guess.

## What the shape supplies

Each of these shapes is centrally symmetric: for every node `v`, `-v` is a node too. Measured (`polytopes.py`):

| shape | hops home to mirror (= diameter) | unique farthest node | mirror's neighbours disjoint from home's |
|---|---|---|---|
| 8-cell | 4 | True | True |
| 16-cell | 2 | True | False |
| 24-cell | 3 | True | True |
| 120-cell | 15 | True | True |
| 600-cell | 5 | True | True |

The mirror is the one node farthest from the home, and never its neighbour. An outage confined to the home and
its neighbours never touches the mirror; on four of the five shapes it does not even touch the mirror's
neighbours, so the mirror keeps every one of its links. The 16-cell is the exception: home and mirror share all
six neighbours (they are the only unlinked pair), so the mirror survives the outage but is cut off by it.

## What must not be done

Do not serve a stale copy, however near. Do not acknowledge a write below the key's durability. Do not start a second repair while one is in flight.

---

## The measurement the body will supply

Eight bits. Every one is measured mechanically; none is a judgement.

| bit | name | set when |
|---|---|---|
| 0 | `HOME_UP` | the key's home node answered |
| 1 | `MIRROR_UP` | its mirror - the home's antipode - answered |
| 2 | `HOME_CUR` | the home holds the version of the key's last acknowledged write (from the key's write log; a key never written is current everywhere) |
| 3 | `MIRROR_CUR` | the mirror does |
| 4 | `NEAR_MIRROR` | the requester is strictly fewer hops from the mirror than from the home |
| 5 | `WRITE` | the operation is a write (else a read) |
| 6 | `REPAIRING` | a repair of this key is already in flight |
| 7 | `ONE_OK` | the key's policy allows acknowledging a write held by one copy |

**Situation word:** `x = HOME_UP | MIRROR_UP << 1 | HOME_CUR << 2 | MIRROR_CUR << 3 | NEAR_MIRROR << 4 | WRITE << 5 | REPAIRING << 6 | ONE_OK << 7`

**Unreachable, so the law may return anything there (but must still land in 0..7):**
- `HOME_CUR` without `HOME_UP`, or `MIRROR_CUR` without `MIRROR_UP` - a node that did not answer has no measured version; the lane is silent.
- Both up and neither current - every acknowledged write is held by at least one copy, and storage is durable, so when both answer at least one holds the last acknowledged version.

That leaves **128 reachable values of 256.**

---

## The law to find

```
mirror(x) -> 0..7
   bits 0-1 = 0   NONE - refuse (unavailable, never wrong)
   bits 0-1 = 1   HOME
   bits 0-1 = 2   MIRROR
   bits 0-1 = 3   BOTH (writes only)
   bit 2          REPAIR - copy the current copy over the stale one
```

### The principles that fix the table

- **M0** - **Never serve stale.** A read goes to exactly one copy, and only to one that is up AND current - or to none.
- **M1** - **Never refuse while a current copy is up.** A read with an up, current copy has a target.
- **M2** - **The nearer current copy; ties go home.** Both up and current: the mirror if `NEAR_MIRROR`, else the home.
- **M3** - **Writes go to every live copy.** A write with both copies up: BOTH - which overwrites a stale copy with no repair needed.
- **M4** - **One live copy: only if the key allows it.** A write with exactly one copy up goes to that copy if `ONE_OK`, else to NONE - never acknowledge a write below the key's durability. Neither up: NONE.
- **M5** - **Repair heals, once.** REPAIR is set exactly when the operation is a read, no repair is in flight, and one copy is up and current while the other is up and stale. A write never sets it: BOTH overwrites the stale copy itself, and a write to one copy has no live stale copy to repair.
- **M6** - **Never a down copy.** No target includes a copy that did not answer.

**They fix every cell.** Each of the 896 single-cell changes to the table below - every reachable word,
every other value in 0..7 - breaks at least one principle, checked by enumeration
(`judge.py --selftest`). The table is the principles' consequence, not a choice beside them.

### Truth table - all 256 values

Row `r`, column `c` is `x = 16r + c`. `.` is unreachable.

```
x=  0..15   0 0 0 . . 1 . 5 . . 2 6 . . . 1
x= 16..31   0 0 0 . . 1 . 5 . . 2 6 . . . 2
x= 32..47   0 0 0 . . 0 . 3 . . 0 3 . . . 3
x= 48..63   0 0 0 . . 0 . 3 . . 0 3 . . . 3
x= 64..79   0 0 0 . . 1 . 1 . . 2 2 . . . 1
x= 80..95   0 0 0 . . 1 . 1 . . 2 2 . . . 2
x= 96..111  0 0 0 . . 0 . 3 . . 0 3 . . . 3
x=112..127  0 0 0 . . 0 . 3 . . 0 3 . . . 3
x=128..143  0 0 0 . . 1 . 5 . . 2 6 . . . 1
x=144..159  0 0 0 . . 1 . 5 . . 2 6 . . . 2
x=160..175  0 1 2 . . 1 . 3 . . 2 3 . . . 3
x=176..191  0 1 2 . . 1 . 3 . . 2 3 . . . 3
x=192..207  0 0 0 . . 1 . 1 . . 2 2 . . . 1
x=208..223  0 0 0 . . 1 . 1 . . 2 2 . . . 2
x=224..239  0 1 2 . . 1 . 3 . . 2 3 . . . 3
x=240..255  0 1 2 . . 1 . 3 . . 2 3 . . . 3
```

(Reachable: NONE 48, BOTH 24, HOME 24, MIRROR 24, HOME+R 4, MIRROR+R 4.)

Anchors, so the table can be read against reality - every shape-dependent bit is computed from the real shape
(`anchors.py`):

| situation | x | mirror |
|---|---|---|
| 8-cell: home `0000`, mirror `1111`, read from `0111` - 3 hops to the home, 1 to the mirror | 31 | **2** MIRROR |
| 16-cell: every other node is one hop from both copies - ties, so the home | 15 | **1** HOME |
| 24-cell: a reader 2 hops from the home at 120 degrees is 1 hop from the mirror (at 90 degrees it would be 2 and 2 - hops to the copies need not sum to the diameter) | 31 | **2** MIRROR |
| 600-cell: the home and all 12 of its neighbours are down - the mirror and all 12 of its neighbours are untouched | 10 | **2** MIRROR |
| a write during that outage, key needs two copies | 42 | **0** NONE |
| the same write, key allows one copy | 170 | **2** MIRROR |
| the home is back, stale (it missed that write) - serve the mirror, repair the home | 11 | **6** MIRROR+R |
| the same read with that repair already in flight | 75 | **2** MIRROR |

---

## Constraints

- **Branchless integer arithmetic over `x`.** No conditionals, no lookup table - the same character as the
  existing laws: lanes of shifts and masks, counted, then ranked.
- Shifts, masks, adds, subtracts, and popcount and `ntzb` if your engine has them. Fewer operations is better.
- **Total** on 0..255 and **exact** on every reachable word. The judge compiles the file **on its own**
  (`cc -O2 -shared`), so define every helper it uses - popcount, `ntzb` - in the file itself, the way the
  existing laws define their lanes. A `main()` that checks itself is welcome and is not run by the judge.
- Signature: `int32_t mirror(int32_t x)`; or a Python port, `def mirror(x)`.

## How it will be judged

```
.venv/bin/python judge.py mirror laws/mirror.c
```

1. **Exhaustively against the table**, all 128 reachable `x`, and the range on all 256.
2. **Every principle re-checked by enumeration on the kernel itself**, not only through the table -
   M0, M1, M2, M3, M4, M5, M6.
3. **The anchors.**

Zero violations or it is not the law.

**What the superoptimizer does not decide:** Whether antipodal placement beats any other placement under correlated failure - measured in the swarm against random placement - and the ordering of a repair against a concurrent write (the body copies only a strictly newer version).
