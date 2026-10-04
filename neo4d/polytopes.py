"""The six regular convex 4D polytopes, as swarm graphs.

Every vertex is a node of the swarm, every edge a link. Coordinates are exact up to float rounding and every
invariant below is MEASURED from them, never typed in: `python3 polytopes.py` prints the table the law prompts
quote, and exits non-zero if any measured fact disagrees with the known value.

    5-cell    5 vertices   K5                  every node sees every node
    8-cell   16 vertices   the tesseract Q4    node = a 4-bit word, link = one bit flipped
    16-cell   8 vertices   K(2,2,2,2)          linked to all but its antipode
    24-cell  24 vertices   degree 8            self-dual, no 3D analogue
    120-cell 600 vertices  degree 4            built here as the dual of the 600-cell
    600-cell 120 vertices  degree 12
"""
from __future__ import annotations

import itertools
import sys
from collections import deque
from dataclasses import dataclass, field

import numpy as np

PHI = (1 + 5 ** 0.5) / 2
EPS = 1e-6


@dataclass
class Shape:
    name: str
    coords: np.ndarray                      # (V, 4), unit circumradius
    adj: list[list[int]] = field(default_factory=list)
    dist: np.ndarray | None = None          # (V, V) hop distance

    @property
    def V(self) -> int:
        return len(self.coords)

    @property
    def E(self) -> int:
        return sum(len(a) for a in self.adj) // 2


def _unit(rows) -> np.ndarray:
    a = np.array(rows, dtype=float)
    return a / np.linalg.norm(a, axis=1, keepdims=True)


def _link_nearest(coords: np.ndarray) -> list[list[int]]:
    """Edges are exactly the pairs at the minimum distance - true of every regular polytope."""
    g = coords @ coords.T
    np.fill_diagonal(g, -np.inf)
    top = g.max()
    return [list(np.nonzero(np.abs(row - top) < EPS)[0]) for row in g]


def _even_perms(n: int):
    for p in itertools.permutations(range(n)):
        inv = sum(1 for i in range(n) for j in range(i + 1, n) if p[i] > p[j])
        if inv % 2 == 0:
            yield p


def five_cell() -> np.ndarray:
    r = 1 / 5 ** 0.5
    return _unit([[1, 1, 1, -r], [1, -1, -1, -r], [-1, 1, -1, -r], [-1, -1, 1, -r], [0, 0, 0, 4 * r]])


def tesseract() -> np.ndarray:
    """Vertex i has coordinate k = +1 when bit k of i is set: node id IS the 4-bit address."""
    return _unit([[1 if i >> k & 1 else -1 for k in range(4)] for i in range(16)])


def sixteen_cell() -> np.ndarray:
    rows = []
    for k in range(4):
        for s in (1, -1):
            r = [0, 0, 0, 0]
            r[k] = s
            rows.append(r)
    return _unit(rows)


def twenty_four_cell() -> np.ndarray:
    rows = set()
    for i, j in itertools.combinations(range(4), 2):
        for si, sj in itertools.product((1, -1), repeat=2):
            r = [0, 0, 0, 0]
            r[i], r[j] = si, sj
            rows.add(tuple(r))
    return _unit(sorted(rows))


def six_hundred_cell() -> np.ndarray:
    rows = set()
    for k in range(4):
        for s in (1, -1):
            r = [0.0] * 4
            r[k] = s
            rows.add(tuple(r))
    for signs in itertools.product((0.5, -0.5), repeat=4):
        rows.add(signs)
    base = (PHI / 2, 0.5, 1 / (2 * PHI), 0.0)
    for p in _even_perms(4):
        for s in itertools.product((1, -1), repeat=3):
            v = [base[0] * s[0], base[1] * s[1], base[2] * s[2], 0.0]
            rows.add(tuple(round(v[p[i]], 12) for i in range(4)))
    return _unit(sorted(rows))


