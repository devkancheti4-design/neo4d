"""Replay the routing laws on the real shapes with dead nodes - judged before asking.

No queues, no traffic: this measures what the LAW does with faults alone. A dead node is a node all of whose
links are dead. A packet is delivered, stuck (every option ranked 0 / HOLD), or out of budget.

    python3 replay.py            the table the prompts quote
    any law kernel can be replayed: replay_hop(kernel), replay_step(shape, kernel)
"""
from __future__ import annotations

import itertools
import random
import sys

from neo4d import laws as L
from neo4d import polytopes as P


def route_hop(k, dead: set[int], s: int, t: int, ttl: int = 16):
    """HOP on the 8-cell. Returns hops taken, or None if not delivered."""
    u, back, hops = s, None, 0
    while hops <= ttl:
        diff = u ^ t
        dmask = sum(1 << d for d in range(4) if (u ^ (1 << d)) in dead or d == back)
        a = k(diff | dmask << 4)
        if a == 8:
            return hops if u == t else None
        if a == 12 or not 0 <= a <= 7:
            return None
        d = a & 3
        if dmask >> d & 1:
            return None                 # a law that crosses a dead link fails the packet
        u, back, hops = u ^ (1 << d), (d if a >= 4 else None), hops + 1
    return None


def route_step(sh: P.Shape, k, dead: set[int], s: int, t: int):
    """STEP on any shape, no load: ROOM and QUIET set, FULL clear. Returns hops, or None."""
    u, seen, hops = s, {s}, 0
    D = sh.dist
    while u != t:
        nbrs = sh.adj[u]
        def dist_code(w):
            return 3 if w == t else 1 + (D[u, t] - D[w, t])     # 0 farther, 1 level, 2 nearer
        ahead = any(w not in dead and dist_code(w) >= 2 and w not in seen for w in nbrs)
        best, best_r = None, 0
        for w in nbrs:
            live = w not in dead
            x = (int(live) | dist_code(w) << 1 | (8 if live else 0) | 32
                 | (64 if w in seen else 0) | (128 if ahead else 0))
            r = k(x)
            if r > best_r:
                best, best_r = w, r
        if best is None:
            return None
        u = best
        seen.add(u)
        hops += 1
        if hops > sh.V:
            return None
    return hops


def _components(sh, dead):
    comp, cid = {}, 0
    for v in range(sh.V):
        if v in dead or v in comp:
            continue
        stack = [v]
        comp[v] = cid
        while stack:
            u = stack.pop()
            for w in sh.adj[u]:
                if w not in dead and w not in comp:
                    comp[w] = cid
                    stack.append(w)
        cid += 1
    return comp


def _fault_sets(sh, f, cap, seed):
    """Every fault set of size f if there are at most cap of them (exhaustive=True), else cap sampled ones."""
    if f == 0:
        return [set()], True
    total = 1
    for i in range(f):
        total = total * (sh.V - i) // (i + 1)
    if total <= cap:
        return [set(c) for c in itertools.combinations(range(sh.V), f)], True
    rng = random.Random(seed * 1000 + f)
    return [set(rng.sample(range(sh.V), f)) for _ in range(cap)], False


def measure(sh: P.Shape, route, faults: int, cap_sets=60, cap_pairs=400, seed=1):
    """Over fault sets of the given size: delivered / connected pairs, and mean stretch (hops / shortest)."""
    ok = tried = 0
    stretch = 0.0
    rng = random.Random(seed)
    sets, exhaustive = _fault_sets(sh, faults, cap_sets, seed)
    for dead in sets:
        comp = _components(sh, dead)
        live = [v for v in range(sh.V) if v not in dead]
        pairs = [(s, t) for s in live for t in live if s != t and comp[s] == comp[t]]
        if len(pairs) > cap_pairs:
            pairs = rng.sample(pairs, cap_pairs)
            exhaustive = False
        for s, t in pairs:
            tried += 1
            h = route(dead, s, t)
            if h is not None:
                ok += 1
                # shortest path avoiding dead nodes
                stretch += h / _shortest(sh, dead, s, t)
    return ok, tried, (stretch / ok if ok else 0.0), exhaustive


def _shortest(sh, dead, s, t):
    from collections import deque
    d = {s: 0}
    q = deque([s])
    while q:
        u = q.popleft()
        if u == t:
            return d[u]
        for w in sh.adj[u]:
            if w not in dead and w not in d:
                d[w] = d[u] + 1
                q.append(w)
    raise ValueError("not connected")


def main() -> int:
    t = P.build("8-cell")
    print("HOP on the 8-cell (oracle), every fault set of the size, every connected live pair")
    for f in range(0, 4):
        ok, n, st, _ = measure(t, lambda dead, s, tt: route_hop(L.HOP.oracle, dead, s, tt), f,
                               cap_sets=10**6, cap_pairs=10**6)
        print(f"   {f} dead nodes   delivered {ok:5}/{n:<5} = {100*ok/n:6.2f}%   mean stretch {st:.3f}")
    print("\nSTEP (oracle, no load), dead nodes up to degree - 1")
    for name in P.BUILDERS:
        sh = P.build(name)
        deg = len(sh.adj[0])
        for f in sorted({0, 1, 2, deg - 1}):
            if f > deg - 1:
                continue
            small = sh.V <= 24
            ok, n, st, ex = measure(sh, lambda dead, s, tt: route_step(sh, L.STEP.oracle, dead, s, tt), f,
                                    cap_sets=4000 if small else 60, cap_pairs=10**6 if small else 400)
            print(f"   {name:9} {f:2} dead   delivered {ok:5}/{n:<5} = {100*ok/n:6.2f}%   mean stretch {st:.3f}"
                  f"   {'exhaustive' if ex else 'sampled'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
