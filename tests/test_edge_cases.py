"""The routers mirror the brute-force group on edge cases (a quick version of `neo4d edge`)."""
import random

from neo4d import edge_cases as E


def test_edge_cases_quick():
    rng = random.Random(7)
    routers = E.kernels()
    _, a = E.ambiguity(routers, rng, per=20)
    _, c = E.contradictions(routers, rng, per=50)
    _, d = E.differential(routers, rng, n=3000)
    assert a == 0 and c == 0 and d == 0
