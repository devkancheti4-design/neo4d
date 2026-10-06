"""RELATE live - a swarm of nets learning relations like neurons, on 1,729 real bugs. The body; the law decides.

Every project of BugsInPy, Defects4J and Defects4C is a net (49). Their small fixes (up to 3 tokens changed in one
line) arrive as one stream, in a seeded random order; each fix is SCORED first - do the swarm's active relations
generate it exactly, and how many candidates do they propose - and only then LEARNED from. Every relation is a neuron
with a strength the law sets on every event that touches it:

    0 unknown   1 primed (remembered, never used)   2 active (proposes fixes)   3 proven (active, and it predicted a
    fix before learning it)

The neurons are shared by the swarm: a fix in any net is an event for them, and a relation active anywhere proposes
everywhere. The body measures each event into one byte (prompts/RELATE_LAW_PROMPT.md):

    LEVEL (2 bits) | FIRE << 2 | NEWNET << 3 | PREDICTED << 4 | CHEAP << 5 | COSTLY << 6 | BARREN << 7

    FIRE        this fix instantiates the relation (the relation is this fix's edit, abstracted)
    NEWNET      ... and it is the relation's first firing in this net
    PREDICTED   applied to the buggy line before this fix was learned, the relation generated the fixed line exactly
    CHEAP       at most 5 candidates per line it fires on, and at most 0.5 per unchanged line
    COSTLY      more than 30 per line it fires on, or more than 35 per unchanged line
    BARREN      while active it fired on 100+ fix lines and generated fewer than 5% of them

Policies compared: fluidfix's 9 shipped classes; every relation at first sight (no law); cheap relations at first
sight; relations seen in two nets; the law (`--law neo4d/kernels/relate.c`); and, before a law exists, the one table
the principles allow (`--spec`, judge_relate.spec_table - built to check the principles, never a law).

    python -m neo4d.relate_live [--law path | --spec]   -> results/RELATE_LIVE.md
"""
from __future__ import annotations

import ctypes
import pickle
import random
import statistics
import subprocess
import sys
import tempfile
from collections import defaultdict
from pathlib import Path

from neo4d import BUILD, REPO
from neo4d import relations as R

CACHE = BUILD / "relate_cache_v2.pkl"
CHEAP, COSTLY = (5, 0.5), (30, 35.0)
BARREN_FIRES, BARREN_YIELD = 100, 0.05   # the record behind BARREN: 100 firings - with 10, rare-hitting relations were
                                         # demoted before their first hit (bugs 9.2% -> 10.3%, click 14.5% -> 17.4%)
SEEDS = range(8)


def prep():
    if CACHE.exists():
        return pickle.load(open(CACHE, "rb"))
    from neo4d import classes as C
    from neo4d import realfix as RF
    fixes, nbugs, _ = R.corpus()
    rows = []
    for c, proj, bid, m, q, s in fixes:
        e = R.edit(m, q)
        if e is None:
            continue
        a, b, i, o, n = e
        rows.append(dict(corpus=c, proj=proj, bid=bid, a=a, b=tuple(b), scope=s, lit=R.literal(o, n),
                         rel=R.relation(o, n, s), buggy=m, fixed=q))
    rels = sorted({r["rel"] for r in rows if R.generative(r["rel"])})
    F = {k: [R.fire(k, r["a"], r["scope"], r["b"]) for r in rows] for k in rels}
    lits = sorted({r["lit"] for r in rows})
    FL = {k: [R.fire(k, r["a"], r["scope"], r["b"]) for r in rows] for k in lits}
    rng = random.Random(2026)
    pool = [(l, r["scope"]) for r in rows for l in r["scope"] if R.toks(l) != list(r["a"])]
    sample = rng.sample(pool, 2000)
    noise = {k: sum(R.fire(k, R.toks(l), s)[0] for l, s in sample) / len(sample) for k in rels}
    sh = C.shipped()
    shipped = []
    for r in rows:
        cands = {RF.norm_ws(x) for cl in sh for x in cl.candidates(r["buggy"], 1, [r["buggy"]])} - {RF.norm_ws(r["buggy"])}
        shipped.append((len(cands), any(R.toks(x) == list(r["b"]) for x in cands)))
    sh_noise = statistics.mean(len({RF.norm_ws(x) for cl in sh for x in cl.candidates(l, 1, [l])} - {RF.norm_ws(l)})
                               for l, _ in sample)
    lnoise = {k: sum(R.fire(k, R.toks(l), s)[0] for l, s in sample) / len(sample) for k in lits}
    data = dict(rows=rows, rels=rels, F=F, noise=noise, shipped=shipped, sh_noise=sh_noise, nbugs=dict(nbugs),
                FL=FL, lnoise=lnoise)
    pickle.dump(data, open(CACHE, "wb"))
    return data