def one_twenty_cell() -> np.ndarray:
    """Dual of the 600-cell: one vertex at the centre of each of its 600 tetrahedral cells."""
    c = six_hundred_cell()
    adj = _link_nearest(c)
    nb = [set(a) for a in adj]
    cells = set()
    for a in range(len(c)):
        for b, cc, d in itertools.combinations(sorted(nb[a]), 3):
            if b in nb[cc] and b in nb[d] and cc in nb[d]:
                cells.add(tuple(sorted((a, b, cc, d))))
    assert len(cells) == 600, len(cells)
    return _unit([c[list(t)].sum(axis=0) for t in sorted(cells)])


BUILDERS = {
    "5-cell": five_cell,
    "8-cell": tesseract,
    "16-cell": sixteen_cell,
    "24-cell": twenty_four_cell,
    "120-cell": one_twenty_cell,
    "600-cell": six_hundred_cell,
}

# The known values every measurement is checked against (Coxeter, Regular Polytopes, table I(ii)).
KNOWN = {  # V, E, degree
    "5-cell": (5, 10, 4),
    "8-cell": (16, 32, 4),
    "16-cell": (8, 24, 6),
    "24-cell": (24, 96, 8),
    "120-cell": (600, 1200, 4),
    "600-cell": (120, 720, 12),
}


def _bfs(adj, s):
    d = [-1] * len(adj)
    d[s] = 0
    q = deque([s])
    while q:
        u = q.popleft()
        for w in adj[u]:
            if d[w] < 0:
                d[w] = d[u] + 1
                q.append(w)
    return d


def build(name: str) -> Shape:
    coords = BUILDERS[name]()
    adj = _link_nearest(coords)
    dist = np.array([_bfs(adj, s) for s in range(len(coords))])
    return Shape(name, coords, adj, dist)


@dataclass
class Facts:
    name: str
    V: int
    E: int
    degree: int
    diameter: int
    shells: list[int]           # k_i: nodes at distance i from any node
    closer: list[list[int]]     # c_i: neighbours one step closer to a node at distance i (every value seen)
    level: list[list[int]]      # a_i: neighbours at the same distance
    farther: list[list[int]]    # b_i: neighbours one step farther
    distance_regular: bool      # c_i, a_i, b_i are single numbers at every distance
    geodesics_to_far: int       # shortest paths from a node to one at distance = diameter
    antipodal: bool             # -v is a vertex for every v
    antipode_at_diameter: bool  # -v is the unique node at distance = diameter
    antipode_nbhd_disjoint: bool
    dot_to_dist: dict           # inner product of unit vectors -> every hop distance seen at that angle
    connectivity: int           # node-disjoint paths from node 0, minimum over every other node (vertex-
                                # transitive, so this is the connectivity of the whole graph)
    choice_pairs: tuple         # (ordered pairs s != t where s has >= 2 nearer neighbours toward t, all pairs)


def _disjoint_paths(adj, s, t) -> int:
    """Max number of internally node-disjoint s-t paths (unit-capacity vertex split, BFS augmenting)."""
    n = len(adj)
    cap = {}
    def add(u, v, c):
        cap[(u, v)] = cap.get((u, v), 0) + c
        cap.setdefault((v, u), 0)
    for v in range(n):
        add(2 * v, 2 * v + 1, n if v in (s, t) else 1)       # in -> out
        for w in adj[v]:
            add(2 * v + 1, 2 * w, 1)
    out = {}
    for (u, v) in cap:
        out.setdefault(u, []).append(v)
    src, snk, flow = 2 * s, 2 * t + 1, 0
    while True:
        par = {src: None}
        q = deque([src])
        while q and snk not in par:
            u = q.popleft()
            for v in out[u]:
                if v not in par and cap[(u, v)] > 0:
                    par[v] = u
                    q.append(v)
        if snk not in par:
            return flow
        v = snk
        while par[v] is not None:
            u = par[v]
            cap[(u, v)] -= 1
            cap[(v, u)] += 1
            v = u
        flow += 1


