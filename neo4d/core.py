"""neo4d's core, with no domain in it: propose -> vary -> verify -> remember, under the RELATE v2 law.

A domain supplies only what is specific to it (`Domain` below): how to ask a model, how to read its answer, how to
check a candidate, how to vary one, and how to abstract a solved task into a pattern with slots. Everything else -
the loop, the search, the memory and the law that governs it - is this file, the same for every domain.

    the loop     memory first: trusted patterns are instantiated for the task and checked (no model call); then up to
                 `calls` rounds: the model proposes, the candidate is checked, and neo4d searches its neighbourhood
                 (a beam over one-step variants, ranked by the checker's partial score) within `checks`; the model is
                 told what the best candidate scored
    the memory   each verified solution is abstracted into a pattern; RELATE v2 sets each pattern's level from the
                 evidence of every task (FIRE when a solution exhibits it, NEWNET on a task it was not seen on,
                 PREDICTED when replayed it solved the task, CHEAP: replaying costs no model call, BARREN when it keeps
                 failing); only active patterns (level >= 2) are replayed
"""
from __future__ import annotations

import json
import re
import time
import urllib.error
import urllib.request
from collections import defaultdict

from neo4d import domain_mutation as D
from neo4d import relate_live as RL

OLLAMA = "http://localhost:11434/api/generate"


class Domain:
    """What a domain must supply. Candidates and patterns must be hashable."""
    name = "domain"
    predict = 400                                          # the longest model reply the domain needs (tokens)

    def prompt(self, task, feedback=None):                 # -> str
        raise NotImplementedError

    def parse(self, task, reply):                          # -> candidate or None
        raise NotImplementedError

    def check(self, task, cand):                           # -> (solved: bool, score in [0, 1], note: str)
        raise NotImplementedError

    def variants(self, task, cand):                        # -> iterable of one-step variants
        raise NotImplementedError

    def key(self, task):                                   # -> the task's shape, names abstracted (memory index)
        raise NotImplementedError

    def abstract(self, task, cand):                        # -> pattern (hashable) or None
        raise NotImplementedError

    def instantiate(self, task, pattern):                  # -> candidate or None
        raise NotImplementedError

    def render(self, cand):                                # -> str shown to the model
        return str(cand)

    def start(self, task):                                 # -> a candidate to search from without a model
        raise NotImplementedError


def generate(model, prompt, temperature, seed, stats, predict=400):
    stats["calls"] += 1
    body = json.dumps({"model": model, "prompt": prompt, "stream": False,
                       "options": {"temperature": temperature, "seed": seed, "num_predict": predict,
                                   "num_ctx": 4096}}).encode()
    for wait in (2, 5, 10, None):
        try:
            req = urllib.request.Request(OLLAMA, data=body, headers={"Content-Type": "application/json"})
            with urllib.request.urlopen(req, timeout=600) as r:
                return json.loads(r.read())["response"]
        except (urllib.error.URLError, TimeoutError, ConnectionError):
            if wait is None:
                return ""
            time.sleep(wait)


def trust_all(x):
    """No law: every pattern exhibited once is used, and never weakened."""
    return 2 if (x >> 2) & 1 or (x & 3) >= 2 else x & 3


class Memory:
    """Verified patterns, indexed by the task's shape; RELATE v2 (or another rule) sets each one's level."""

    def __init__(self, law, replay=8):
        self.law, self.replay = law, replay
        self.level = defaultdict(int)
        self.fires = defaultdict(int)
        self.good = defaultdict(int)
        self.nets = defaultdict(set)
        self.by_key = defaultdict(list)                     # key -> patterns in the order first seen

    def ranked(self, key):
        ps = [p for p in self.by_key[key] if self.level[(key, p)] >= 2]
        return sorted(ps, key=lambda p: (-self.level[(key, p)], -self.good[(key, p)], self.by_key[key].index(p)))[:self.replay]

    def learn(self, key, net, own, tried):
        for p, ok in tried.items():
            self.fires[(key, p)] += 1
            self.good[(key, p)] += ok
        for p in ({own} if own is not None else set()) | set(tried):
            k = (key, p)
            L = self.level[k]
            FIRE = int(p == own)
            NEWNET = int(FIRE and net not in self.nets[k])
            PRED = int(L >= 1 and bool(tried.get(p)))
            BAR = int(L >= 1 and self.fires[k] >= D.BARREN_FIRES and self.good[k] / self.fires[k] < RL.BARREN_YIELD)
            x = L | FIRE << 2 | NEWNET << 3 | PRED << 4 | 1 << 5 | BAR << 7      # CHEAP: a replay costs no model call
            self.level[k] = self.law(x) & 3
            if FIRE:
                self.nets[k].add(net)
                if p not in self.by_key[key]:
                    self.by_key[key].append(p)


