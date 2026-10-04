"""The experiment: does putting fluidnet's nets on a 4D shape help?

    python3 experiment.py [--jobs N] [--laws laws/]      writes results/RESULT.md and results/raw.json

E1  COMPOSITION  jobs whose faults need taught classes from k different dictionaries (+ one shipped fault).
                 static fluidnet vs the star+carry control vs the shape.
E2  TRAFFIC      the same jobs, decentralised: hops per job and the busiest node's share of all messages -
                 the shape against a ring and a random regular graph with the same nodes and links, and
                 against the overseer of the star.
E3  RESILIENCE   dead nets. fluidnet as built (one net per dictionary) vs the shape with antipodal mirrors vs
                 the same shape with mirrors paired at random - independent failures, and a local outage
                 (a node and every neighbour of it).

Every number is a count over generated jobs, seeded; nothing is tuned per job.
"""
from __future__ import annotations

import argparse
import json
import os
import random
import statistics as st
import sys
import time
import zlib

from neo4d import classes as C
from neo4d import jobs as J
from neo4d import swarm as S

SHAPES = ["5-cell", "16-cell", "8-cell", "24-cell", "600-cell"]


def _seed(*parts) -> int:
    """Stable across processes - Python's hash() of a str is salted per run."""
    return zlib.crc32(repr(parts).encode())


def setup(g: S.Graph, mirrored: bool):
    partner = g.partner if mirrored else None
    cap = S.capacity(g, mirrored) if mirrored else g.V * C.SLOTS_TAUGHT
    taught = C.taught(cap)
    shipped = C.shipped()
    pl = S.place(g, taught, partner)
    by = {c.name: c for c in shipped + taught}
    return pl, shipped, by


def jobs_for(pl, by, k: int, n: int, seed: int):
    rng = random.Random(seed)
    names_shipped = [c for c in by if not c.startswith(("rename-", "len-", "wrong-"))]
    out = []
    while len(out) < n:
        ds = rng.sample(range(len(pl.dictionaries)), min(k, len(pl.dictionaries)))
        faults = [rng.choice(pl.dictionaries[d]).name for d in ds] + [rng.choice(names_shipped)]
        distract = [rng.choice(list(by)) for _ in range(3)]
        distract = [d for d in distract if d not in faults]
        out.append((J.make_job(faults, distract, rng, by), rng.randrange(10**9)))
    return out


def summarise(rs):
    ok = [r for r in rs if r.repaired]
    return {"repaired": len(ok), "n": len(rs),
            "runs": st.mean(r.runs for r in rs), "runs_ok": st.mean(r.runs for r in ok) if ok else 0,
            "visits": st.mean(r.nets for r in rs), "hops": st.mean(r.hops for r in rs)}


def e1(n_jobs: int):
    rows = []
    for name in SHAPES:
        g = S.polytope(name)
        mirrored = g.partner is not None
        pl, shipped, by = setup(g, mirrored)
        for k in (1, 2, 3):
            js = jobs_for(pl, by, k, n_jobs, seed=_seed(name, k))
            res = {"static": [], "star+carry": [], "shape": []}
            for job, s in js:
                res["static"].append(S.static(job, pl, shipped))
                res["star+carry"].append(S.static(job, pl, shipped, carry=True))
                res["shape"].append(S.shape(job, g, pl, shipped, entry=s % g.V))
            for mode, rs in res.items():
                rows.append({"shape": name, "nets": g.V, "dictionaries": len(pl.dictionaries), "k": k,
                             "mode": mode, **summarise(rs)})
            print(f"  E1 {name:9} k={k}  " + "  ".join(
                f"{m} {sum(r.repaired for r in rs)}/{len(rs)}" for m, rs in res.items()), flush=True)
    return rows


def e2(n_jobs: int):
    rows = []
    for name in ["16-cell", "8-cell", "24-cell", "600-cell"]:
        g = S.polytope(name)
        deg = len(g.adj[0])
        graphs = [g, S.ring(g.V), S.random_regular(g.V, deg, seed=11)]
        base_pl, shipped, by = setup(g, True)
        js = jobs_for(base_pl, by, 3, n_jobs, seed=_seed(name, "e2"))
        for gg in graphs:
            pl = S.place(gg, C.taught(S.capacity(g, True)), gg.partner)
            pl.dictionaries = base_pl.dictionaries            # same knowledge, different wiring
            rs, load = [], {}
            for job, s in js:
                r = S.shape(job, gg, pl, shipped, entry=s % gg.V)
                rs.append(r)
                for v, m in r.load.items():
                    load[v] = load.get(v, 0) + m
            total = sum(load.values()) or 1
            rows.append({"family": name, "graph": gg.name, "nodes": gg.V, "links": deg if gg is not graphs[1] else 2,
                         "diameter": int(gg.dist.max()), **summarise(rs),
                         "busiest_share": max(load.values()) / total if load else 0})
        # the star: every message passes the overseer
        rs = [S.static(job, base_pl, shipped, carry=True) for job, _ in js]
        rows.append({"family": name, "graph": "star (overseer)", "nodes": g.V + 1, "links": g.V,
                     "diameter": 2, **summarise(rs), "busiest_share": 0.5})
        print(f"  E2 {name} done", flush=True)
    return rows


