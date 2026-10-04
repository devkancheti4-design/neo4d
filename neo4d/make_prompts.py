"""Render prompts/*_LAW_PROMPT.md - one superoptimizer task per law - from laws.py, anchors.py, polytopes.py
and replay.py. Nothing in a prompt is typed by hand that can be computed: the tables, the counts, the shape
facts and the replays are all measured when this runs.

    python3 make_prompts.py
"""
from __future__ import annotations

import os
from collections import Counter

from neo4d import anchors
from neo4d import laws as L
from neo4d import polytopes as P
from neo4d import replay

OUT = str(ROOT / "prompts")

INTRO = """The swarm lives on a regular 4D polytope: every vertex is a node, every edge a link, and data flows
node to node along the links. The shape is the advantage - every node is identical (the polytopes are
vertex-transitive), many pairs have more than one shortest route, and every node has as many
node-disjoint routes to any other as it has links (all measured, by `polytopes.py`).

The rule of this repository: **the law decides and the body only measures.** The body turns what it measured
about one decision into one byte, the situation word. The law turns that byte into the decision. No weights,
no `if`s in the law, no number that is a guess."""

CONSTRAINTS = """## Constraints

- **Branchless integer arithmetic over `x`.** No conditionals, no lookup table - the same character as the
  existing laws: lanes of shifts and masks, counted, then ranked.
- Shifts, masks, adds, subtracts, and popcount and `ntzb` if your engine has them. Fewer operations is better.
- **Total** on 0..255 and **exact** on every reachable word. The judge compiles the file **on its own**
  (`cc -O2 -shared`), so define every helper it uses - popcount, `ntzb` - in the file itself, the way the
  existing laws define their lanes. A `main()` that checks itself is welcome and is not run by the judge.
- Signature: `int32_t {name}(int32_t x)`; or a Python port, `def {name}(x)`."""


def table(law: L.Law) -> str:
    w = max(len(str(law.oracle(x))) for x in law.reach()) + 1
    lines = []
    for r in range(16):
        cells = []
        for c in range(16):
            x = 16 * r + c
            cells.append((str(law.oracle(x)) if law.reachable(x) else ".").rjust(w))
        lines.append(f"x={16*r:3}..{16*r+15:<3} {''.join(cells)}")
    return "\n".join(lines)


def counts(law: L.Law) -> str:
    c = Counter(law.verdict_name(law.oracle(x)) for x in law.reach())
    return ", ".join(f"{k} {v}" for k, v in sorted(c.items(), key=lambda kv: (-kv[1], kv[0])))


def facts_table(names) -> str:
    rows = ["| shape | nodes | links each | diameter | node-disjoint routes | pairs with a choice of nearer neighbour | nearer neighbours at distance 1, 2, ... (every value seen) |",
            "|---|---|---|---|---|---|---|"]
    for n in names:
        f = P.measure(anchors.shape(n))
        near = ", ".join("/".join(map(str, c)) for c in f.closer[1:])
        ch, tot = f.choice_pairs
        rows.append(f"| {n} | {f.V} | {f.degree} | {f.diameter} | {f.connectivity} | {100*ch/tot:.0f}% | {near} |")
    return "\n".join(rows)