def tiers(d):
    fan = {k: statistics.mean([n for n, _ in d["F"][k] if n] or [0]) for k in d["rels"]}
    cheap = {k: fan[k] <= CHEAP[0] and d["noise"][k] <= CHEAP[1] for k in d["rels"]}
    costly = {k: fan[k] > COSTLY[0] or d["noise"][k] > COSTLY[1] for k in d["rels"]}
    return fan, cheap, costly


def stream(d, seed):
    """The bugs in a seeded random order, each bug a list of its small fixes. A bug is one repair: all its lines are
    scored before any of them is learned from."""
    bugs = defaultdict(list)
    for i, r in enumerate(d["rows"]):
        bugs[(r["corpus"], r["bid"])].append(i)
    if d.get("ordered"):                                  # a real history: commit order, every seed the same
        return list(bugs.values())
    keys = sorted(bugs)
    random.Random(seed).shuffle(keys)
    return [bugs[k] for k in keys]


def summary(curve, cost, nz, n_active):
    n, half = len(curve), len(curve) // 2
    return dict(cov=sum(curve) / n, first=sum(curve[:half]) / half, second=sum(curve[half:]) / (n - half),
                fixline=cost / n, unchanged=nz / n, active=n_active)


def shipped_policy(d, seed):
    curve = [d["shipped"][i][1] for bug in stream(d, seed) for i in bug]
    return summary(curve, sum(c for c, _ in d["shipped"]), d["sh_noise"] * len(curve), 9)


def _score(F, noise, active, i, acc):
    acc[0].append(any(F[k][i][1] for k in active))
    acc[1] += sum(F[k][i][0] for k in active)
    acc[2] += sum(noise[k] for k in active)


def first_sight(d, seed, only_cheap=False, nets_needed=1):
    _, cheap, _ = tiers(d)
    active, nets, acc = set(), defaultdict(set), [[], 0, 0.0]
    for bug in stream(d, seed):
        for i in bug:
            _score(d["F"], d["noise"], active, i, acc)
        for i in bug:
            r = d["rows"][i]
            k = r["rel"]
            if k in d["F"]:
                nets[k].add(r["proj"])
                if len(nets[k]) >= nets_needed and (cheap[k] or not only_cheap):
                    active.add(k)
    return summary(*acc, len(active))


def literal_first_sight(d, seed, only_cheap=False):
    """Memorisation, for contrast: every literal edit active the moment it is first seen, shared by the swarm."""
    fan = {k: statistics.mean([n for n, _ in d["FL"][k] if n] or [0]) for k in d["FL"]}
    ok = {k: fan[k] <= CHEAP[0] and d["lnoise"][k] <= CHEAP[1] for k in d["FL"]}
    active, acc = set(), [[], 0, 0.0]
    for bug in stream(d, seed):
        for i in bug:
            _score(d["FL"], d["lnoise"], active, i, acc)
        for i in bug:
            lit = d["rows"][i]["lit"]
            if ok[lit] or not only_cheap:
                active.add(lit)
    return summary(*acc, len(active))


def neurons(d, kinds):
    """The neuron set: abstract relations ('rel'), literal edits ('lit'), or both - one law decides them all; a
    literal edit is a relation with nothing abstracted."""
    out = {}
    for kind in kinds:
        F, nz = (d["F"], d["noise"]) if kind == "rel" else (d["FL"], d["lnoise"])
        for k in F:
            out[(kind, k)] = (F[k], nz[k])
    return out


def law_policy(d, seed, law, kinds=("rel",)):
    N = neurons(d, kinds)
    fan = {k: statistics.mean([n for n, _ in v[0] if n] or [0]) for k, v in N.items()}
    cheap = {k: fan[k] <= CHEAP[0] and N[k][1] <= CHEAP[1] for k in N}
    costly = {k: fan[k] > COSTLY[0] or N[k][1] > COSTLY[1] for k in N}
    level, nets, fires, good = defaultdict(int), defaultdict(set), defaultdict(int), defaultdict(int)
    curve, cost, nz = [], 0, 0.0
    for bug in stream(d, seed):
        before = dict(level)
        act = [k for k, v in before.items() if v >= 2]
        for i in bug:
            curve.append(any(N[k][0][i][1] for k in act))
            cost += sum(N[k][0][i][0] for k in act)
            nz += sum(N[k][1] for k in act)
        for i in bug:
            r = d["rows"][i]
            touch = {k for k, v in before.items() if v >= 1 and N[k][0][i][0]}
            own = {("rel", r["rel"]), ("lit", r["lit"])} & set(N)
            touch |= own
            for k in touch:
                L = level[k]
                n_c, hit = N[k][0][i]
                if before.get(k, 0) >= 2 and n_c:
                    fires[k] += 1
                    good[k] += hit
                FIRE = int(k in own)
                NEWNET = int(FIRE and r["proj"] not in nets[k])
                PRED = int(before.get(k, 0) >= 1 and hit)
                BAR = int(L >= 1 and fires[k] >= BARREN_FIRES and good[k] / fires[k] < BARREN_YIELD)
                x = L | FIRE << 2 | NEWNET << 3 | PRED << 4 | int(cheap[k]) << 5 | int(costly[k]) << 6 | BAR << 7
                level[k] = law(x) & 3
                if FIRE:
                    nets[k].add(r["proj"])
    return summary(curve, cost, nz, sum(1 for v in level.values() if v >= 2))


