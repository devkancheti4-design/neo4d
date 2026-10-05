"""neo4d - command line.

    neo4d judge [--quick]     every authored law, judged by enumeration against its principles
    neo4d shapes              the six regular 4D polytopes, every invariant measured
    neo4d generalize          how far each 4D structure generalises (version space) -> results/GENERALIZE.md
    neo4d corpus              the 4D router on fluid-router's 33-bug corpus      -> results/CORPUS4D.md
    neo4d corpus-big          fluidfix's vocabulary renumbered 4D-natively, 1,566 real fixes -> results/CORPUS4D_BIG.md
    neo4d learn               the self-learning loop live on click: PICK chooses, HARVEST decides, route4d5 routes
    neo4d swarm               fluidnet's nets on a 4D shape (v1)                 -> results/RESULT.md
    neo4d realfix             real fix patches: BugsInPy, Defects4J, Defects4C  -> results/REALFIX.md
    neo4d replay              the routing laws replayed on the shapes with dead nodes
    neo4d edge                ambiguity matrix, contradiction injection, 200k differential vs brute force
    neo4d adversarial         ghost-space queries: neo4d against a guessing heuristic
    neo4d silicon             the router's machine code and hardware counters (IPC, branches, memory ops)
    neo4d quixbugs            QuixBugs repair, original and obfuscated (needs bench/)
    neo4d prompts             regenerate the swarm-law prompts

Everything that needs benchmark data reads bench/, fetched by scripts/fetch_bench.sh.
"""
from __future__ import annotations

import argparse
import sys


def judge_all(quick: bool) -> int:
    from neo4d import KERNELS, judge, judge_harvest, judge_induce, judge_pick, judge_router4d as R4

    total = 0
    rows = []

    def note(name, n):
        nonlocal total
        total += n
        rows.append((name, n))

    from neo4d import anchors
    anchors.attach()
    note("swarm laws: oracles + principles fix every table (judge.py --selftest)", judge.selftest())
    note("fluidfix's own router, as the ring law (calibration)", R4.calibrate())
    k3 = R4.load(str(KERNELS / "router4d.c"), "route4d")
    n = R4.judge(k3, "affine", 3, sample=3000 if quick else 30000)
    if not quick:
        n += R4.reduced(k3, "affine", 3)
    note("route4d   (affine GF(2)^4, k = 3)", n)
    k5 = R4.load(str(KERNELS / "router4d5.c"), "route4d5", 64)
    n = R4.judge(k5, "affine", 5, sample=5000 if quick else 200000)
    n += R4.harvest_shaped(k5, "affine", 5, n=3000 if quick else 50000)
    note("route4d5  (affine GF(2)^4, k = 5, 64-bit)", n)
    note("harvest", judge_harvest.main(str(KERNELS / "harvest.c")))
    note("pick", judge_pick.report(judge_pick.load(str(KERNELS / "pick.c")), "pick.c"))
    note("induce", judge_induce.report(judge_induce.load(str(KERNELS / "induce.c")), "induce.c"))
    print("\n  ================= neo4d judge =================")
    for name, n in rows:
        print(f"  {name:70} {'PASS' if n == 0 else f'{n} violations'}")
    print(f"\n  ALL LAWS: {'0 violations' if total == 0 else f'{total} violations'}")
    return int(total != 0)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="neo4d", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    j = sub.add_parser("judge")
    j.add_argument("--quick", action="store_true")
    for name in ("shapes", "generalize", "corpus", "corpus-big", "learn", "swarm", "realfix", "replay", "prompts", "edge", "adversarial", "silicon", "quixbugs"):
        sub.add_parser(name)
    a, rest = ap.parse_known_args(argv)
    if a.cmd == "judge":
        return judge_all(a.quick)
    mod = {"shapes": "polytopes", "generalize": "generalize", "corpus": "corpus4d", "corpus-big": "corpus4d_big",
           "learn": "harvest_pick", "swarm": "experiment", "realfix": "realfix", "replay": "replay",
           "prompts": "make_prompts", "edge": "edge_cases", "adversarial": "adversarial", "silicon": "silicon", "quixbugs": "quixbugs"}[a.cmd]
    import importlib
    m = importlib.import_module(f"neo4d.{mod}")
    sys.argv = [f"neo4d {a.cmd}"] + rest
    return m.main() or 0


if __name__ == "__main__":
    sys.exit(main())
