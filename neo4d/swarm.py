"""fluidnet on a 4D shape - many small nets, no overseer, data flowing through the polytope.

Three ways to run the same nets, with the same dictionaries, on the same jobs:

    static      fluidnet as built: one overseer, nets ordered by how much of the job their taught signals
                recognise, each net tries ALONE from the original code, the first green wins. One hop out
                and one back per net tried, all through the overseer.
    star+carry  the control: the same overseer and order, but a net's partial progress is handed to the
                next net. Isolates what CARRYING buys from what the SHAPE buys.
    shape       no overseer. Every net sits on a vertex of the polytope; every dictionary lives on a home
                node and on its antipode (the MIRROR law picks the copy). A job starts at its edge node,
                which repairs what it can locally, then travels hop by hop (STEP law, or HOP on the
                8-cell) to the nets holding the classes its code needs, carrying its partial repair.
                Only a green module is accepted; anything else returns the original, untouched.

The laws are the oracles in laws.py until the superoptimizer's kernels arrive; load_laws() swaps in judged
kernels and refuses any kernel the judge does not pass clean.
"""
from __future__ import annotations

import random
from collections import deque
from dataclasses import dataclass, field

import numpy as np

from neo4d import laws as L
from neo4d import polytopes as P
from neo4d.classes import SLOTS_TAUGHT, FaultClass
from neo4d.fnet import net_descend
from neo4d.jobs import Job, failing

LAWS = {"step": L.STEP.oracle, "hop": L.HOP.oracle, "mirror": L.MIRROR.oracle, "admit": L.ADMIT.oracle,
        "carry": L.CARRY.oracle, "seek": L.SEEK.oracle}


def load_laws(folder: str) -> list[str]:
    """Swap in the superoptimizer's kernels - each one only if judge.py passes it with zero violations."""
    import os
    from neo4d import anchors
    from neo4d import judge
    anchors.attach()
    took = []
    for name in list(LAWS):
        for ext in (".c", ".py"):
            p = os.path.join(folder, name + ext)
            if os.path.exists(p):
                law = L.LAWS[name]
                k = judge.load_kernel(law, p)
                res = L.judge(law, k)
                if any(res.values()):
                    raise SystemExit(f"{p}: the judge found violations - not loaded")
                LAWS[name] = k
                took.append(p)
    return took


# ------------------------------------------------------------------------------------------- topologies

@dataclass
class Graph:
    name: str
    adj: list[list[int]]
    dist: np.ndarray
    partner: list[int] | None = None        # mirror of each node, or None when not mirrored
    bit_addressed: bool = False             # node id is the address (8-cell): HOP law routes

    @property
    def V(self):
        return len(self.adj)


def _bfs_all(adj):
    n = len(adj)
    D = np.full((n, n), -1, dtype=int)
    for s in range(n):
        D[s, s] = 0
        q = deque([s])
        while q:
            u = q.popleft()
            for w in adj[u]:
                if D[s, w] < 0:
                    D[s, w] = D[s, u] + 1
                    q.append(w)
    return D


def _farthest_pairs(D):
    """Pair every node with the farthest unpaired node (lowest index on ties)."""
    n = len(D)
    partner = [-1] * n
    for v in range(n):
        if partner[v] >= 0:
            continue
        cands = [w for w in range(n) if w != v and partner[w] < 0]
        if not cands:
            partner[v] = v
            continue
        w = max(cands, key=lambda w: (D[v, w], -w))
        partner[v], partner[w] = w, v
    return partner


def polytope(name: str, mirror: bool = True) -> Graph:
    sh = P.build(name)
    partner = None
    if mirror:
        keyed = {tuple(np.round(c, 6)): i for i, c in enumerate(sh.coords)}
        anti = [keyed.get(tuple(np.round(-c, 6))) for c in sh.coords]
        partner = anti if all(a is not None for a in anti) else None
    return Graph(name, sh.adj, sh.dist, partner, bit_addressed=(name == "8-cell"))


