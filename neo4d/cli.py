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
    neo4d robustness          noise around the query, other encodings, a million calls in one process
    neo4d exact               neo4d by exact math: closed forms over the group, checked against brute force
    neo4d inductive           shard test, sample-efficiency shootout vs MLP/Transformer, active vs passive, OOD
    neo4d degeneracy          rank-2 redundant examples, one-bit contradictions, validation points k = 5..8
    neo4d induce-live         INDUCE replayed on click's history: the learning curve
    neo4d kit-scaling | kit-language | kit-outage | kit-federation | kit-proof     the kit's five directions
    neo4d router5-math        the 32-kind router's numbers, exact               -> results/ROUTER5_MATH.md
    neo4d router5-live        route5 live at 32 kinds: federation, degeneracy, adversary -> results/ROUTER5_LIVE.md
    neo4d relations           fix relations on real bugs: the generalisation ceiling  -> results/RELATIONS.md
    neo4d relate-live         a swarm learning relations like neurons [--spec | law.c] -> results/RELATE_LIVE.md
    neo4d domain-mutation     a whole domain taught: code mutation on the standard library -> results/DOMAIN_MUTATION.md
    neo4d domain-hard         harder data: new codebases, C / C++ / Java, harder operators, a noisy teacher -> results/DOMAIN_HARD.md
    neo4d relate-v2           the RELATE v2 law judged and run live, beside v1 -> results/RELATE_V2.md
    neo4d kit-topology        does it absorb a domain's topology? the rewrite graph learned vs the true one -> results/KIT_TOPOLOGY.md
    neo4d repeats             how well repeats are handled: exact, generalised, novel -> results/REPEATS.md
    neo4d proof-grows         proof that it mutates and its knowledge grows -> results/PROOF_GROWS.md
    neo4d proof-hard          the same proof on C, C++, Java, harder operators, a noisy teacher -> results/PROOF_HARD.md
    neo4d proof-js            the proof on JavaScript: a codebase and new topics -> results/PROOF_JS.md
    neo4d proof-closed        can it replace a model in a closed domain? exact answers line by line -> results/PROOF_CLOSED.md
    neo4d local-model         a local model (ollama) with neo4d as its brain [--model phi4-mini] [--compare answers.json]
                              -> results/LOCAL_MODEL.md, results/LOCAL_MODEL_VS_CLAUDE.md
    neo4d local-agent         a local model doing multi-step work like Claude, neo4d as its brain [--model phi4-mini]
                              [--claude-score answers.json] [--agent-score sonnet,haiku] -> results/LOCAL_AGENT.md
    neo4d local-hints         bugs a small model never solved: neo4d mutates, the model gets the evidence -> results/LOCAL_HINTS.md
    neo4d novelty             does novelty die? new-pattern rate on bugs, click and the mutation domain -> results/NOVELTY.md
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
    from neo4d import judge_ship, judge_router5 as R5
    note("ship", judge_ship.report(judge_ship.load(str(KERNELS / "ship.c")), "ship.c"))
    import os
    t = R5.run(R5.build(KERNELS / "router5.c"), 800_000 if quick else 16_000_000, os.cpu_count() or 8)
    note("route5    (GL(5,2), 32 kinds, k = 6; the CBMC proof: judge_router5 --prove)", R5.report(t, "router5.c"))
    from neo4d import judge_relate
    note("relate v1", judge_relate.report(judge_relate.load(str(KERNELS / "relate_v1.c")), "relate_v1.c"))
    note("relate v2", judge_relate.report(judge_relate.load(str(KERNELS / "relate_v2.c"), "relate_v2"), "relate_v2.c", 2))
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
    for name in ("shapes", "generalize", "corpus", "corpus-big", "learn", "swarm", "realfix", "replay", "prompts", "edge", "adversarial", "silicon", "quixbugs", "robustness", "exact", "inductive", "degeneracy", "induce-live", "kit-scaling", "kit-language", "kit-outage", "kit-federation", "kit-proof", "router5-math", "router5-live", "relations", "relate-live", "domain-mutation", "domain-hard", "novelty", "relate-v2", "kit-topology", "repeats", "proof-grows", "proof-hard", "proof-js", "proof-closed", "local-model", "local-agent", "local-hints"):
        sub.add_parser(name)
    a, rest = ap.parse_known_args(argv)
    if a.cmd == "judge":
        return judge_all(a.quick)
    mod = {"shapes": "polytopes", "generalize": "generalize", "corpus": "corpus4d", "corpus-big": "corpus4d_big",
           "learn": "harvest_pick", "swarm": "experiment", "realfix": "realfix", "replay": "replay",
           "prompts": "make_prompts", "edge": "edge_cases", "adversarial": "adversarial", "silicon": "silicon", "quixbugs": "quixbugs", "robustness": "robustness", "exact": "exactmath", "inductive": "inductive", "degeneracy": "degeneracy", "induce-live": "induce_live", "kit-scaling": "kit_scaling", "kit-language": "kit_language", "kit-outage": "kit_outage", "kit-federation": "kit_federation", "kit-proof": "kit_proof", "router5-math": "router5_math", "router5-live": "router5_live", "relations": "relations", "relate-live": "relate_live", "domain-mutation": "domain_mutation", "novelty": "novelty", "domain-hard": "domain_hard", "relate-v2": "relate_v2_check", "kit-topology": "kit_topology", "repeats": "repeats", "proof-grows": "proof_grows", "proof-hard": "proof_hard", "proof-js": "proof_js", "proof-closed": "proof_closed", "local-model": "local_model", "local-agent": "local_agent", "local-hints": "local_hints"}[a.cmd]
    import importlib
    m = importlib.import_module(f"neo4d.{mod}")
    sys.argv = [f"neo4d {a.cmd}"] + rest
    return m.main() or 0


if __name__ == "__main__":
    sys.exit(main())