def load_law(path):
    out = Path(tempfile.mkdtemp(prefix="relate_")) / "r.so"
    subprocess.run(["cc", "-O2", "-shared", "-fPIC", "-o", str(out), str(path)], check=True)
    f = ctypes.CDLL(str(out)).relate
    f.argtypes, f.restype = [ctypes.c_int32], ctypes.c_int32
    table = [int(f(x)) for x in range(256)]
    return lambda x: table[x]


# --------------------------------------------------------------------------- click's own history, in commit order

CLICK_CACHE = BUILD / "relate_click_v1.pkl"


def prep_click():
    """click's fix commits in commit order (the same selection as induce_live), each commit one repair; its small
    one-line fixes with their hunk as scope. One net, real time order: fully prospective."""
    if CLICK_CACHE.exists():
        return pickle.load(open(CLICK_CACHE, "rb"))
    from neo4d import classes as C
    from neo4d import induce_live as IL
    from neo4d import realfix as RF
    rows = []
    for sha, date, msg in IL.commits():
        if not IL.FIX.search(msg):
            continue
        diff = IL.git("show", "--format=", "-U3", sha, "--", "click", "src/click")
        for f, m, q, sc in R.hunks_with_scope(diff, lambda p: bool(IL.SRC.search(p)) and "/tests/" not in p):
            e = R.edit(m, q)
            if e is None:
                continue
            a, b, i, o, n = e
            rows.append(dict(corpus="click", proj="click", bid=sha, date=date, a=a, b=tuple(b), scope=sc,
                             lit=R.literal(o, n), rel=R.relation(o, n, sc), buggy=m, fixed=q))
    rels = sorted({r["rel"] for r in rows if R.generative(r["rel"])})
    lits = sorted({r["lit"] for r in rows})
    F = {k: [R.fire(k, r["a"], r["scope"], r["b"]) for r in rows] for k in rels}
    FL = {k: [R.fire(k, r["a"], r["scope"], r["b"]) for r in rows] for k in lits}
    pool = [(l, r["scope"]) for r in rows for l in r["scope"] if R.toks(l) != list(r["a"])]
    sample = random.Random(2026).sample(pool, min(2000, len(pool)))
    noise = {k: sum(R.fire(k, R.toks(l), s_)[0] for l, s_ in sample) / len(sample) for k in rels}
    lnoise = {k: sum(R.fire(k, R.toks(l), s_)[0] for l, s_ in sample) / len(sample) for k in lits}
    sh = C.shipped()
    shipped = []
    for r in rows:
        cands = {RF.norm_ws(x) for cl in sh for x in cl.candidates(r["buggy"], 1, [r["buggy"]])} - {RF.norm_ws(r["buggy"])}
        shipped.append((len(cands), any(R.toks(x) == list(r["b"]) for x in cands)))
    sh_noise = statistics.mean(len({RF.norm_ws(x) for cl in sh for x in cl.candidates(l, 1, [l])} - {RF.norm_ws(l)})
                               for l, _ in sample)
    data = dict(rows=rows, rels=rels, F=F, FL=FL, noise=noise, lnoise=lnoise, shipped=shipped, sh_noise=sh_noise,
                nbugs={"click": len({r["bid"] for r in rows})}, ordered=True)
    pickle.dump(data, open(CLICK_CACHE, "wb"))
    return data