def e3(n_jobs: int):
    """Single-fault jobs (one taught + one shipped), so every arm repairs everything when nothing is dead -
    what changes below is resilience alone."""
    rows = []
    for name in ["16-cell", "8-cell", "24-cell", "600-cell"]:
        g = S.polytope(name)
        deg = len(g.adj[0])
        pl_anti, shipped, by = setup(g, True)
        rp = S.random_partner(g, seed=5)
        pl_rand = S.place(g, C.taught(S.capacity(g, True)), rp)
        pl_rand.dictionaries = pl_anti.dictionaries
        # each dictionary on ONE net (its home), no copy - fluidnet as built, and the shape without mirrors
        pl_one = S.single_copy(pl_anti, g.V)
        js = jobs_for(pl_anti, by, 1, n_jobs, seed=_seed(name, "e3"))
        rng = random.Random(99)
        scenarios = [("none dead", 0), ("1 dead", 1), ("2 dead", 2), (f"{deg - 1} dead", deg - 1),
                     ("local outage", "local")]
        arms = ("fluidnet as built", "shape, no copies", "shape, antipodal mirror", "shape, random mirror")
        for label, f in scenarios:
            res = {a: [] for a in arms}
            for job, s in js:
                if f == "local":
                    c = rng.randrange(g.V)
                    dead = {c, *g.adj[c]}
                else:
                    dead = set(rng.sample(range(g.V), f)) if f else set()
                live = [v for v in range(g.V) if v not in dead]
                entry = live[s % len(live)]
                res[arms[0]].append(S.static(job, pl_one, shipped, dead=dead))
                res[arms[1]].append(S.shape(job, g, pl_one, shipped, entry, dead))
                res[arms[2]].append(S.shape(job, g, pl_anti, shipped, entry, dead))
                res[arms[3]].append(S.shape(job, g, pl_rand, shipped, entry, dead))
            for mode, rs in res.items():
                rows.append({"shape": name, "scenario": label, "mode": mode, **summarise(rs)})
            print(f"  E3 {name:9} {label:13} " + "  ".join(
                f"{sum(r.repaired for r in rs)}/{len(rs)}" for m, rs in res.items()), flush=True)
    return rows


def report(r1, r2, r3, n_jobs, laws_used, seconds) -> str:
    out = ["# fluidnet on a 4D shape - result", "",
           f"Generated by `experiment.py` ({n_jobs} jobs per cell, seeded; {seconds:.0f} s). Laws: "
           + (", ".join(laws_used) if laws_used else "the reference oracles in `laws.py` (the superoptimizer's "
              "kernels replace them once judged)") + ".", ""]
    out += ["## E1 - composition: faults whose taught classes live in k different nets (+1 shipped fault)", "",
            "| shape | nets | dictionaries | k | static fluidnet | star+carry | shape | suite runs (static / carry / shape) | nets visited (static / carry / shape) |",
            "|---|---|---|---|---|---|---|---|---|"]
    by = {}
    for r in r1:
        by.setdefault((r["shape"], r["k"]), {})[r["mode"]] = r
    for (shape, k), m in by.items():
        s, c, h = m["static"], m["star+carry"], m["shape"]
        out.append(f"| {shape} | {s['nets']} | {s['dictionaries']} | {k} | {s['repaired']}/{s['n']} | "
                   f"{c['repaired']}/{c['n']} | {h['repaired']}/{h['n']} | "
                   f"{s['runs']:.0f} / {c['runs']:.0f} / {h['runs']:.0f} | "
                   f"{s['visits']:.1f} / {c['visits']:.1f} / {h['visits']:.1f} |")
    out += ["", "## E2 - traffic: same jobs (k = 3), same dictionaries, different wiring", "",
            "| family | graph | nodes | links each | diameter | repaired | hops per job | busiest node's share of messages |",
            "|---|---|---|---|---|---|---|---|"]
    for r in r2:
        out.append(f"| {r['family']} | {r['graph']} | {r['nodes']} | {r['links']} | {r['diameter']} | "
                   f"{r['repaired']}/{r['n']} | {r['hops']:.2f} | {100*r['busiest_share']:.1f}% |")
    out += ["", "## E3 - resilience: dead nets (single-fault jobs: one taught + one shipped)", "",
            "| shape | scenario | fluidnet as built | shape, no copies | shape, antipodal mirror | shape, random mirror |",
            "|---|---|---|---|---|---|"]
    by = {}
    for r in r3:
        by.setdefault((r["shape"], r["scenario"]), {})[r["mode"]] = r
    for (shape, sc), m in by.items():
        cells = [f"{m[k]['repaired']}/{m[k]['n']}" for k in
                 ("fluidnet as built", "shape, no copies", "shape, antipodal mirror", "shape, random mirror")]
        out.append(f"| {shape} | {sc} | " + " | ".join(cells) + " |")
    return "\n".join(out) + "\n"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--jobs", type=int, default=60)
    ap.add_argument("--laws", default=None, help="folder of judged kernels (hop.c, step.c, mirror.c, ...)")
    a = ap.parse_args(argv)
    laws_used = S.load_laws(a.laws) if a.laws else []
    t = time.time()
    r1 = e1(a.jobs)
    r2 = e2(a.jobs)
    r3 = e3(a.jobs)
    os.makedirs("results", exist_ok=True)
    with open("results/raw.json", "w") as fh:
        json.dump({"e1": r1, "e2": r2, "e3": r3}, fh, indent=1)
    md = report(r1, r2, r3, a.jobs, laws_used, time.time() - t)
    with open("results/RESULT.md", "w") as fh:
        fh.write(md)
    print("\n" + md)
    return 0


if __name__ == "__main__":
    sys.exit(main())
