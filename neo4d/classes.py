"""The fault classes the nets carry - fluidfix's own, plus taught ones.

A fluidnet net is one fluidfix process: the NINE shipped classes are in every net, and each net's dictionary
adds at most SEVEN taught classes (16 slots, 9 shipped). That ceiling is per process, which is the whole
reason fluidnet has many nets. Here a class is an object - signal, applier, property - so one process can
hold many nets' vocabularies at once; each net still sees only its own nine + seven.

    shipped   the 9 classes fluidfix 0.16.0 ships (signals and appliers taken from fluidfix itself)
    taught    `len-as-last-index` and `wrong-attribute-sibling`, exactly as fluidnet's demo teaches them,
              with their properties; plus `rename-j` house migrations (old_j( -> new_j(), each with a
              property, as many as the swarm has slots for
"""
from __future__ import annotations

import io
import re
import tokenize
from dataclasses import dataclass
from typing import Callable

from fluidfix import propcheck
from fluidfix.acts import ACTS, KINDS, SHIPPED_KINDS, Observation, act_for
from fluidfix.place import insert_token
from fluidfix.props import PROVEN, REFUTED, UNPROVEN

SLOTS_TAUGHT = 7          # per net: 16 kernel slots, 9 shipped


@dataclass(frozen=True)
class FaultClass:
    name: str
    signal: re.Pattern
    applier: Callable
    prop: Callable | None = None          # checker(original_line, candidate_line) -> (ok, why, n)
    shipped: bool = False
    kind: int = -1                        # the fluidfix kind, for shipped classes

    def candidates(self, line: str, lineno: int, all_lines: list[str]) -> list[str]:
        if not self.signal.search(line):
            return []
        obs = Observation(lineno=lineno)
        obs.kinds = [self.kind]
        obs.all_lines = all_lines
        try:
            out = self.applier(line, obs)
        except Exception:                 # a rule that raises abstains
            return []
        out = out if isinstance(out, list) else [out]
        return [c for c in out[:32] if isinstance(c, str) and c != line]

    def check(self, original: str, candidate: str) -> str:
        """The class property, with fluidfix's semantics: no property, or nothing evaluated, is UNPROVEN."""
        if self.prop is None:
            return UNPROVEN
        try:
            ok, _why, n = self.prop(original, candidate)
        except Exception:
            return UNPROVEN
        if ok is None:
            return UNPROVEN
        if ok is False:
            return REFUTED
        return PROVEN if n else UNPROVEN


def shipped() -> list[FaultClass]:
    out = []
    for k in sorted(SHIPPED_KINDS):
        name, _desc, sig = KINDS[k]
        out.append(FaultClass(name, sig, ACTS[act_for(k)], None, True, k))
    return out


# ---- taught exactly as fluidnet's docs/demo/rules.py teaches them

_ATTR = re.compile(r"\b([A-Za-z_]\w*)\.([A-Za-z_]\w*)\b(?!\s*=[^=])")


def _sibling(line, o):
    text = "\n".join(getattr(o, "all_lines", None) or [])
    out = []
    for m in _ATTR.finditer(line):
        recv, wrong = m.group(1), m.group(2)
        pool = set(re.findall(r"\b" + re.escape(recv) + r"\.(\w+)", text)) - {wrong}
        out += [line[:m.start(2)] + c + line[m.end(2):] for c in sorted(pool)]
    return out or [line]


def _tokens(s):
    return [t.string for t in tokenize.generate_tokens(io.StringIO(s.strip()).readline)]


def _one_attribute_only(orig, cand):
    a, b = _tokens(orig), _tokens(cand)
    diff = [i for i, (x, y) in enumerate(zip(a, b)) if x != y]
    if len(a) != len(b) or len(diff) != 1:
        return False, "more than one token moved", len(a)
    if diff[0] == 0 or a[diff[0] - 1] != ".":
        return False, "the changed token is not an attribute", len(a)
    return True, "", len(a)


_LEN = re.compile(r"\blen\(\w+\)(?!\s*-\s*1\b)")


def _len_applier(line, o):
    return [insert_token(line, m.start(), m.end(), " - 1") for m in _LEN.finditer(line)]


def _placement_preserves_value(orig, cand):
    o, c = propcheck.rhs(orig), propcheck.rhs(cand)
    intended = re.sub(r"\blen\(\w+\)", "(__L - 1)", o, count=1)
    actual = re.sub(r"\blen\(\w+\)", "__L", c, count=1)
    return propcheck.agree_over(intended, actual, grid=(1, 2, 3, 5, 8))


def demo_taught() -> list[FaultClass]:
    return [FaultClass("wrong-attribute-sibling", _ATTR, _sibling, _one_attribute_only),
            FaultClass("len-as-last-index", _LEN, _len_applier, _placement_preserves_value)]


# ---- house migrations: `old_j(` -> `new_j(`, one class per j, each with its property

def rename_class(j: int) -> FaultClass:
    old, new = f"old_{j}", f"new_{j}"
    sig = re.compile(rf"\b{old}\(")

    def applier(line, o, sig=sig, new=new):
        return [line[:m.start()] + new + "(" + line[m.end():] for m in sig.finditer(line)]

    def prop(orig, cand, old=old, new=new):
        a, b = _tokens(orig), _tokens(cand)
        diff = [i for i, (x, y) in enumerate(zip(a, b)) if x != y]
        if len(a) != len(b) or len(diff) != 1:
            return False, "more than one token moved", len(a)
        if (a[diff[0]], b[diff[0]]) != (old, new):
            return False, f"the change is not {old} -> {new}", len(a)
        return True, "", len(a)

    return FaultClass(f"rename-{j}", sig, applier, prop)


def taught(n: int) -> list[FaultClass]:
    """n taught classes: the demo's two, then rename-0, rename-1, ..."""
    base = demo_taught()
    return (base + [rename_class(j) for j in range(max(0, n - len(base)))])[:n]
