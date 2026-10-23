"""ARC (the Abstraction and Reasoning Corpus): find the grid transformation the training pairs share.

A candidate is a short program - at most 3 steps - over a small set of grid operations. The checker runs it on every
training input and compares the outputs (partial score: the share of cells right when the shape is right); the task's
test output is never used by a solver, only to score the program it submits. Variants: append a step, replace a step,
delete a step. A pattern is the program itself: a program that solved one task is tried first on the next.
"""
from __future__ import annotations

import json
import re
from collections import Counter
from pathlib import Path

from neo4d.core import Domain

COLORS = range(10)


# --------------------------------------------------------------------------------------------- grid operations

def T(g):
    return tuple(zip(*g)) if g else g


def rot90(g):
    return tuple(zip(*g[::-1]))


def flip_h(g):
    return tuple(r[::-1] for r in g)


def flip_v(g):
    return g[::-1]


def crop(g, bg=0):
    cells = [(i, j) for i, r in enumerate(g) for j, v in enumerate(r) if v != bg]
    if not cells:
        return None
    i0, i1 = min(c[0] for c in cells), max(c[0] for c in cells)
    j0, j1 = min(c[1] for c in cells), max(c[1] for c in cells)
    return tuple(r[j0:j1 + 1] for r in g[i0:i1 + 1])


def upscale(g, k):
    return tuple(tuple(v for v in r for _ in range(k)) for r in g for _ in range(k))


def downscale(g, k):
    if len(g) % k or len(g[0]) % k:
        return None
    out = []
    for i in range(0, len(g), k):
        row = []
        for j in range(0, len(g[0]), k):
            block = {g[a][b] for a in range(i, i + k) for b in range(j, j + k)}
            if len(block) != 1:
                return None
            row.append(block.pop())
        out.append(tuple(row))
    return tuple(out)


def tile(g, a, b):
    return tuple(tuple(v for _ in range(b) for v in r) for _ in range(a) for r in g)


