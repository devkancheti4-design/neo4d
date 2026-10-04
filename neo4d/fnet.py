"""One net's work on a job - fluidnet's descent, with its own vocabulary, that may hand on partial progress.

fluidnet's descend(): candidates from the loaded vocabulary, the class PROPERTY refuses before any test
runs, a step is kept only when the failing set STRICTLY shrinks (nothing new broken), walk downhill until
green. In fluidnet nothing partial ever leaves a net - stuck short of green is refusal, every edit undone.

Here a net returns how far it got, and the swarm decides what travels (the CARRY law). Acceptance is
unchanged: only a green module is ever accepted, and no step in it was refuted by its class property
(a class without one is UNPROVEN - fluidfix fails open; the CARRY law's STRICT bit refuses that).
"""
from __future__ import annotations

from fluidfix.props import PROVEN, REFUTED

from neo4d.classes import FaultClass
from neo4d.jobs import failing


def net_descend(code: str, tests: list[str], vocab: list[FaultClass], max_steps: int = 6,
                start: frozenset | None = None) -> dict:
    lines = code.split("\n")
    runs, blocked, steps = 0, 0, []
    cur = start if start is not None else failing(code, tests)
    if start is None:
        runs += 1
    for _ in range(max_steps):
        if not cur:
            break
        best = None
        for i, line in enumerate(lines):
            if not line.strip() or line.lstrip().startswith("#"):
                continue
            for c in vocab:
                for cand in c.candidates(line, i + 1, lines):
                    if c.check(line, cand) == REFUTED:           # free refusal, before any test runs
                        blocked += 1
                        continue
                    trial = lines[:]
                    trial[i] = cand
                    try:
                        compile("\n".join(trial), "<candidate>", "exec")
                    except SyntaxError:
                        continue
                    runs += 1
                    got = failing("\n".join(trial), tests)
                    if got < cur:                                 # strictly fewer, nothing new broken
                        best = (i, cand, c.name, got, line, c.check(line, cand) == PROVEN)
                        break
                if best:
                    break
            if best:
                break
        if not best:
            break
        i, cand, name, got, was, proven = best
        lines[i] = cand
        steps.append({"class": name, "line": i + 1, "before": was.strip(), "after": cand.strip(),
                      "failing": f"{len(cur)} -> {len(got)}", "proven": proven})
        cur = got
    return {"code": "\n".join(lines), "failing": cur, "runs": runs, "blocked": blocked, "steps": steps}
