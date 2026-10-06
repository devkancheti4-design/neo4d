"""Does neo4d absorb the topology of a domain? The domain's topology here: the graph of its transformations - nodes are
tokens, an edge is a rewrite the domain allows (`<` -> `<=`) - and its invariants, connected components (separate
families of rewrites) and the first Betti number (independent cycles: E - V + C on the undirected graph).

    A  THE MUTATION DOMAIN - the true graph is known: the teacher's swap operators. ROR is the complete digraph on the
       six comparisons, AOR on the five arithmetic operators, ASR on the four assignment operators; LCR, BCR, BRK and
       NEG (`not` deleted / inserted) are single pairs. The swarm (RELATE v2, anchored relations, the domain's junk
       budget) is taught k lines; its active neurons' rewrites form the learned graph. Absorbed means equal.
       And the same graph read against the C domain - the canonical tokens make it one graph for both languages.
    B  REAL BUGS - the true graph is unknown. Does the learned graph stop growing as experience accumulates, and do
       different orders of the same bugs reach the same graph?

    python -m neo4d.kit_topology   -> results/KIT_TOPOLOGY.md
"""
from __future__ import annotations

import random
import statistics
import sys
from collections import defaultdict
from pathlib import Path

from neo4d import KERNELS, REPO
from neo4d import domain_mutation as D
from neo4d import relate_live as RL

EMPTY = "(none)"
KS = (10, 30, 100, 300, 1000, 3000, 10000)


def truth():
    e = set()
    for fam in (D.ROR, D.AOR, D.ASR, ["AND", "OR"], ["TRUE", "FALSE"], ["break", "continue"]):
        e |= {(a, b) for a in fam for b in fam if a != b}
    return e | {("NOT", EMPTY), (EMPTY, "NOT")}


def edge(k):
    """The rewrite a neuron makes, if it is one literal token becoming another (or appearing, or vanishing)."""
    old, new = k[1]
    i = 0
    while i < min(len(old), len(new)) and old[i] == new[i]:
        i += 1
    j = 0
    while j < min(len(old), len(new)) - i and old[-1 - j] == new[-1 - j]:
        j += 1
    o, n = old[i:len(old) - j], new[i:len(new) - j]
    if len(o) > 1 or len(n) > 1 or (not o and not n):
        return None
    lit = lambda t: not t.startswith(("$", "~", "@"))
    if any(not lit(t) for t in o + n):
        return None
    return (o[0] if o else EMPTY, n[0] if n else EMPTY)


def invariants(edges):
    und = {tuple(sorted(e)) for e in edges if e[0] != e[1]}
    nodes = {v for e in und for v in e}
    parent = {v: v for v in nodes}

    def find(v):
        while parent[v] != v:
            parent[v] = parent[parent[v]]
            v = parent[v]
        return v
    for a, b in und:
        parent[find(a)] = find(b)
    comps = len({find(v) for v in nodes})
    return dict(nodes=len(nodes), edges=len(edges), undirected=len(und), components=comps,
                betti=len(und) - len(nodes) + comps)


def mutation_part(law):
    T = truth()
    tinv = invariants(T)
    dom = D.Domain()
    rows = defaultdict(list)
    for seed in (0, 1, 2):
        train, test, held = D.split(dom, seed)
        order = random.Random(seed).sample(train, max(KS))
        for kk in KS:
            act = D.teach(dom, order[:kk], law, ("ctx",), costly_t=D.JUNK)
            E = {e for e in map(edge, act) if e}
            tok = {v for e in T for v in e}
            inside = E & T
            outside = {e for e in E - T if e[0] in tok and e[1] in tok}      # junk: between the domain's own tokens
            other = {e for e in E - T if e not in outside}                   # rewrites of other operators (RET's -> None)
            inv = invariants(inside)
            fams = {name: all((a, b) in E for a in f for b in f if a != b)
                    for name, f in (("ROR", D.ROR), ("AOR", D.AOR), ("ASR", D.ASR))}
            rows[kk].append(dict(recall=len(inside) / len(T), extra=len(outside), equal=inside == T and not outside,
                                 comps=inv["components"], betti=inv["betti"], fams=fams, outside=sorted(outside),
                                 other=sorted(other)))
        print(f"  mutation seed {seed} done", flush=True)
    return T, tinv, rows