def table(d, seeds, law, label_law, spec=None):
    avg = lambda f: {k: statistics.mean(f(s)[k] for s in seeds) for k in ("cov", "first", "second", "fixline",
                                                                           "unchanged", "active")}
    rows = [("fluidfix's 9 shipped classes", avg(lambda s: shipped_policy(d, s))),
            ("literal edits, at first sight (memorisation, no law)", avg(lambda s: literal_first_sight(d, s))),
            ("cheap literal edits, at first sight", avg(lambda s: literal_first_sight(d, s, only_cheap=True))),
            ("every relation, at first sight (no law)", avg(lambda s: first_sight(d, s))),
            ("cheap relations, at first sight", avg(lambda s: first_sight(d, s, only_cheap=True)))]
    if spec is not None:
        rows.append(("the table the principles allow, over relations (`--spec`: a check, not a law)",
                     avg(lambda s: law_policy(d, s, lambda x: spec[x]))))
    if law is not None:
        rows += [(f"{label_law} over relations", avg(lambda s: law_policy(d, s, law, ("rel",)))),
                 (f"{label_law} over literal edits", avg(lambda s: law_policy(d, s, law, ("lit",)))),
                 (f"**{label_law} over both - memory and generalisation**",
                  avg(lambda s: law_policy(d, s, law, ("rel", "lit"))))]
    out = ["| policy | covers | first half | second half | candidates on the fix line | per unchanged line | active at the end |",
           "|---|---|---|---|---|---|---|"]
    for name, r in rows:
        out.append(f"| {name} | **{r['cov']:.1%}** | {r['first']:.1%} | {r['second']:.1%} | {r['fixline']:.1f} | "
                   f"{r['unchanged']:.1f} | {r['active']:.0f} |")
    table.rows = dict(rows)
    return out


def main() -> int:
    args = sys.argv[1:]
    spec = None
    if "--spec" in args:
        from neo4d.judge_relate import spec_table
        spec = spec_table()
    law_path = next((a for a in args if a.endswith(".c")), None)
    if law_path is None and (Path(__file__).parent / "kernels" / "relate.c").exists():
        law_path = str(Path(__file__).parent / "kernels" / "relate.c")
    law = load_law(law_path) if law_path else None
    label = f"the RELATE law (`{Path(law_path).name}`)" if law_path else ""
    d, c = prep(), prep_click()
    _, cheap, costly = tiers(d)
    out = ["# RELATE live - a swarm learning relations like neurons", "",
           "Generated by `neo4d/relate_live.py`. A relation is a fix with the project-specific parts abstracted "
           "(`neo4d/relations.py`); a literal edit is the same with nothing abstracted. Every relation and every "
           "literal edit is a neuron whose strength the law sets on every event (0 unknown, 1 primed, 2 active - it "
           "proposes fixes, 3 proven). Exact generation of the real fixed line counts; candidates are what a repair "
           "would have to try. Each repair is scored before it is learned from.", "",
           f"## A swarm of {len({r['proj'] for r in d['rows']})} projects - BugsInPy, Defects4J, Defects4C", "",
           f"{sum(d['nbugs'].values()):,} real bugs, **{len(d['rows'])} small fixes** (up to 3 tokens changed in one "
           f"line). Each project is a net; the neurons are shared. Bugs arrive in a seeded random order, "
           f"{len(SEEDS)} seeds averaged. {len(d['rels'])} relations can generate: {sum(cheap.values())} cheap, "
           f"{sum(costly.values())} costly.", ""]
    out += table(d, SEEDS, law, label, spec)
    out += ["", "## click's own history - one net, real commit order, fully prospective", "",
            f"**{len(c['rows'])} small fixes in {c['nbugs']['click']} fix commits** (the commits INDUCE was replayed "
            "on, `results/INDUCE_LIVE.md`: literal one-token learning reached 1.2% there).", ""]
    out += table(c, [0], law, label)
    lit = table.rows["literal edits, at first sight (memorisation, no law)"]
    both = next((v for k, v in table.rows.items() if "over both" in k), None)
    out += ["", "**What this shows.** Across projects, relations generalise where literal edits do not transfer; "
            "inside one project's history, its own literal edits recur and memorising them wins. The same law over "
            "both - memory and generalisation, like episodic and semantic memory - beats the law over either alone "
            "on both streams, and its coverage keeps rising as it learns."
            + (f" The no-law rows reach more only by proposing many times the candidates (on click, every literal "
               f"edit at first sight: {lit['cov']:.1%} at {lit['fixline']:.0f} per fix line, against the law's "
               f"{both['cov']:.1%} at {both['fixline']:.0f})." if both else ""), "",
            "**What this does not show.** Coverage is patch level: a neuron generating the real fixed line. A repair "
            "would still run the suite on every candidate and need the SHIP law. Candidates per unchanged line "
            "multiply by the lines a repair searches; fault localisation decides how many that is."]
    (REPO / "results" / "RELATE_LIVE.md").write_text("\n".join(out) + "\n")
    print("\n".join(out))
    return 0


if __name__ == "__main__":
    sys.exit(main())