def shape_section(law: L.Law) -> str:
    if law.name == "hop":
        f = P.measure(anchors.shape("8-cell"))
        return f"""## What the shape supplies

Measured on the 8-cell (`polytopes.py`):

- **The node id is the address.** Number the 16 vertices by their sign pattern; two nodes are linked **exactly**
  when their ids differ in one bit, and their distance is **exactly** `popcount(a XOR b)` - checked on all 256
  pairs. So `here XOR destination` is the whole routing state, and link k flips bit k.
- At distance i there are exactly i nearer neighbours (c = {[c[0] for c in f.closer]}): a packet always has a
  choice of how to get closer, except on its last hop.
- {f.geodesics_to_far} shortest routes from any node to its antipode; {f.connectivity} node-disjoint routes between any two
  nodes - any {f.connectivity - 1} dead nodes leave the swarm connected.

No other shape has this: on the rest, routing needs a distance table (the STEP law). Here it needs one XOR."""
    if law.name == "quorum":
        f = P.measure(anchors.shape("5-cell"))
        return f"""## What the shape supplies

Measured on the 5-cell (`polytopes.py`): {f.V} nodes, {f.degree} links each, diameter **{f.diameter}** - every node
is linked to every other, the only regular 4D polytope where that holds. A vote broadcast once reaches every
peer in one hop, so a proposal is decided in **one round**, with no relays and no leader. The symmetry group of
the 5-cell is every permutation of its five vertices, so the four peers of a node are interchangeable (Q5)."""
    if law.name == "step":
        return f"""## What the shape supplies

The law is the same on every shape; what changes is how many **nearer** neighbours a packet sees - the choices
the load lane gets to balance across. Measured (`polytopes.py`; where a shape is not distance-regular the count
depends on the angle to the destination, and every value seen is listed):

{facts_table(P.BUILDERS)}

On every shape, **node-disjoint routes = links per node**: no small set of failures can cut the swarm. And
every node has the same distance profile, so one law serves every node."""
    if law.name == "admit":
        return """## What the shape supplies

Every regular polytope is vertex-transitive: any node can be moved onto any other by a symmetry of the shape.
So no node is a hub, no node is a leaf, and one admission law serves every node unchanged - there is no
special case for the centre or the edge, because there is no centre or edge."""
    if law.name == "mirror":
        rows = ["| shape | hops home to mirror (= diameter) | unique farthest node | mirror's neighbours disjoint from home's |",
                "|---|---|---|---|"]
        for n in ("8-cell", "16-cell", "24-cell", "120-cell", "600-cell"):
            f = P.measure(anchors.shape(n))
            rows.append(f"| {n} | {f.diameter} | {f.antipode_at_diameter} | {f.antipode_nbhd_disjoint} |")
        return f"""## What the shape supplies

Each of these shapes is centrally symmetric: for every node `v`, `-v` is a node too. Measured (`polytopes.py`):

{chr(10).join(rows)}

The mirror is the one node farthest from the home, and never its neighbour. An outage confined to the home and
its neighbours never touches the mirror; on four of the five shapes it does not even touch the mirror's
neighbours, so the mirror keeps every one of its links. The 16-cell is the exception: home and mirror share all
six neighbours (they are the only unlinked pair), so the mirror survives the outage but is cut off by it."""
    if law.name == "carry":
        st, sh, runs_v, hops_v = _carry_measure()
        return f"""## What the shape supplies

fluidnet as built never lets a net hand anything on: each net starts from the original code and the first
green wins. So a job whose faults need taught classes from two different nets is refused, though the swarm
holds both answers. On the polytope a job travels, and what it carries is this law's decision. Measured
here on the 8-cell, 30 jobs whose two taught faults live in two different dictionaries (plus one shipped
fault), every law at its reference table:

| | repaired |
|---|---|
| fluidnet as built (overseer, each net alone) | {st}/30 |
| on the 8-cell, partial repairs carried | {sh}/30 |

Acceptance did not loosen to get there: the only state ever accepted is green, no step in it was refuted by
its class property, and under `STRICT` every step must be proven - a class with no property (all nine
shipped ones) is UNPROVEN, which fluidfix lets pass and `STRICT` does not."""
    if law.name == "seek":
        st, sh, runs_v, hops_v = _carry_measure()
        return f"""## What the shape supplies

The swarm knows every dictionary's signals (they are small) but each dictionary's appliers and properties
live only on its home node and its antipode. So the edge can see which nets the code calls for, and the
shape decides what reaching them costs. Measured on the same 8-cell jobs: a visit costs
**{runs_v:.1f} suite runs**, a hop costs **one message** ({hops_v:.1f} hops per visit). That is the whole
reason evidence outranks distance here. `NEAR` is banded against the shape's own diameter, so one law
serves the 16-cell (diameter 2) and the 120-cell (diameter 15) unchanged."""
    return ""


_CM = None


def _carry_measure():
    """30 two-dictionary jobs on the 8-cell: static vs shape, and the cost of a visit against a hop."""
    global _CM
    if _CM is None:
        import random
        from neo4d import classes as C
        from neo4d import jobs as J
        from neo4d import swarm as S
        g = S.polytope("8-cell")
        taught, shipped = C.taught(S.capacity(g, True)), C.shipped()
        pl = S.place(g, taught, g.partner)
        by = {c.name: c for c in shipped + taught}
        rng = random.Random(2026)
        st = sh = runs = nets = hops = 0
        for _ in range(30):
            ds = rng.sample(range(len(pl.dictionaries)), 2)
            job = J.make_job([rng.choice(pl.dictionaries[d]).name for d in ds] + ["flipped-boolean"],
                             ["strictness"], rng, by)
            st += S.static(job, pl, shipped).repaired
            r = S.shape(job, g, pl, shipped, entry=rng.randrange(g.V))
            sh += r.repaired
            runs += r.runs; nets += r.nets; hops += r.hops
        _CM = (st, sh, runs / nets, hops / nets)
    return _CM