def search(dom, task, starts, budget, stats, beam=3, depth=2):
    """Beam search over one-step variants from the given candidates, ranked by the checker's partial score.
    -> (a solving candidate or None, the best (score, candidate) seen)"""
    seen = set(starts)
    frontier = list(starts)
    best = (-1.0, None)
    for _ in range(depth):
        scored = []
        for c in frontier:
            for v in dom.variants(task, c):
                if v in seen or v is None:
                    continue
                seen.add(v)
                if stats["checks"] >= budget:
                    return None, best
                stats["checks"] += 1
                ok, score, _ = dom.check(task, v)
                if ok:
                    return v, (1.0, v)
                scored.append((score, len(scored), v))
        if not scored:
            break
        scored.sort(key=lambda t: (-t[0], t[1]))
        best = max(best, (scored[0][0], scored[0][2]), key=lambda t: t[0])
        frontier = [c for _, _, c in scored[:beam]]
    return None, best


def solve(dom, task, model, method, memory=None, calls=4, checks=400, seed=0):
    """One task. method: 'alone' | 'sample' | 'debug' | 'core' | 'core-no-memory' | 'core-no-mutation' | 'search'.
    -> dict(solved, how, calls, checks)"""
    stats = defaultdict(int)
    key = dom.key(task)
    tried, how, sol = {}, None, None
    use_memory = method in ("core", "core-no-mutation") and memory is not None
    use_mutation = method in ("core", "core-no-memory", "search")
    if use_memory:
        for p in memory.ranked(key):
            c = dom.instantiate(task, p)
            ok = False
            if c is not None:
                stats["checks"] += 1
                ok = dom.check(task, c)[0]
            tried[p] = ok
            if ok:
                how, sol = "memory", c
                break
    if how is None and method == "search":
        sol, _ = search(dom, task, [dom.start(task)], checks, stats, depth=4)
        how = "search" if sol is not None else None
    elif how is None:
        n = 1 if method == "alone" else calls
        feedback = None
        for k in range(n):
            reply = generate(model, dom.prompt(task, feedback if method != "sample" else None),
                             0.0 if k == 0 else 0.8, seed * 1000 + k, stats, predict=dom.predict)
            cand = dom.parse(task, reply)
            if cand is None:
                feedback = "That answer could not be read; follow the requested format exactly."
                continue
            stats["checks"] += 1
            ok, score, note = dom.check(task, cand)
            if ok:
                how, sol = "model", cand
                break
            if use_mutation:
                found, best = search(dom, task, [cand], stats["checks"] + checks // n, stats, depth=4)   # as search alone
                if found is not None:
                    how, sol = "neo4d", found
                    break
                if best[1] is not None and best[0] > score:
                    feedback = (f"Your answer {dom.render(cand)} is not right ({note}). The closest neo4d found by small "
                                f"changes is {dom.render(best[1])} (score {best[0]:.2f} of 1). Try again.")
                    continue
            feedback = f"Your answer {dom.render(cand)} is not right: {note}. Try again."
    if memory is not None and method in ("core", "core-no-mutation"):
        memory.learn(key, task["id"], dom.abstract(task, sol) if sol is not None else None, tried)
    return dict(id=task["id"], solved=sol is not None, how=how, calls=stats["calls"], checks=stats["checks"])
