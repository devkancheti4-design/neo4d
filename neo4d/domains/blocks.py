"""Blocks world, a planning puzzle: restack named blocks into a goal arrangement, one legal move at a time.

The checker is a simulator: every move must be legal (only a clear block moves, onto the table or a clear block) and the
final arrangement must be the goal. Its partial score is the share of goal facts (what each block stands on) true when
the plan ends or first breaks a rule. Variants: delete, swap, redirect or re-pick one move, or insert a move to the
table. A pattern is the plan with blocks named by their place in the task's structure, so it replays on tasks of the
same shape with other names.
"""
from __future__ import annotations

import random
import re

from neo4d.core import Domain

NAMES = """red blue green amber violet teal coral olive navy ivory plum mint gold silver rust lime peach slate cyan
khaki maroon azure beige cream lilac ochre pearl ruby sand jade onyx sage taupe umber wine zinc copper bronze""".split()


def stacks_of(on):
    """{block: support} -> stacks, bottom to top, in a fixed order (by the bottom block's name)."""
    above = {s: b for b, s in on.items() if s != "table"}
    out = []
    for b in sorted(x for x, s in on.items() if s == "table"):
        st = [b]
        while st[-1] in above:
            st.append(above[st[-1]])
        out.append(st)
    return out


def show(on, order):
    """Stacks listed in the given block order of their bottoms (so a task's text follows its structure)."""
    sts = sorted(stacks_of(on), key=lambda st: order.index(st[0]))
    return "\n".join(f"  stack {i + 1} (bottom to top): {', '.join(st)}" for i, st in enumerate(sts))


def run_lenient(on, plan):
    """Every legal move applied, every illegal one skipped. -> (state, illegal moves, the first reason)"""
    s, bad, why = dict(on), 0, ""
    for i, (b, d) in enumerate(plan):
        ok = b in s and (d == "table" or d in s) and b != d and not any(v == b for v in s.values()) and \
            (d == "table" or not any(v == d for v in s.values()))
        if ok:
            s[b] = d
        else:
            bad += 1
            why = why or f"move {i + 1} ({b} onto {d}) is illegal"
    return s, bad, why


def run(on, plan):
    """-> (state after the legal prefix, index of the first illegal move or None, why)"""
    s = dict(on)
    for i, (b, d) in enumerate(plan):
        if b not in s or (d != "table" and d not in s) or b == d:
            return s, i, f"move {i + 1} names an unknown block"
        if any(v == b for v in s.values()):
            return s, i, f"move {i + 1} is illegal: {b} has a block on top"
        if d != "table" and any(v == d for v in s.values()):
            return s, i, f"move {i + 1} is illegal: {d} has a block on top"
        s[b] = d
    return s, None, ""


def naive(task):
    """A plan that always works: everything to the table, then each goal tower bottom up."""
    s, plan = dict(task["init"]), []
    for st in stacks_of(s):
        for b in reversed(st[1:]):
            plan.append((b, "table"))
    for st in stacks_of(task["goal"]):
        for i in range(1, len(st)):
            plan.append((st[i], st[i - 1]))
    return tuple(plan)


