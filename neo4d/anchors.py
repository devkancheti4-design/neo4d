"""The anchors - situations on the real shapes, so each table can be read against reality.

Every bit of every anchor that depends on the shape is computed here from polytopes.py and asserted, never
typed in: a neighbour is 'nearer' because the distance table says so. attach() puts them on the laws, and
judge.py checks every kernel against them.
"""
from __future__ import annotations

from functools import lru_cache

import numpy as np

from neo4d import laws as L
from neo4d import polytopes as P


@lru_cache(maxsize=None)
def shape(name: str) -> P.Shape:
    return P.build(name)


def antipode(sh: P.Shape, v: int) -> int:
    far = np.nonzero(sh.dist[v] == sh.dist[v].max())[0]
    assert len(far) == 1
    return int(far[0])


def step_word(sh, u, t, w, dead=(), seen=(), room=True, full=False, quiet=True) -> int:
    D = sh.dist
    code = lambda v: 3 if v == t else 1 + int(D[u, t] - D[v, t])
    live = w not in dead
    room = room and not full                    # at most half full and full cannot both hold
    ahead = any(v not in dead and code(v) >= 2 and v not in seen for v in sh.adj[u])
    return (int(live) | code(w) << 1 | (8 if live and room else 0) | (16 if live and full else 0)
            | (32 if quiet else 0) | (64 if w in seen else 0) | (128 if ahead else 0))


def hop_anchors():
    t = shape("8-cell")
    assert P.tesseract_is_bit_addressed(t)
    out = [
        (0b1111, "node `0000` to its antipode `1111` (4 hops, 24 shortest routes), all links up - lowest "
                 "dimension first"),
        (0b1011 | 0b0001 << 4, "node `0000` to `1011`, link 0 down - the next live differing dimension, 1"),
    ]
    # a one-hop packet whose only link is down: detour, then the anti-bounce, then home in 3 hops
    u, dst, words = 0b0110, 0b0111, []
    dead_links = {(0b0110, 0)}
    back = None
    while True:
        dmask = sum(1 << d for d in range(4) if (u, d) in dead_links or d == back)
        x = (u ^ dst) | dmask << 4
        a = L.HOP.oracle(x)
        words.append((u, x, a))
        if a in (8, 12):
            break
        d = a & 3
        u, back = u ^ (1 << d), (d if a >= 4 else None)
    assert [w[2] for w in words] == [5, 0, 1, 8], words
    names = ["`0110` to `0111` (one hop), link 0 down - DETOUR across link 1 to `0100`",
             "then at `0100`: link 1 is DEAD because the packet arrived on it by a detour - FORWARD across 0",
             "then at `0101`: FORWARD across 1 to `0111`",
             "then at `0111`: DELIVER - three hops where one link failed"]
    out += [(x, n) for (_, x, _), n in zip(words, names)]
    out += [
        (0b0000 | 0b1111 << 4, "at the destination with every link down - DELIVER still"),
        (0b1111 | 0b1111 << 4, "node `0101` to `1010`, every link down - HOLD"),
    ]
    return out


def quorum_anchors():
    v = lambda heard, yes: heard | yes << 4
    return [
        (v(0b1111, 0b1111), "all four peers heard, all yes"),
        (v(0b0101, 0b0101), "only peers 1 and 3 heard, both yes - three of five, no need to hear 2 and 4"),
        (v(0b0011, 0b0001), "peers 1 and 2 heard, 1 yes and 2 no - two yes, one no, two silent"),
        (v(0b0111, 0b0000), "peers 1, 2, 3 heard, all no"),
        (v(0b1111, 0b0001), "all heard, only peer 1 yes - two yes, three no"),
        (v(0b0000, 0b0000), "nobody heard yet"),
    ]


