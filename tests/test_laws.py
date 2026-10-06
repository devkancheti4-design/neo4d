"""Every authored law, judged by enumeration - the same checks as `neo4d judge --quick`."""
import os

from neo4d import KERNELS, judge_harvest, judge_induce, judge_pick, judge_relate, judge_ship
from neo4d import judge_router5 as R5
from neo4d import judge_router4d as R4


def test_route4d_k3():
    k = R4.load(str(KERNELS / "router4d.c"), "route4d")
    assert R4.judge(k, "affine", 3, sample=3000) == 0


def test_route4d5_k5():
    k = R4.load(str(KERNELS / "router4d5.c"), "route4d5", 64)
    assert R4.judge(k, "affine", 5, sample=2000) == 0
    assert R4.harvest_shaped(k, "affine", 5, n=1000) == 0


def test_fluidfix_router_is_the_ring_law():
    assert R4.calibrate() == 0


def test_harvest():
    assert judge_harvest.main(str(KERNELS / "harvest.c")) == 0


def test_pick():
    assert judge_pick.report(judge_pick.load(str(KERNELS / "pick.c")), "pick.c") == 0


def test_induce():
    assert judge_induce.report(judge_induce.load(str(KERNELS / "induce.c")), "induce.c") == 0


def test_ship():
    assert judge_ship.report(judge_ship.load(str(KERNELS / "ship.c")), "ship.c") == 0


def test_route5_k6():
    t = R5.run(R5.build(KERNELS / "router5.c"), 800_000, os.cpu_count() or 8)
    assert R5.report(t, "router5.c") == 0


def test_relate_spec_is_complete():
    assert judge_relate.selfcheck() == 0


def test_relate():
    assert judge_relate.report(judge_relate.load(str(KERNELS / "relate_v1.c")), "relate_v1.c") == 0


def test_relate_v2_spec_is_complete():
    assert judge_relate.selfcheck(2) == 0


def test_relate_v2():
    assert judge_relate.report(judge_relate.load(str(KERNELS / "relate_v2.c"), "relate_v2"), "relate_v2.c", 2) == 0