def measure(sh: Shape) -> Facts:
    D = sh.dist
    diam = int(D.max())
    deg = {len(a) for a in sh.adj}
    assert len(deg) == 1, f"{sh.name} is not regular"
    k = len(sh.adj[0])
    shells, closer, level, farther = [], [], [], []
    for i in range(diam + 1):
        ks = {int((D[s] == i).sum()) for s in range(sh.V)}
        assert len(ks) == 1, f"{sh.name}: shell {i} size varies by node"
        shells.append(ks.pop())
        cs, as_, bs = set(), set(), set()
        for s in range(sh.V):
            for t in np.nonzero(D[s] == i)[0]:
                cs.add(sum(1 for w in sh.adj[s] if D[w, t] == i - 1))
                as_.add(sum(1 for w in sh.adj[s] if D[w, t] == i))
                bs.add(sum(1 for w in sh.adj[s] if D[w, t] == i + 1))
        # a single value when the shape is distance-regular at i; every value that occurs otherwise
        closer.append(sorted(cs)); level.append(sorted(as_)); farther.append(sorted(bs))
    distance_regular = all(len(x) == 1 for x in closer + level + farther)
    # shortest paths to a farthest node, counted from node 0
    t = int(np.nonzero(D[0] == diam)[0][0])
    ways = [0] * sh.V
    ways[0] = 1
    for v in sorted(range(sh.V), key=lambda v: D[0, v])[1:]:
        ways[v] = sum(ways[w] for w in sh.adj[v] if D[0, w] == D[0, v] - 1)
    # antipodes
    keyed = {tuple(np.round(c, 6)): i for i, c in enumerate(sh.coords)}
    anti = [keyed.get(tuple(np.round(-c, 6))) for c in sh.coords]
    antipodal = all(a is not None for a in anti)
    at_diam = antipodal and all(D[v, anti[v]] == diam and int((D[v] == diam).sum()) == 1 for v in range(sh.V))
    disjoint = antipodal and all(not (set(sh.adj[v]) & set(sh.adj[anti[v]])) for v in range(sh.V))
    # inner product -> distance must be a function
    g = sh.coords @ sh.coords.T
    d2d: dict[float, set] = {}
    for s in range(sh.V):
        for u in range(sh.V):
            d2d.setdefault(round(float(g[s, u]), 6), set()).add(int(D[s, u]))
    dot_to_dist = {k: sorted(v) for k, v in sorted(d2d.items(), reverse=True)}
    conn = min(_disjoint_paths(sh.adj, 0, u) for u in range(1, sh.V))
    choice = sum(1 for s in range(sh.V) for u in range(sh.V) if s != u
                 and sum(1 for w in sh.adj[s] if D[w, u] < D[s, u]) >= 2)
    return Facts(sh.name, sh.V, sh.E, k, diam, shells, closer, level, farther, distance_regular, ways[t],
                 antipodal, at_diam, disjoint, dot_to_dist, conn, (choice, sh.V * (sh.V - 1)))


def tesseract_is_bit_addressed(sh: Shape) -> bool:
    """Node i and node j are linked exactly when i ^ j is a power of two, and distance = popcount(i ^ j)."""
    return all(
        ((j in sh.adj[i]) == (bin(i ^ j).count("1") == 1)) and sh.dist[i, j] == bin(i ^ j).count("1")
        for i in range(16) for j in range(16))


def main() -> int:
    bad = 0
    print(f"{'shape':9} {'V':>4} {'E':>5} {'deg':>3} {'diam':>4} {'conn':>4} {'antip':>5}  shells / closer c_i / farther b_i")
    for name in BUILDERS:
        f = measure(build(name))
        kv, ke, kd = KNOWN[name]
        ok = (f.V, f.E, f.degree) == (kv, ke, kd)
        bad += not ok
        print(f"{name:9} {f.V:4} {f.E:5} {f.degree:3} {f.diameter:4} {f.connectivity:4} {str(f.antipode_at_diameter):>5}"
              f"  DRG={str(f.distance_regular):5} k={f.shells} c={f.closer} geodesics->far={f.geodesics_to_far}"
              f"{'' if ok else '   <-- DISAGREES WITH KNOWN'}")
    t = build("8-cell")
    ba = tesseract_is_bit_addressed(t)
    bad += not ba
    print(f"\n  8-cell: linked iff i^j is one bit, distance = popcount(i^j)   {ba}")
    print(f"\n  TOTAL  {bad} disagreements")
    return bad != 0


if __name__ == "__main__":
    sys.exit(main())