def halves(g, axis):
    """Two halves, split at a uniform separator line if there is one, else in the middle."""
    h = g if axis == "h" else T(g)
    w = len(h[0])
    if w % 2 == 1 and len({r[w // 2] for r in h}) == 1:
        a, b = tuple(r[:w // 2] for r in h), tuple(r[w // 2 + 1:] for r in h)
    elif w % 2 == 0:
        a, b = tuple(r[:w // 2] for r in h), tuple(r[w // 2:] for r in h)
    else:
        return None
    return (a, b) if axis == "h" else (T(a), T(b))


def combine(g, axis, how, c):
    hs = halves(g, axis)
    if hs is None:
        return None
    a, b = hs
    f = {"and": lambda x, y: x and y, "or": lambda x, y: x or y, "xor": lambda x, y: bool(x) != bool(y),
         "nor": lambda x, y: not x and not y}[how]
    return tuple(tuple(c if f(x != 0, y != 0) else 0 for x, y in zip(ra, rb)) for ra, rb in zip(a, b))


def objects(g):
    """4-connected components of non-background cells (any colour)."""
    seen, out = set(), []
    for i, r in enumerate(g):
        for j, v in enumerate(r):
            if v and (i, j) not in seen:
                stack, comp = [(i, j)], []
                seen.add((i, j))
                while stack:
                    a, b = stack.pop()
                    comp.append((a, b))
                    for x, y in ((a + 1, b), (a - 1, b), (a, b + 1), (a, b - 1)):
                        if 0 <= x < len(g) and 0 <= y < len(g[0]) and g[x][y] and (x, y) not in seen:
                            seen.add((x, y))
                            stack.append((x, y))
                out.append(comp)
    return out


def object_crop(g, pick):
    obs = objects(g)
    if not obs:
        return None
    ob = (max if pick == "largest" else min)(obs, key=len)
    i0, i1 = min(c[0] for c in ob), max(c[0] for c in ob)
    j0, j1 = min(c[1] for c in ob), max(c[1] for c in ob)
    keep = set(ob)
    return tuple(tuple(g[i][j] if (i, j) in keep else 0 for j in range(j0, j1 + 1)) for i in range(i0, i1 + 1))


def gravity(g, d):
    h = {"down": g, "up": flip_v(g), "right": T(g), "left": flip_v(T(g))}[d]
    cols = T(h)
    fell = tuple(tuple([0] * sum(1 for v in c if v == 0) + [v for v in c if v]) for c in cols)
    out = T(fell)
    return {"down": out, "up": flip_v(out), "right": T(out), "left": T(flip_v(out))}[d]


def fill_enclosed(g, c):
    H, W = len(g), len(g[0])
    outside = set()
    stack = [(i, j) for i in range(H) for j in (0, W - 1) if not g[i][j]] + \
            [(i, j) for j in range(W) for i in (0, H - 1) if not g[i][j]]
    for p in stack:
        outside.add(p)
    while stack:
        a, b = stack.pop()
        for x, y in ((a + 1, b), (a - 1, b), (a, b + 1), (a, b - 1)):
            if 0 <= x < H and 0 <= y < W and not g[x][y] and (x, y) not in outside:
                outside.add((x, y))
                stack.append((x, y))
    return tuple(tuple(c if not v and (i, j) not in outside else v for j, v in enumerate(r)) for i, r in enumerate(g))


def recolor(g, a, b):
    return tuple(tuple(b if v == a else v for v in r) for r in g)


def keep(g, c):
    return tuple(tuple(v if v == c else 0 for v in r) for r in g)


def color_map_from(train):
    """A cell-by-cell colour mapping consistent with every training pair of equal shape, or None."""
    m = {}
    for i, o in train:
        if len(i) != len(o) or len(i[0]) != len(o[0]):
            return None
        for ri, ro in zip(i, o):
            for a, b in zip(ri, ro):
                if m.setdefault(a, b) != b:
                    return None
    return m


OPS = {
    "rot90": lambda g, p: rot90(g), "rot180": lambda g, p: rot90(rot90(g)), "rot270": lambda g, p: rot90(rot90(rot90(g))),
    "flip_h": lambda g, p: flip_h(g), "flip_v": lambda g, p: flip_v(g), "transpose": lambda g, p: T(g),
    "crop": lambda g, p: crop(g), "upscale": lambda g, p: upscale(g, p), "downscale": lambda g, p: downscale(g, p),
    "tile": lambda g, p: tile(g, *p), "mirror_h": lambda g, p: tuple(r + r[::-1] for r in g),
    "mirror_v": lambda g, p: g + g[::-1], "largest": lambda g, p: object_crop(g, "largest"),
    "smallest": lambda g, p: object_crop(g, "smallest"), "gravity": lambda g, p: gravity(g, p),
    "fill_enclosed": lambda g, p: fill_enclosed(g, p), "recolor": lambda g, p: recolor(g, *p),
    "keep": lambda g, p: keep(g, p), "remove": lambda g, p: recolor(g, p, 0),
    "left": lambda g, p: (halves(g, "h") or (None, None))[0], "right": lambda g, p: (halves(g, "h") or (None, None))[1],
    "top": lambda g, p: (halves(g, "v") or (None, None))[0], "bottom": lambda g, p: (halves(g, "v") or (None, None))[1],
    "combine": lambda g, p: combine(g, *p),
}


def step(g, op, p, cmap=None):
    if g is None or not g or not g[0]:
        return None
    if op == "color_map":
        return tuple(tuple(cmap.get(v, v) for v in r) for r in g) if cmap else None
    try:
        out = OPS[op](g, p)
    except (IndexError, ValueError, ZeroDivisionError, TypeError, KeyError):
        return None
    if out is None or not out or not out[0] or len(out) > 30 or len(out[0]) > 30:
        return None
    return tuple(tuple(r) for r in out)


def apply(prog, g, cmap=None):
    for op, p in prog:
        g = step(g, op, p, cmap)
        if g is None:
            return None
    return g


def steps_for(task):
    """Every operation with every parameter it can take on this task (colours: those its training grids use)."""
    used = sorted({v for i, o in task["train"] for g in (i, o) for r in g for v in r})
    out = [(op, None) for op in ("rot90", "rot180", "rot270", "flip_h", "flip_v", "transpose", "crop", "mirror_h",
                                  "mirror_v", "largest", "smallest", "left", "right", "top", "bottom", "color_map")]
    out += [("upscale", k) for k in (2, 3)] + [("downscale", k) for k in (2, 3)]
    out += [("tile", ab) for ab in ((1, 2), (2, 1), (2, 2), (3, 3))]
    out += [("gravity", d) for d in ("down", "up", "left", "right")]
    out += [("fill_enclosed", c) for c in used if c] + [("keep", c) for c in used if c] + [("remove", c) for c in used if c]
    out += [("recolor", (a, b)) for a in used for b in used if a != b]
    out += [("combine", (ax, how, c)) for ax in ("h", "v") for how in ("and", "or", "xor", "nor") for c in used if c]
    return out


def grid_text(g):
    return "\n".join("".join(str(v) for v in r) for r in g)


def load(split):
    root = Path(__file__).resolve().parents[2] / "bench" / "ARC-AGI" / "data" / split
    out = []
    for f in sorted(root.glob("*.json")):
        d = json.loads(f.read_text())
        tup = lambda g: tuple(tuple(r) for r in g)
        out.append(dict(id=f.stem, train=[(tup(x["input"]), tup(x["output"])) for x in d["train"]],
                        test=[(tup(x["input"]), tup(x["output"])) for x in d["test"]]))
    return out


# ------------------------------------------------------------------------------------------------ the adapter

def render_prog(prog):
    return ", ".join(op if p is None else f"{op}({','.join(map(str, p)) if isinstance(p, tuple) else p})" for op, p in prog) or "identity"


class Arc(Domain):
    name = "arc"
    predict = 120
    max_len = 3

    def prompt(self, task, feedback=None):
        pairs = "\n\n".join(f"Example {k + 1} input:\n{grid_text(i)}\nExample {k + 1} output:\n{grid_text(o)}"
                            for k, (i, o) in enumerate(task["train"]))
        ops = ("rot90, rot180, rot270, flip_h, flip_v, transpose, crop, mirror_h, mirror_v, largest, smallest, left, "
               "right, top, bottom, color_map, upscale(k), downscale(k), tile(a,b), gravity(down|up|left|right), "
               "fill_enclosed(c), keep(c), remove(c), recolor(a,b), combine(h|v,and|or|xor|nor,c)")
        return (f"Each example turns an input grid (digits are colours) into an output grid by the same rule.\n\n{pairs}\n\n"
                f"Write the rule as a program of at most 3 steps from these operations: {ops}.\n"
                + (f"{feedback}\n" if feedback else "") + "Reply with only the program, for example: flip_h, crop")

    def parse(self, task, reply):
        prog = []
        for m in re.finditer(r"([a-z_0-9]+)\s*(?:\(([^)]*)\))?", (reply or "").split("\n")[0].lower()):
            op, arg = m.group(1), m.group(2)
            if op not in OPS and op != "color_map":
                continue
            p = None
            if arg is not None:
                parts = [x.strip() for x in arg.split(",") if x.strip()]
                try:
                    p = tuple(int(x) if x.isdigit() else x for x in parts)
                    p = p[0] if len(p) == 1 else p
                except ValueError:
                    continue
            prog.append((op, p))
        return tuple(prog[:self.max_len]) if prog else None

    def check(self, task, prog):
        cmap = color_map_from(task["train"])
        score, ok = 0.0, True
        for i, o in task["train"]:
            g = apply(prog, i, cmap)
            if g == o:
                score += 1
                continue
            ok = False
            if g is not None and len(g) == len(o) and len(g[0]) == len(o[0]):
                score += sum(a == b for ra, rb in zip(g, o) for a, b in zip(ra, rb)) / (len(o) * len(o[0])) * 0.9
        return ok, score / len(task["train"]), "right" if ok else "it does not reproduce every example"

    def variants(self, task, prog):
        ss = steps_for(task)
        if len(prog) < self.max_len:
            for s in ss:
                yield prog + (s,)
        for i in range(len(prog)):
            yield prog[:i] + prog[i + 1:]
            for s in ss:
                if s != prog[i]:
                    yield prog[:i] + (s,) + prog[i + 1:]

    def key(self, task):
        same = all(len(i) == len(o) and len(i[0]) == len(o[0]) for i, o in task["train"])
        return "same shape" if same else "shape changes"

    def abstract(self, task, prog):
        return prog

    def instantiate(self, task, pattern):
        return pattern

    def render(self, prog):
        return render_prog(prog)

    def start(self, task):
        return ()

    def solves_test(self, task, prog):
        cmap = color_map_from(task["train"])
        return prog is not None and all(apply(prog, i, cmap) == o for i, o in task["test"])