def bug_part(law, kinds=("rel", "lit")):
    d = RL.prep()
    curves, finals = [], []
    for s in RL.SEEDS:
        level, nets, fires, good = defaultdict(int), defaultdict(set), defaultdict(int), defaultdict(int)
        N = RL.neurons(d, kinds)
        fan = {k: statistics.mean([n for n, _ in v[0] if n] or [0]) for k, v in N.items()}
        cheap = {k: fan[k] <= RL.CHEAP[0] and N[k][1] <= RL.CHEAP[1] for k in N}
        costly = {k: fan[k] > RL.COSTLY[0] or N[k][1] > RL.COSTLY[1] for k in N}
        bugs = RL.stream(d, s)
        marks = {int(len(bugs) * q / 10) - 1 for q in range(1, 11)}
        curve = []
        for b_i, bug in enumerate(bugs):
            before = dict(level)
            for i in bug:
                r = d["rows"][i]
                touch = {k for k, v in before.items() if v >= 1 and N[k][0][i][0]} | ({("rel", r["rel"]), ("lit", r["lit"])} & set(N))
                for k in touch:
                    L = level[k]
                    n_c, hit = N[k][0][i]
                    if before.get(k, 0) >= 2 and n_c:
                        fires[k] += 1
                        good[k] += hit
                    FIRE = int(k in {("rel", r["rel"]), ("lit", r["lit"])})
                    NEWNET = int(FIRE and r["proj"] not in nets[k])
                    PRED = int(before.get(k, 0) >= 1 and hit)
                    BAR = int(L >= 1 and fires[k] >= RL.BARREN_FIRES and good[k] / fires[k] < RL.BARREN_YIELD)
                    x = L | FIRE << 2 | NEWNET << 3 | PRED << 4 | int(cheap[k]) << 5 | int(costly[k]) << 6 | BAR << 7
                    level[k] = law(x) & 3
                    if FIRE:
                        nets[k].add(r["proj"])
            if b_i in marks:
                E = {e for e in (edge(k) for k, v in level.items() if v >= 2) if e}
                curve.append(invariants(E))
        curves.append(curve)
        finals.append({e for e in (edge(k) for k, v in level.items() if v >= 2) if e})
    jac = [len(a & b) / len(a | b) for i, a in enumerate(finals) for b in finals[i + 1:]]
    return curves, finals, jac