def replay_section(law: L.Law) -> str:
    if law.name == "hop":
        t = anchors.shape("8-cell")
        rows = ["| dead nodes | delivered | mean stretch (hops / shortest live route) |", "|---|---|---|"]
        res = []
        for f in range(4):
            ok, n, st, _ = replay.measure(t, lambda dead, s, tt: replay.route_hop(L.HOP.oracle, dead, s, tt), f,
                                          cap_sets=10**6, cap_pairs=10**6)
            res.append((ok, n))
            rows.append(f"| {f} | {ok:,} / {n:,} = {100*ok/n:.2f}% | {st:.3f} |")
        clean = max(f for f in range(4) if all(o == n for o, n in res[:f + 1]))
        lost3, n3 = res[3][1] - res[3][0], res[3][1]
        return f"""## Judged before asking - replayed on the 8-cell

The table, replayed by `replay.py` on the real 8-cell with dead nodes (all links of a dead node dead): every set
of that many dead nodes, every pair of live nodes still connected, no traffic. A packet that HOLDs or runs past
16 hops counts as lost.

{chr(10).join(rows)}

Every route is minimal with no faults. Up to {clean} dead nodes, every packet arrives. With three, {lost3:,} of
{n3:,} connected pairs are lost - the table's one weakness, and it is the body's anti-bounce rule (a detour's
arrival link is DEAD), not the table, that would change if it matters."""
    if law.name == "step":
        rows = ["| shape | dead nodes | delivered | mean stretch | |", "|---|---|---|---|---|"]
        for n in P.BUILDERS:
            sh = anchors.shape(n)
            deg = len(sh.adj[0])
            small = sh.V <= 24
            for f in sorted({0, 1, deg - 1}):
                ok, tot, st, ex = replay.measure(sh, lambda dead, s, tt: replay.route_step(sh, L.STEP.oracle, dead, s, tt), f,
                                                 cap_sets=4000 if small else 60, cap_pairs=10**6 if small else 400)
                rows.append(f"| {n} | {f} | {ok:,} / {tot:,} = {100*ok/tot:.2f}% | {st:.3f} | "
                            f"{'every fault set, every pair' if ex else 'sampled, seeded'} |")
        return f"""## Judged before asking - replayed on every shape

The table, replayed by `replay.py` with no load (every live neighbour has room, every link quiet; ties to the
lowest index) and dead nodes up to links-per-node minus one - the most any shape is guaranteed to survive
connected. A packet with every rank 0 counts as lost.

{chr(10).join(rows)}

The load lane is constant here; this measures the veto, `AHEAD`, the detour and the `VISITED` record alone.
Load is judged in the swarm, not here."""
    return ""


def must_not(law: L.Law) -> str:
    return {
        "hop": "Do not route by a table of next hops - the address is the table. Do not choose a link by load or by "
               "a guess: HOP is the fixed, deadlock-free router; adaptive choice is the STEP law's job. Do not detour "
               "while any differing link is live.",
        "quorum": "Do not count a peer that has not answered as either vote. Do not add a timeout to the law - waiting "
                  "is always safe, deciding on silence is not. Do not weight peers: they are interchangeable.",
        "step": "Do not weight the lanes: progress is ranked before load, and load is counted. Do not let a packet "
                "wander sideways because the way ahead is busy - it waits. Do not let `ROOM` or `FULL` speak when "
                "there was no heartbeat.",
        "admit": "Do not drop live traffic silently when the queue is full - bounce it while the retry budget lasts. "
                 "Do not deliver twice. Do not let `SPENT` change anything but BOUNCE.",
        "mirror": "Do not serve a stale copy, however near. Do not acknowledge a write below the key's durability. "
                  "Do not start a second repair while one is in flight.",
        "carry": "Do not ship partial progress - ever. Do not carry an edit that broke a passing test. Do not "
                 "treat a flaky green as green. Do not loosen acceptance to make travel pay.",
        "seek": "Do not visit a net because it is near when another sees more of the code. Do not weight evidence "
                "against distance - evidence first, then distance, counted in bands. Do not send a job to a net "
                "that cannot be certified under the job's policy.",
    }[law.name]


