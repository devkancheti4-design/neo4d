"""Countdown, a numbers puzzle: reach a target with given numbers (each at most once) and + - * /.

The checker evaluates exactly (fractions) and checks the numbers used; it says whether a candidate is right and how
close it is, never what the answer is. Variants: change an operator, replace or swap numbers, insert `(x op n)`, delete
an operation, regroup. A pattern is the expression's shape with each number replaced by its rank among the task's
numbers - the same shape can then be tried on new numbers.
"""
from __future__ import annotations

import ast
import random
import re
from collections import Counter
from fractions import Fraction

from neo4d.core import Domain

OPS = {ast.Add: "+", ast.Sub: "-", ast.Mult: "*", ast.Div: "/"}
SMALL, LARGE = list(range(1, 11)), [25, 50, 75, 100]


def value(node):
    if isinstance(node, ast.Constant) and isinstance(node.value, int) and not isinstance(node.value, bool):
        return Fraction(node.value)
    if isinstance(node, ast.BinOp) and type(node.op) in OPS:
        a, b = value(node.left), value(node.right)
        if isinstance(node.op, ast.Add):
            return a + b
        if isinstance(node.op, ast.Sub):
            return a - b
        if isinstance(node.op, ast.Mult):
            return a * b
        if b == 0:
            raise ZeroDivisionError
        return a / b
    raise ValueError("only numbers and + - * / are allowed")


def leaves(node):
    if isinstance(node, ast.Constant):
        return [node.value]
    return leaves(node.left) + leaves(node.right)


def tree(expr):
    try:
        t = ast.parse(expr, mode="eval").body
        value(t)                                            # validates the node types
        return t
    except (SyntaxError, ValueError, ZeroDivisionError, RecursionError):
        return None


def text(node):
    return ast.unparse(node)


class Countdown(Domain):
    name = "countdown"

    def tasks(self, n, seed, k=4):
        rng = random.Random(seed)
        out = []
        while len(out) < n:
            nums = rng.sample(LARGE, 1) + rng.sample(SMALL, k - 1)
            rng.shuffle(nums)
            use = rng.sample(nums, rng.randint(2, 3))
            expr = str(use[0])
            for x in use[1:]:
                expr = f"({expr} {rng.choice('+-*')} {x})"
            t = value(ast.parse(expr, mode="eval").body)
            if t.denominator == 1 and 10 <= t <= 200 and int(t) not in nums:
                # _witness: how the target was made - for tests only, never shown to or used by a solver
                out.append(dict(id=f"cd{seed}-{len(out)}", numbers=nums, target=int(t), _witness=expr))
        return out

    def prompt(self, task, feedback=None):
        nums = ", ".join(map(str, task["numbers"]))
        return (f"Use the numbers {nums} (each at most once; you do not need to use all of them) with + - * / and "
                f"parentheses to make exactly {task['target']}.\n" + (f"{feedback}\n" if feedback else "")
                + "Reply with only the expression, for example (25 + 3) * 7 - without writing its value.")

    def parse(self, task, reply):
        for line in (reply or "").replace("×", "*").replace("÷", "/").replace("x", "*").split("\n"):
            line = line.strip().strip("`").split("=")[0].strip()
            if re.fullmatch(r"[\d\s+\-*/().]+", line or "x") and re.search(r"\d", line):
                t = tree(line)
                if t is not None:
                    return text(t)
        return None

    def check(self, task, cand):
        t = tree(cand) if cand else None
        if t is None:
            return False, 0.0, "it is not a valid expression"
        used, have = Counter(leaves(t)), Counter(task["numbers"])
        extra = used - have
        if extra:
            return False, 0.0, f"it uses {', '.join(map(str, sorted(extra.elements())))} more often than given"
        try:
            v = value(t)
        except ZeroDivisionError:
            return False, 0.0, "it divides by zero"
        if v == task["target"]:
            return True, 1.0, "right"
        shown = int(v) if v.denominator == 1 else float(v)
        return False, max(0.0, 1 - abs(float(v) - task["target"]) / task["target"]), f"it equals {shown}"

    def variants(self, task, cand):
        t = tree(cand)
        if t is None:
            return
        nodes = []

        def walk(n, path):
            nodes.append((n, path))
            if isinstance(n, ast.BinOp):
                walk(n.left, path + ("left",))
                walk(n.right, path + ("right",))
        walk(t, ())
        unused = list((Counter(task["numbers"]) - Counter(leaves(t))).elements())

        def put(path, new):
            root = ast.parse(cand, mode="eval").body
            if not path:
                return text(new)
            n = root
            for step in path[:-1]:
                n = getattr(n, step)
            setattr(n, path[-1], new)
            return text(root)

        def copy(n):
            return ast.parse(text(n), mode="eval").body
        for n, path in nodes:
            if isinstance(n, ast.BinOp):
                for op in OPS:
                    if not isinstance(n.op, op):
                        m = copy(n)
                        m.op = op()
                        yield put(path, m)
                yield put(path, copy(n.left))                # delete this operation, keep one side
                yield put(path, copy(n.right))
                for side in ("left", "right"):              # regroup a op (b op c) <-> (a op b) op c
                    inner = getattr(n, side)
                    if isinstance(inner, ast.BinOp):
                        if side == "right":
                            new = ast.BinOp(ast.BinOp(copy(n.left), type(n.op)(), copy(inner.left)), type(inner.op)(), copy(inner.right))
                        else:
                            new = ast.BinOp(copy(inner.left), type(inner.op)(), ast.BinOp(copy(inner.right), type(n.op)(), copy(n.right)))
                        yield put(path, new)
            else:
                for x in sorted(set(unused)):
                    yield put(path, ast.Constant(x))
            for x in sorted(set(unused)):                    # insert (node op x)
                for op in OPS:
                    yield put(path, ast.BinOp(copy(n), op(), ast.Constant(x)))
        ls = [p for n, p in nodes if isinstance(n, ast.Constant)]
        for i in range(len(ls)):                             # swap two numbers
            for j in range(i + 1, len(ls)):
                root = ast.parse(cand, mode="eval").body
                a, b = root, root
                for s in ls[i][:-1]:
                    a = getattr(a, s)
                for s in ls[j][:-1]:
                    b = getattr(b, s)
                va, vb = getattr(a, ls[i][-1]) if ls[i] else root, getattr(b, ls[j][-1]) if ls[j] else root
                va.value, vb.value = vb.value, va.value
                yield text(root)

    def key(self, task):
        return f"{len(task['numbers'])} numbers"

    def _ranks(self, task):
        order = sorted(range(len(task["numbers"])), key=lambda i: (-task["numbers"][i], i))
        return [task["numbers"][i] for i in order]

    def abstract(self, task, cand):
        t = tree(cand)
        if t is None:
            return None
        ranked = self._ranks(task)
        taken = Counter()

        def slot(n):
            if isinstance(n, ast.Constant):
                idx = [i for i, x in enumerate(ranked) if x == n.value]
                i = idx[min(taken[n.value], len(idx) - 1)]
                taken[n.value] += 1
                return ast.Name(f"n{i + 1}")
            return ast.BinOp(slot(n.left), n.op, slot(n.right))
        return text(slot(t))

    def instantiate(self, task, pattern):
        ranked = self._ranks(task)
        try:
            return text(tree(re.sub(r"n(\d+)", lambda m: str(ranked[int(m.group(1)) - 1]), pattern)))
        except (IndexError, TypeError, AttributeError):
            return None

    def start(self, task):
        return " + ".join(map(str, task["numbers"]))