def main() -> int:
    law = RL.load_law(str(KERNELS / "relate_v2.c"))
    T, tinv, rows = mutation_part(law)
    curves, finals, jac = bug_part(law)
    m = lambda kk, f: statistics.mean(r[f] for r in rows[kk])
    out = ["# Does it absorb the topology of a domain?", "",
           "Generated by `neo4d/kit_topology.py`, the RELATE v2 law deciding. A domain's topology here is the graph of "
           "its transformations - tokens as nodes, each rewrite the domain allows as an edge - with its invariants: "
           "connected components (separate families of rewrites) and the first Betti number (independent cycles, "
           "E - V + C).", "",
           "## A. The mutation domain - the true graph is known", "",
           f"The teacher's swap operators: **{len(T)} directed edges, {tinv['nodes']} tokens, {tinv['components']} "
           f"components, Betti number {tinv['betti']}** (ROR the complete graph on 6 comparisons, AOR on 5 arithmetic "
           "operators, ASR on 4 assignment operators; `and`/`or`, `True`/`False`, `break`/`continue`, `not` and its "
           "absence). The learned graph: the rewrites of the swarm's active neurons, taught k standard-library lines, "
           "3 seeds.", "",
           "| taught lines | edges recovered | junk edges between the domain's tokens | components | Betti number | ROR / AOR / ASR complete | **learned graph = true graph** |",
           "|---|---|---|---|---|---|---|"]
    for kk in KS:
        fam = "/".join(f"{sum(r['fams'][f] for r in rows[kk])}/3" for f in ("ROR", "AOR", "ASR"))
        out.append(f"| {kk:,} | {m(kk, 'recall'):.0%} | {m(kk, 'extra'):.1f} | {m(kk, 'comps'):.1f} (true "
                   f"{tinv['components']}) | {m(kk, 'betti'):.1f} (true {tinv['betti']}) | {fam} seeds | "
                   f"**{sum(r['equal'] for r in rows[kk])} of 3 seeds** |")
    extra = sorted({e for kk in KS for r in rows[kk] for e in r["outside"]})
    other = sorted({e for kk in KS for r in rows[kk] for e in r["other"]})
    out += ["", "Junk edges between the domain's tokens, any seed, any k: " +
            (", ".join(f"`{a} -> {b}`" for a, b in extra[:12]) + (" ..." if len(extra) > 12 else "") if extra else
             "**none**") + ". Edges reaching other operators' tokens - not junk, the `return <value> -> return None` "
            "operator (RET), whose rewrite is abstract (any value becomes None) and so is left out of the true graph: " +
            (", ".join(f"`{a} -> {b}`" for a, b in other[:8]) if other else "none") + ".",
            "", "The graph is language-free: the canonical tokens (`&&` and `and` are both AND, `!` and `not` both NOT) "
            "make the C domain's swap graph the same 70 edges, so a graph absorbed from Python is the C graph too - "
            "which is why the swap operators carried to C with no C lesson (`results/DOMAIN_HARD.md`, E2).", "",
            "## B. Real bugs - the true graph is unknown", "",
            f"The learned graph of single-token rewrites as the swarm lives through the 706 small fixes (49 projects, "
            f"{len(RL.SEEDS)} orders of the same bugs averaged), measured at each tenth of the stream:", "",
            "| share of the stream | tokens | rewrite edges | components | Betti number |", "|---|---|---|---|---|"]
    for q in range(len(curves[0])):
        c = [cv[q] for cv in curves]
        out.append(f"| {(q + 1) * 10}% | {statistics.mean(x['nodes'] for x in c):.0f} | "
                   f"{statistics.mean(x['edges'] for x in c):.0f} | {statistics.mean(x['components'] for x in c):.0f} | "
                   f"{statistics.mean(x['betti'] for x in c):.0f} |")
    common = set.intersection(*finals)
    out += ["", f"Different orders of the same bugs end with graphs that overlap **{statistics.mean(jac):.0%}** "
            f"(Jaccard, mean over pairs); {len(common)} edges are in every one of the {len(finals)} final graphs.", "",
            "**What this shows.**"]
    first_equal = next((kk for kk in KS if all(r["equal"] for r in rows[kk])), None)
    first_rec = next((kk for kk in KS if m(kk, "recall") == 1.0), None)
    out += [f"- In a closed domain it does absorb the topology, exactly: by "
            f"{first_rec:,} taught lines every true edge is recovered in every seed" if first_rec else
            "- In the closed domain the true graph is not fully recovered at 10,000 taught lines",
            ("" if not first_rec else
             (f" and the learned graph equals the true one - same edges, {tinv['components']} components, Betti "
              f"number {tinv['betti']} - from {first_equal:,} lines on." if first_equal else
              ", but junk edges outside it keep the learned graph from equaling it."))]
    out[-2] = out[-2] + out[-1]
    out.pop()
    b0, b1 = curves[0][len(curves[0]) // 2], curves[0][-1]
    grow = statistics.mean(cv[-1]["edges"] for cv in curves) / max(1, statistics.mean(cv[len(cv) // 2]["edges"] for cv in curves))
    out += [f"- On real bugs the learned graph is still growing at the end of the corpus: from the middle of the "
            f"stream to its end its edges grow {grow:.2f}x. There is no settled topology to absorb yet at 706 fixes - "
            "the novelty measurement (`results/NOVELTY.md`) says how far the curve has to run.",
            "- It is a graph of rewrites, learned from tests - not geometry in any metric sense, and not the 4D "
            "polytopes the swarm once ran on."]
    (REPO / "results" / "KIT_TOPOLOGY.md").write_text("\n".join(out) + "\n")
    print("\n".join(out))
    return 0


if __name__ == "__main__":
    sys.exit(main())