def step_anchors():
    out = []
    six = shape("600-cell")
    u = 0
    t = antipode(six, u)
    assert six.dist[u, t] == 5 and all(six.dist[w, t] == 4 for w in six.adj[u])
    w = six.adj[u][0]
    out.append((step_word(six, u, t, w),
                "600-cell, at the antipode of the destination (5 hops): all 12 neighbours are nearer; this one has "
                "room and a quiet link"))
    out.append((step_word(six, u, t, w, room=False, full=True),
                "the same neighbour, full - the packet takes one of the other 11 nearer links"))
    t8 = shape("8-cell")
    u, t = 0b0110, 0b0111
    assert [w for w in t8.adj[u] if t8.dist[w, t] < t8.dist[u, t]] == [t]
    out.append((step_word(t8, u, t, t, dead={t}),
                "8-cell, one hop from the destination, which is down - its only nearer neighbour (c_1 = 1)"))
    far = [w for w in t8.adj[u] if t8.dist[w, t] > t8.dist[u, t]]
    assert far and not [w for w in t8.adj[u] if w != t and t8.dist[w, t] == t8.dist[u, t]]
    out.append((step_word(t8, u, t, far[0], dead={t}),
                "the same node: a farther neighbour, live with room - the detour (the 8-cell has no level neighbours, "
                "a_i = 0, so the detour is farther)"))
    tw = shape("24-cell")
    pairs = [(0, s) for s in range(tw.V) if tw.dist[0, s] == 2
             and sum(tw.dist[w, s] == 1 for w in tw.adj[0]) == 4]
    u, t = pairs[0]
    near = [w for w in tw.adj[u] if tw.dist[w, t] == 1]
    level = [w for w in tw.adj[u] if tw.dist[w, t] == 2]
    assert len(near) == 4 and level
    g = tw.coords @ tw.coords.T
    deg = round(float(np.degrees(np.arccos(np.clip(g[u, t], -1, 1)))))
    other = [s for s in range(tw.V) if tw.dist[0, s] == 2 and abs(g[0, s] - g[u, t]) > 1e-9]
    c_other = sum(tw.dist[w, other[0]] == 1 for w in tw.adj[0])
    deg_other = round(float(np.degrees(np.arccos(np.clip(g[0, other[0]], -1, 1)))))
    out.append((step_word(tw, u, t, near[0], quiet=False),
                f"24-cell, two hops away at {deg} degrees (4 nearer neighbours; at {deg_other} degrees there would "
                f"be {c_other}): a nearer one with room, link busy last tick"))
    out.append((step_word(tw, u, t, level[0]),
                "the same node: a level neighbour with room and a quiet link - 0, the nearer ones are live"))
    sx = shape("16-cell")
    u = 0
    t = antipode(sx, u)
    assert all(sx.dist[w, t] == 1 for w in sx.adj[u])
    w0, w1 = sx.adj[u][0], sx.adj[u][1]
    out.append((step_word(sx, u, t, w0, seen={w0}),
                "16-cell, at the destination's antipode (all 6 neighbours nearer): one the packet already visited"))
    ot = shape("120-cell")
    u = 0
    t = antipode(ot, u)
    assert ot.dist[u, t] == 15 and all(ot.dist[w, t] == 14 for w in ot.adj[u])
    out.append((step_word(ot, u, t, ot.adj[u][0]),
                "120-cell, 15 hops from the destination at its antipode: all 4 neighbours nearer (c_15 = 4)"))
    u, t = 0b0000, 0b0001
    out.append((step_word(t8, u, t, t, full=True),
                "8-cell, the neighbour IS the destination and reports full - 10, the destination consumes"))
    return out


def admit_anchors():
    w = lambda mine=0, dup=0, q=0, last=0, copy=0, urgent=0, spent=0: (
        mine | dup << 1 | q << 2 | last << 4 | copy << 5 | urgent << 6 | spent << 7)
    return [
        (w(mine=1, q=3, last=1), "arrives at its destination on its last hop, queue full"),
        (w(mine=1, dup=1), "a retry of a packet already delivered here"),
        (w(q=3), "in transit, queue full, first try"),
        (w(q=3, spent=1), "the same, retry budget spent"),
        (w(q=2, copy=1), "an antipodal mirror copy, queue at half"),
        (w(q=2, copy=1, urgent=1), "the same copy, marked urgent"),
        (w(q=2), "an original, queue at half"),
        (w(last=1), "in transit, hop budget spent"),
    ]


def mirror_anchors():
    out = []
    w = lambda hu=0, mu=0, hc=0, mc=0, nm=0, wr=0, rep=0, one=0: (
        hu | mu << 1 | hc << 2 | mc << 3 | nm << 4 | wr << 5 | rep << 6 | one << 7)
    t8 = shape("8-cell")
    h, m, r = 0b0000, antipode(t8, 0b0000), 0b0111
    assert m == 0b1111 and t8.dist[r, h] == 3 and t8.dist[r, m] == 1
    out.append((w(1, 1, 1, 1, nm=1), "8-cell: home `0000`, mirror `1111`, read from `0111` - 3 hops to the home, "
                                       "1 to the mirror"))
    sx = shape("16-cell")
    h = 0
    m = antipode(sx, h)
    assert all(sx.dist[r, h] == sx.dist[r, m] == 1 for r in range(sx.V) if r not in (h, m))
    out.append((w(1, 1, 1, 1), "16-cell: every other node is one hop from both copies - ties, so the home"))
    tw = shape("24-cell")
    h = 0
    m = antipode(tw, h)
    g = tw.coords @ tw.coords.T
    tie = [r for r in range(tw.V) if tw.dist[r, h] == 2 and abs(g[r, h]) < 1e-9]
    lop = [r for r in range(tw.V) if tw.dist[r, h] == 2 and abs(g[r, h] + 0.5) < 1e-9]
    assert tie and lop and tw.dist[tie[0], m] == 2 and tw.dist[lop[0], m] == 1
    out.append((w(1, 1, 1, 1, nm=1), "24-cell: a reader 2 hops from the home at 120 degrees is 1 hop from the mirror "
                                       "(at 90 degrees it would be 2 and 2 - hops to the copies need not sum to the "
                                       "diameter)"))
    six = shape("600-cell")
    h = 0
    m = antipode(six, h)
    outage = {h, *six.adj[h]}
    assert m not in outage and not (set(six.adj[m]) & outage)
    out.append((w(0, 1, 0, 1), "600-cell: the home and all 12 of its neighbours are down - the mirror and all 12 of "
                               "its neighbours are untouched"))
    out.append((w(0, 1, 0, 1, wr=1), "a write during that outage, key needs two copies"))
    out.append((w(0, 1, 0, 1, wr=1, one=1), "the same write, key allows one copy"))
    out.append((w(1, 1, 0, 1), "the home is back, stale (it missed that write) - serve the mirror, repair the home"))
    out.append((w(1, 1, 0, 1, rep=1), "the same read with that repair already in flight"))
    return out