def ring(n: int, mirror: bool = True) -> Graph:
    adj = [[(i - 1) % n, (i + 1) % n] for i in range(n)]
    D = _bfs_all(adj)
    return Graph(f"ring{n}", adj, D, _farthest_pairs(D) if mirror else None)


def random_regular(n: int, d: int, seed: int, mirror: bool = True) -> Graph:
    """A random d-regular graph: a circulant start, then degree-preserving double-edge swaps (10 per edge),
    kept simple and connected. The control for 'same nodes, same links each, no geometry'."""
    assert d % 2 == 0 and d < n
    rng = random.Random(seed)
    edges = {tuple(sorted((v, (v + k) % n))) for v in range(n) for k in range(1, d // 2 + 1)}
    edges = sorted(edges)
    present = set(edges)
    for _ in range(10 * len(edges)):
        i, j = rng.randrange(len(edges)), rng.randrange(len(edges))
        (a, b), (c, e) = edges[i], edges[j]
        if rng.random() < 0.5:
            c, e = e, c
        n1, n2 = tuple(sorted((a, e))), tuple(sorted((c, b)))
        if len({a, b, c, e}) < 4 or n1 in present or n2 in present:
            continue
        present -= {edges[i], edges[j]}
        present |= {n1, n2}
        edges[i], edges[j] = n1, n2
    adj = [[] for _ in range(n)]
    for a, b in edges:
        adj[a].append(b); adj[b].append(a)
    adj = [sorted(x) for x in adj]
    assert all(len(x) == d for x in adj)
    D = _bfs_all(adj)
    if not (D >= 0).all():
        return random_regular(n, d, seed + 1, mirror)
    return Graph(f"random{n}d{d}", adj, D, _farthest_pairs(D) if mirror else None)


def random_partner(g: Graph, seed: int) -> list[int]:
    """The control for antipodal placement: pair nodes at random instead."""
    rng = random.Random(seed)
    order = list(range(g.V))
    rng.shuffle(order)
    partner = [-1] * g.V
    for a, b in zip(order[::2], order[1::2]):
        partner[a], partner[b] = b, a
    return partner


# ---------------------------------------------------------------------------------------- the swarm

@dataclass
class Placement:
    dictionaries: list[list[FaultClass]]     # dictionary d: at most SLOTS_TAUGHT taught classes
    holders: list[list[int]]                 # dictionary d lives on these nodes
    of_node: list[int]                       # node -> dictionary


def place(g: Graph, taught: list[FaultClass], partner: list[int] | None) -> Placement:
    """Mirrored: one dictionary per partner pair. Unmirrored: one per node."""
    if partner is None:
        groups = [[v] for v in range(g.V)]
    else:
        seen, groups = set(), []
        for v in range(g.V):
            if v not in seen:
                groups.append(sorted({v, partner[v]}))
                seen.update(groups[-1])
    dicts = [taught[i * SLOTS_TAUGHT:(i + 1) * SLOTS_TAUGHT] for i in range(len(groups))]
    of_node = [0] * g.V
    for d, grp in enumerate(groups):
        for v in grp:
            of_node[v] = d
    return Placement(dicts, groups, of_node)


def single_copy(pl: Placement, V: int) -> Placement:
    """Each dictionary on its home node only; every other node carries the shipped classes and nothing else."""
    holders = [h[:1] for h in pl.holders]
    of_node = [-1] * V
    for d, h in enumerate(holders):
        of_node[h[0]] = d
    return Placement(pl.dictionaries, holders, of_node)


def capacity(g: Graph, mirrored: bool) -> int:
    groups = g.V if not mirrored else len({tuple(sorted((v, g.partner[v]))) for v in range(g.V)})
    return groups * SLOTS_TAUGHT


@dataclass
class Result:
    repaired: bool
    runs: int = 0                 # test-suite runs, the expensive unit
    nets: int = 0                 # net visits that ran a descent
    hops: int = 0                 # messages along links, there and back
    load: dict = field(default_factory=dict)   # node -> messages it handled
    why: str = ""


def _hits(dictionary: list[FaultClass], code: str) -> int:
    return sum(len(c.signal.findall(code)) for c in dictionary)


def _accept(code: str, tests: list[str]) -> bool:
    return not failing(code, tests)


def static(job: Job, pl: Placement, shipped: list[FaultClass], dead: set[int] = frozenset(),
           carry: bool = False, overseer_dead: bool = False) -> Result:
    """fluidnet's watch: the overseer orders the dictionaries' nets by signal hits and tries them."""
    if overseer_dead:
        return Result(False, why="the overseer is down")
    r = Result(False)
    order = sorted(range(len(pl.dictionaries)), key=lambda d: -_hits(pl.dictionaries[d], job.code))
    code, cur = job.code, failing(job.code, job.tests)
    r.runs += 1
    tried_any = False
    for d in order:
        live = [v for v in pl.holders[d] if v not in dead]
        if not live:
            continue
        if carry and tried_any and _hits(pl.dictionaries[d], code) == 0:
            continue                              # carrying: only nets whose classes the code still shows
        v = live[0]
        r.hops += 2
        r.load["overseer"] = r.load.get("overseer", 0) + 2
        r.load[v] = r.load.get(v, 0) + 2
        start_code, start_cur = (code, cur) if carry else (job.code, failing(job.code, job.tests))
        out = net_descend(start_code, job.tests, shipped + pl.dictionaries[d], start=start_cur)
        r.runs += out["runs"]
        r.nets += 1
        tried_any = True
        if not out["failing"]:
            r.repaired = _accept(out["code"], job.tests)
            return r
        if carry and out["failing"] < cur:
            code, cur = out["code"], out["failing"]
    r.why = "no net reached green"
    return r


def _route(g: Graph, s: int, t: int, dead: set[int]) -> list[int] | None:
    """Hop by hop by the laws. Returns the node path s..t, or None if the packet is stuck."""
    if g.bit_addressed:
        return _route_hop(s, t, dead)
    path, seen, u = [s], {s}, s
    D = g.dist
    while u != t:
        code = lambda w: 3 if w == t else 1 + int(D[u, t] - D[w, t])
        ahead = any(w not in dead and code(w) >= 2 and w not in seen for w in g.adj[u])
        best, best_r = None, 0
        for w in g.adj[u]:
            live = w not in dead
            x = (int(live) | code(w) << 1 | (8 if live else 0) | 32
                 | (64 if w in seen else 0) | (128 if ahead else 0))
            rank = LAWS["step"](x)
            if rank > best_r:
                best, best_r = w, rank
        if best is None or len(path) > g.V:
            return None
        u = best
        seen.add(u)
        path.append(u)
    return path


def _route_hop(s: int, t: int, dead: set[int]) -> list[int] | None:
    path, u, back = [s], s, None
    for _ in range(17):
        dmask = sum(1 << d for d in range(4) if (u ^ (1 << d)) in dead or d == back)
        a = LAWS["hop"]((u ^ t) | dmask << 4)
        if a == 8:
            return path if u == t else None
        if not 0 <= a <= 7 or dmask >> (a & 3) & 1:
            return None
        d = a & 3
        u, back = u ^ (1 << d), (d if a >= 4 else None)
        path.append(u)
    return None


def _copy(g: Graph, holders: list[int], here: int, dead: set[int]) -> int | None:
    """The MIRROR law, read path: a dictionary is static, so both copies are always current."""
    if len(holders) == 1:
        return holders[0] if holders[0] not in dead else None
    h, m = holders[0], holders[1]
    hu, mu = int(h not in dead), int(m not in dead)
    nm = int(g.dist[here, m] < g.dist[here, h])
    x = hu | mu << 1 | hu << 2 | mu << 3 | nm << 4
    t = LAWS["mirror"](x) & 3
    return {1: h, 2: m}.get(t)


def _lines_hit(dictionary: list[FaultClass], code: str) -> int:
    return sum(1 for line in code.split("\n") if any(c.signal.search(line) for c in dictionary))


def _near_band(g: Graph, a: int, b: int) -> int:
    d = int(g.dist[a, b])
    return 0 if d == 0 else 1 if d == 1 else 2 if 2 * d <= int(g.dist.max()) + 1 else 3


def shape(job: Job, g: Graph, pl: Placement, shipped: list[FaultClass], entry: int,
          dead: set[int] = frozenset(), strict: bool = False, budget: int | None = None,
          trace: list | None = None) -> Result:
    """No overseer. The edge repairs what it can; then SEEK picks the next net, MIRROR the copy, STEP (or HOP)
    the hops, and CARRY what travels - every decision a law."""
    r = Result(False)
    if entry in dead:
        return Result(False, why="the edge node is down")
    budget = budget if budget is not None else len(pl.dictionaries)
    code, cur = job.code, failing(job.code, job.tests)
    at_edge = cur
    r.runs += 1
    here, served, visits, unproven = entry, set(), 0, False

    def visit(v):
        nonlocal code, cur, visits, unproven
        d = pl.of_node[v]
        if d >= 0:
            served.add(d)
        visits += 1
        out = net_descend(code, job.tests, shipped + (pl.dictionaries[d] if d >= 0 else []), start=cur)
        r.runs += out["runs"]
        r.nets += 1
        code, cur = out["code"], out["failing"]       # descent keeps only strict improvements
        unproven = unproven or any(not s["proven"] for s in out["steps"])

    def candidates():
        out = []
        for d in range(len(pl.dictionaries)):
            v = _copy(g, pl.holders[d], here, dead)
            if v is None:
                continue
            hits = min(3, _lines_hit(pl.dictionaries[d], code))
            unc = strict and any(c.prop is None and c.signal.search(code) for c in pl.dictionaries[d])
            x = 1 | _near_band(g, here, v) << 1 | hits << 3 | int(d in served) << 5 | int(unc) << 6
            rank = LAWS["seek"](x)
            if trace is not None:
                trace.append(("seek", x, rank, here, v, d))
            if rank > 0:
                out.append((rank, -v, v))
        return sorted(out, reverse=True)

    visit(here)                                   # the edge repairs what it can, zero hops
    rechecked = False
    while True:
        cands = candidates()
        stable = failing(code, job.tests) == cur
        x = (int(not cur) | int(stable) << 1 | int(not cur <= at_edge) << 2 | int(unproven) << 3
             | int(strict) << 4 | int(bool(cands)) << 5 | int(visits >= budget) << 6 | int(rechecked) << 7)
        act = LAWS["carry"](x)
        if trace is not None:
            trace.append(("carry", x, act, here, visits))
        if act == 2:
            r.repaired = True
            break
        if act == 3:
            rechecked = True
            cur = failing(code, job.tests)
            continue
        if act == 0:
            break
        rechecked = False
        v = cands[0][2]
        path = _route(g, here, v, dead)
        if path is None:                          # unreachable now: that dictionary is done for this job
            if pl.of_node[v] >= 0:
                served.add(pl.of_node[v])
            continue
        for u in path[1:]:
            r.load[u] = r.load.get(u, 0) + 1
        r.hops += len(path) - 1
        here = v
        visit(here)
    if here != entry:                             # the answer goes back to the edge
        back = _route(g, here, entry, dead)
        r.hops += (len(back) - 1) if back else int(g.dist[here, entry])
        for u in (back or [])[1:]:
            r.load[u] = r.load.get(u, 0) + 1
    if not r.repaired:
        r.why = "refused - the original returned to the edge, untouched"
    return r