def not_decided(law: L.Law) -> str:
    return {
        "hop": "Whether dimension order is the best fixed order under heavy load, and whether three-fault loss is "
               "worth a longer anti-bounce memory. Both are measured in the running swarm; if they say so, the "
               "body's measurement changes - never the table.",
        "quorum": "Liveness when fewer than three matching votes ever arrive: the law WAITs forever, which is safe. "
                  "Re-running the round is the body's job, and it never decides.",
        "step": "Whether waiting for a full nearer neighbour beats deflecting under heavy load, and the queue "
                "threshold behind `ROOM`. Both are measured in the swarm; the table follows from its principles.",
        "admit": "The queue thresholds behind `Q`, the hop budget and the retry budget. Measured in the swarm.",
        "mirror": "Whether antipodal placement beats any other placement under correlated failure - measured in the "
                  "swarm against random placement - and the ordering of a repair against a concurrent write "
                  "(the body copies only a strictly newer version).",
        "carry": "The visit budget behind `SPENT`, and whether a second recheck would rescue real work from a flaky "
                 "suite. Both are measured in the swarm (`experiment.py`); the table follows from its principles.",
        "seek": "Whether line counts are the right measure of evidence (against, say, failing tests a class could "
                "touch), and the band edges. Measured in the swarm; if they change, the body's measurement changes.",
    }[law.name]


def render(law: L.Law) -> str:
    R = law.reach()
    n_cells = len(R) * law.range_hi
    bits = "\n".join(f"| {b} | `{name}` | {when} |" for b, name, when in law.bits)
    outs = "\n".join(f"   {v:<14} {m}" for v, m in law.outputs)
    princ = "\n".join(f"- **{p.id}** - {p.statement}" for p in law.principles)
    unreach = "\n".join(f"- {u}" for u in law.unreachable_rules)
    anch = "\n".join(f"| {s} | {x} | **{law.oracle(x)}** {law.verdict_name(law.oracle(x)) if law.verdict_name(law.oracle(x)) != str(law.oracle(x)) else ''} |"
                     for x, s in law.anchors)
    sections = [
        f"# Superoptimizer task - {law.title}",
        f"**Shape:** {law.shapes}.  \n**Decides:** {law.question}",
        "---",
        INTRO,
        shape_section(law),
        "## What must not be done\n\n" + must_not(law),
        "---",
        f"""## The measurement the body will supply

Eight bits. Every one is measured mechanically; none is a judgement.

| bit | name | set when |
|---|---|---|
{bits}

**Situation word:** `{law.word}`

**Unreachable, so the law may return anything there (but must still land in 0..{law.range_hi}):**
{unreach}

That leaves **{len(R)} reachable values of 256.**""",
        "---",
        f"""## The law to find

```
{law.name}(x) -> 0..{law.range_hi}
{outs}
```

### The principles that fix the table

{princ}

**They fix every cell.** Each of the {n_cells:,} single-cell changes to the table below - every reachable word,
every other value in 0..{law.range_hi} - breaks at least one principle, checked by enumeration
(`judge.py --selftest`). The table is the principles' consequence, not a choice beside them.

### Truth table - all 256 values

Row `r`, column `c` is `x = 16r + c`. `.` is unreachable.

```
{table(law)}
```

(Reachable: {counts(law)}.)

Anchors, so the table can be read against reality - every shape-dependent bit is computed from the real shape
(`anchors.py`):

| situation | x | {law.name} |
|---|---|---|
{anch}""",
        replay_section(law),
        "---",
        CONSTRAINTS.format(name=law.name),
        f"""## How it will be judged

```
.venv/bin/python judge.py {law.name} laws/{law.name}.c
```

1. **Exhaustively against the table**, all {len(R)} reachable `x`, and the range on all 256.
2. **Every principle re-checked by enumeration on the kernel itself**, not only through the table -
   {", ".join(p.id for p in law.principles)}.
3. **The anchors.**

Zero violations or it is not the law.

**What the superoptimizer does not decide:** {not_decided(law)}""",
    ]
    return "\n\n".join(s for s in sections if s) + "\n"


def main() -> int:
    anchors.attach()
    os.makedirs(OUT, exist_ok=True)
    for law in L.LAWS.values():
        p = os.path.join(OUT, f"{law.name.upper()}_LAW_PROMPT.md")
        with open(p, "w") as fh:
            fh.write(render(law))
        print(f"  wrote {os.path.relpath(p)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