def _traced_job(shape_name: str, k: int, seed: int, strict: bool = False):
    """One real job through the real swarm, every law decision recorded."""
    import random
    from neo4d import classes as C
    from neo4d import jobs as J
    from neo4d import swarm as S
    g = S.polytope(shape_name)
    taught = C.taught(S.capacity(g, True))
    shipped = C.shipped()
    pl = S.place(g, taught, g.partner)
    by = {c.name: c for c in shipped + taught}
    rng = random.Random(seed)
    ds = rng.sample(range(len(pl.dictionaries)), k)
    faults = [rng.choice(pl.dictionaries[d]).name for d in ds] + ["minmax-swap"]
    job = J.make_job(faults, ["strictness"], rng, by)
    trace = []
    r = S.shape(job, g, pl, shipped, entry=0, strict=strict, trace=trace)
    return g, pl, faults, trace, r


def carry_anchors():
    out = []
    g, pl, faults, trace, r = _traced_job("8-cell", 3, seed=7)
    cs = [t for t in trace if t[0] == "carry"]
    assert r.repaired and [t[2] for t in cs][-1] == 2
    for t in cs:
        _, x, act, here, visits = t
        out.append((x, f"8-cell, a job with faults {', '.join(faults)}: after visit {visits}, at node "
                       f"`{here:04b}`"))
    g, pl, faults, trace, r = _traced_job("8-cell", 3, seed=7, strict=True)
    last = [t for t in trace if t[0] == "carry"][-1]
    out.append((last[1], "the same job under a STRICT policy, at the end: green, but a shipped class's step has "
                         "no property"))
    w = lambda **b: sum(1 << i for i, n in enumerate(("green", "stable", "broke", "unproven", "strict", "plan",
                                                      "spent", "rechecked")) if b.get(n))
    out += [(w(), "red and the re-run disagreed - first time"),
            (w(rechecked=1), "red and the re-run disagreed again"),
            (w(stable=1, broke=1, plan=1), "a carried edit broke a test that passed at the edge"),
            (w(stable=1, plan=1, spent=1), "red, a net left to try, visit budget spent")]
    return out


def seek_anchors():
    g, pl, faults, trace, r = _traced_job("600-cell", 3, seed=11)
    ss = [t for t in trace if t[0] == "seek"]
    first_here = ss[0][3]
    first = [t for t in ss if t[3] == first_here]
    pos = sorted([t for t in first if t[2] > 0], key=lambda t: -t[2])
    out = []
    for t in pos[:3]:
        _, x, rank, here, v, d = t
        out.append((x, f"600-cell, a job with faults {', '.join(faults)}, at its edge node {here}: dictionary {d} "
                       f"at node {v}, {int(g.dist[here, v])} hops away"))
    zeros = [t for t in first if t[2] == 0]
    tried = [t for t in zeros if t[1] >> 5 & 1]
    blind = [t for t in zeros if not t[1] >> 5 & 1 and (t[1] >> 3 & 3) == 0]
    if tried:
        out.append((tried[0][1], "the same decision: the edge node's own dictionary - it has had its turn"))
    if blind:
        out.append((blind[0][1], "the same decision: a dictionary whose signals match no line of the code"))
    w = lambda live=1, near=1, hits=1, tried=0, unc=0, full=0: (live | near << 1 | hits << 3 | tried << 5
                                                                 | unc << 6 | full << 7)
    out += [(w(near=3, hits=3), "three or more lines match, farther than half the diameter"),
            (w(near=1, hits=2), "two lines match, one hop away - fewer lines lose, however near"),
            (w(near=1, hits=3, full=1), "the best candidate, but its queue is full"),
            (w(near=2, hits=2, unc=1), "a STRICT job, and a matching class has no property")]
    return out


def attach() -> None:
    L.HOP.anchors = hop_anchors()
    L.QUORUM.anchors = quorum_anchors()
    L.STEP.anchors = step_anchors()
    L.ADMIT.anchors = admit_anchors()
    L.MIRROR.anchors = mirror_anchors()
    L.CARRY.anchors = carry_anchors()
    L.SEEK.anchors = seek_anchors()
    for law in L.LAWS.values():
        for x, _ in law.anchors:
            assert law.reachable(x), (law.name, x)
