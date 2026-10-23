"""neo4d's domain-free core on two non-code domains: the checkers are right, neo4d's variants repair a near-miss,
memory replays a verified pattern on a new task of the same shape, and the core contains no domain."""
from neo4d import core as C
from neo4d import relate_live as RL
from neo4d import KERNELS
from neo4d.domains.blocks import Blocks, run
from neo4d.domains.countdown import Countdown


def test_countdown_checker_and_variants():
    d = Countdown()
    for t in d.tasks(30, 7):
        assert d.check(t, d.parse(t, t["_witness"]))[0]
        assert not d.check(t, d.start(t))[0] or eval(d.start(t)) == t["target"]
    t = d.tasks(1, 3)[0]
    w = d.parse(t, t["_witness"])
    i = next(k for k, ch in enumerate(w) if ch in "+-*")                # change the first operator to a wrong one
    broken = next(w[:i] + op + w[i + 1:] for op in "+-*" if op != w[i] and not d.check(t, w[:i] + op + w[i + 1:])[0])
    assert not d.check(t, broken)[0]
    assert any(d.check(t, v)[0] for v in d.variants(t, broken))
    assert d.check(t, d.instantiate(t, d.abstract(t, w)))[0]


def test_blocks_checker_and_variants():
    d = Blocks()
    for t in d.tasks(40, 7):
        assert d.check(t, t["_witness"])[0]
        assert not d.check(t, ())[0]
    t = next(t for t in d.tasks(40, 8) if len(t["_witness"]) >= 3)
    w = t["_witness"]
    assert run(t["init"], ((w[-1][0], "nowhere"),))[1] == 0
    near = w[:1] + w[2:]                                     # one move missing
    assert any(d.check(t, v)[0] for v in d.variants(t, near))
    assert d.check(t, d.instantiate(t, d.abstract(t, w)))[0]


def test_memory_replays_on_a_new_task_of_the_same_shape(monkeypatch):
    d = Blocks()
    tasks = [t for t in d.tasks(200, 5) if t["kind"] == "reverse" and len(t["init"]) == 4][:3]
    assert len(tasks) == 3 and len({d.key(t) for t in tasks}) == 1
    monkeypatch.setattr(C, "generate", lambda model, prompt, temperature, seed, stats, predict=400:
                        (stats.__setitem__("calls", stats["calls"] + 1),
                         "\n".join(f"move {b} onto {x}" for b, x in tasks[[t["order"][0] in prompt for t in tasks].index(True)]["_witness"]))[1])
    mem = C.Memory(RL.load_law(str(KERNELS / "relate_v2.c")))
    first = C.solve(d, tasks[0], "fake", "core", mem)
    second = C.solve(d, tasks[1], "fake", "core", mem)
    assert first["how"] == "model" and first["calls"] == 1
    assert second["how"] == "memory" and second["calls"] == 0


def test_the_core_names_no_domain():
    src = (C.__file__ and open(C.__file__).read()).lower()
    assert "countdown" not in src and "blocks" not in src


def test_arc_adapter_finds_a_transformation_and_scores_the_hidden_test():
    from neo4d.domains.arc import Arc
    d = Arc()
    t = dict(id="t", train=[(((1, 2), (3, 4)), ((2, 1), (4, 3))), (((5, 0), (0, 6)), ((0, 5), (6, 0)))],
             test=[(((7, 8), (9, 1)), ((8, 7), (1, 9)))])
    r = C.solve(d, t, None, "search", checks=500)
    assert r["solved"] and d.solves_test(t, r["solution"])
    assert not d.solves_test(t, ())                                   # the identity does not