class Blocks(Domain):
    name = "blocks"
    predict = 160                                          # 15 moves read at most (3 per block) need about 100 tokens

    def tasks(self, n, seed):
        rng = random.Random(seed)
        out = []
        while len(out) < n:
            size = rng.randint(3, 5)
            names = rng.sample(NAMES, size)
            kind = rng.choice(("reverse", "unstack", "stack", "reorder", "scramble"))
            tower = lambda bs: {b: ("table" if i == 0 else bs[i - 1]) for i, b in enumerate(bs)}
            if kind == "reverse":
                init, goal = tower(names), tower(names[::-1])
            elif kind == "unstack":
                init, goal = tower(names), {b: "table" for b in names}
            elif kind == "stack":
                init, goal = {b: "table" for b in names}, tower(names)
            elif kind == "reorder":
                perm = names[:]
                while perm == names:
                    rng.shuffle(perm)
                init, goal = tower(names), tower(perm)
            else:
                goal = tower(names[:size // 2 + 1]) | tower(names[size // 2 + 1:])
                init = dict(goal)
                for _ in range(rng.randint(2, 4)):
                    clear = [b for b in init if not any(v == b for v in init.values())]
                    b = rng.choice(clear)
                    d = rng.choice([x for x in clear if x != b] + ["table"])
                    init[b] = d
                if init == goal:
                    continue
            task = dict(id=f"bw{seed}-{len(out)}", kind=kind, init=init, goal=goal, order=names)
            task["_witness"] = naive(task)                   # for tests only, never shown to or used by a solver
            out.append(task)
        return out

    def prompt(self, task, feedback=None):
        tops = [st[-1] for st in sorted(stacks_of(task["init"]), key=lambda st: task["order"].index(st[0]))]
        return ("Blocks are stacked on a table. Only the TOP block of a stack can be moved, one at a time, onto the "
                "table or onto the top block of another stack.\nNow:\n" + show(task["init"], task["order"])
                + f"\n  (top blocks now: {', '.join(tops)})"
                + "\nGoal:\n" + show(task["goal"], task["order"]) + "\n" + (f"{feedback}\n" if feedback else "")
                + "Reply with the moves, one per line, each as: move X onto Y   (or: move X onto table). Nothing else.")

    def parse(self, task, reply):
        plan = []
        for m in re.finditer(r"move\s+(\w+)\s+(?:onto|on|to)\s+(?:the\s+)?(\w+)", reply or "", re.I):
            plan.append((m.group(1).lower(), m.group(2).lower()))
        return tuple(plan[:3 * len(task["init"])]) if plan else None      # longer replies only repeat themselves

    def check(self, task, plan):
        s, bad, why = run_lenient(task["init"], plan)
        n = len(task["goal"])
        facts = sum(s.get(b) == d for b, d in task["goal"].items())
        if not bad and s == task["goal"]:
            return True, 1.0, "right"
        note = (why + "; " if why else "") + f"{facts} of {n} blocks end where the goal has them"
        return False, max(0.0, facts / n - 0.1 * bad), note

    def variants(self, task, plan):
        blocks = sorted(task["init"])
        L = len(plan)
        for i in range(L):
            yield plan[:i] + plan[i + 1:]                    # delete
        for i in range(L - 1):
            yield plan[:i] + (plan[i + 1], plan[i]) + plan[i + 2:]   # swap neighbours
        for i in range(L):
            b, d = plan[i]
            for x in ["table"] + blocks:                     # redirect
                if x not in (d, b):
                    yield plan[:i] + ((b, x),) + plan[i + 1:]
            for x in blocks:                                 # move another block
                if x not in (b, d):
                    yield plan[:i] + ((x, d),) + plan[i + 1:]
        for i in range(L + 1):                               # insert a move: a clear block onto the table, or onto
            s, bad, _ = run(task["init"], plan[:i])          # where the goal wants it
            if bad is not None:
                continue
            clear = [b for b in blocks if not any(v == b for v in s.values())]
            for b in clear:
                for d in ("table", task["goal"][b]):
                    if s[b] != d and (d == "table" or d in clear):
                        yield plan[:i] + ((b, d),) + plan[i:]

    def _canon(self, task):
        """Blocks named by structure: by stack (in the task's order), bottom to top."""
        names = [b for st in sorted(stacks_of(task["init"]), key=lambda st: task["order"].index(st[0])) for b in st]
        return {b: f"b{i + 1}" for i, b in enumerate(names)}

    def key(self, task):
        c = self._canon(task)
        rel = lambda on: tuple(sorted((c[b], c.get(d, d)) for b, d in on.items()))
        return f"{rel(task['init'])}->{rel(task['goal'])}"

    def abstract(self, task, plan):
        c = self._canon(task)
        return tuple((c[b], c.get(d, d)) for b, d in plan) if plan else None

    def instantiate(self, task, pattern):
        back = {v: k for k, v in self._canon(task).items()}
        try:
            return tuple((back[b], back.get(d, d)) for b, d in pattern)
        except KeyError:
            return None

    def render(self, plan):
        return "; ".join(f"move {b} onto {d}" for b, d in plan)

    def start(self, task):
        return ()
