"""Jobs - small red modules with tests, faults injected from named classes.

A job is what arrives at the edge: one module's source, its tests (statements, the way fluidnet's descend
takes them), and the faults that made it red. Every fault comes from a site template whose buggy line its
own class repairs; make_job() checks that the clean module is green, the buggy one is red on exactly the
faulty sites' tests, and that each fault's class proposes the clean line - so a job that cannot be repaired
by its own classes is never posed.
"""
from __future__ import annotations

import random
from dataclasses import dataclass, field
from functools import lru_cache

from neo4d.classes import FaultClass

# name -> (setup lines or None, function body lines with one line marked, buggy replacement, signature, tests)
# `{f}` is the function name; the marked line is the one the fault replaces.
SITES = {
    "strictness": ("(x)", ["    return x >= 10"], 0, "    return x > 10",
                   ["assert {f}(10) is True", "assert {f}(9.5) is False"]),
    "literal-off-by-one": ("(s)", ["    return s[1:]"], 0, "    return s[2:]", ['assert {f}("abc") == "bc"']),
    "swapped-return-operands": ("(a, b)", ["    return a / b"], 0, "    return b / a", ["assert {f}(6, 3) == 2"]),
    "flipped-additive": ("(a, b)", ["    return a + b"], 0, "    return a - b", ["assert {f}(2, 3) == 5"]),
    "minmax-swap": ("(a, b)", ["    return max(a, b)"], 0, "    return min(a, b)", ["assert {f}(2, 3) == 3"]),
    "flipped-augmented-assign": ("(x)", ["    t = 0", "    t += x", "    return t"], 1, "    t -= x",
                                 ["assert {f}(4) == 4"]),
    "flipped-comparison-direction": ("(a, b)", ["    return a < b"], 0, "    return a > b",
                                     ["assert {f}(1, 2) is True", "assert {f}(2, 1) is False"]),
    "reversed-minus-operands": ("(a, b)", ["    return b - a"], 0, "    return a - b", ["assert {f}(1, 5) == 4"]),
    "flipped-boolean": ("()", ["    return True"], 0, "    return False", ["assert {f}() is True"]),
    "len-as-last-index": ("(xs)", ["    return xs[len(xs) - 1]"], 0, "    return xs[len(xs)]",
                          ["assert {f}([1, 2, 3]) == 3"]),
    "wrong-attribute-sibling": ("(pt)", ["    return pt.y"], 0, "    return pt.z",
                                ["assert {f}(Pt(1, 2)) == 2"]),
}

HEADER = ["from collections import namedtuple", "Pt = namedtuple('Pt', 'x y')", "",
          "def _uses(pt):", "    return (pt.x, pt.y)", ""]


def site(cls_name: str):
    if cls_name.startswith("rename-"):
        j = int(cls_name.split("-")[1])
        return ("(x)", [f"    return new_{j}(x)"], 0, f"    return old_{j}(x)", [f"assert {{f}}(1) == {1 + j}"])
    return SITES[cls_name]


@dataclass
class Job:
    code: str
    tests: list[str]
    clean: str
    faults: list[str]                        # class names, one per injected fault
    lines: dict = field(default_factory=dict)   # class name -> 1-based line of its fault


def failing(code: str, tests: list[str]) -> frozenset:
    """Which tests fail. In-process (fluidnet's own failing() uses a subprocess per call - same verdicts,
    run a thousand times cheaper; the tests here are generated, never untrusted). Memoised on the exact
    text: a verdict is a function of the module and its tests, and the swarm still COUNTS every run."""
    return _failing(code, tuple(tests))


@lru_cache(maxsize=200_000)
def _failing(code: str, tests: tuple) -> frozenset:
    ns: dict = {}
    try:
        exec(compile(code, "<job>", "exec"), ns)
    except Exception:
        return frozenset(range(len(tests)))
    bad = []
    for i, t in enumerate(tests):
        try:
            exec(t, ns)
        except Exception:
            bad.append(i)
    return frozenset(bad)


def make_job(faults: list[str], distractors: list[str], rng: random.Random, by_name: dict) -> Job:
    """A module with one function per fault (buggy) and one per distractor (clean), in shuffled order."""
    names = [("F", n) for n in faults] + [("D", n) for n in distractors]
    rng.shuffle(names)
    clean, buggy, tests, lines = list(HEADER), list(HEADER), [], {}
    helpers = sorted({int(n.split("-")[1]) for _, n in names if n.startswith("rename-")})
    for j in helpers:
        for out in (clean, buggy):
            out += [f"def new_{j}(v):", f"    return v + {j}", ""]
    for i, (role, n) in enumerate(names):
        sig, body, mark, bad, ts = site(n)
        f = f"f{i}"
        for out in (clean, buggy):
            out.append(f"def {f}{sig}:")
        for k, l in enumerate(body):
            clean.append(l)
            if role == "F" and k == mark:
                buggy.append(bad)
                lines[n] = len(buggy)
            else:
                buggy.append(l)
        clean.append(""); buggy.append("")
        tests += [t.format(f=f) for t in ts]
    job = Job("\n".join(buggy), tests, "\n".join(clean), list(faults), lines)
    _validate(job, by_name)
    return job


def _validate(job: Job, by_name: dict) -> None:
    assert not failing(job.clean, job.tests), "clean module must be green"
    assert failing(job.code, job.tests), "buggy module must be red"
    cl, bl = job.clean.split("\n"), job.code.split("\n")
    for n, ln in job.lines.items():
        cands = by_name[n].candidates(bl[ln - 1], ln, bl)
        assert cl[ln - 1] in cands, f"{n} does not propose its own repair: {bl[ln-1]!r} -> {cands}"
