"""Judge a law kernel - exhaustively, by enumeration, against everything laws.py says.

    python3 judge.py hop   laws/hop.c        a C kernel: int32_t hop(int32_t x)
    python3 judge.py step  laws/step.py      a Python kernel: def step(x)
    python3 judge.py --all laws/             every law whose file is in the folder (.c or .py)
    python3 judge.py --selftest              the oracles judge clean, and every single-cell change to any
                                             table is caught by the principles alone

The C file is compiled on its own (cc -O2 -shared), so it must define every helper it uses - popcount,
ntzb - itself, the way the existing laws define their lanes. A main() in it is fine and is not run.
Exit status is the number of violations, capped at 1.
"""
from __future__ import annotations

import ctypes
import importlib.util
import os
import subprocess
import sys
import tempfile

from neo4d import anchors
from neo4d import laws as L


def load_kernel(law: L.Law, path: str):
    if path.endswith(".py"):
        spec = importlib.util.spec_from_file_location(f"kernel_{law.name}", path)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return getattr(mod, law.name)
    out = os.path.join(tempfile.mkdtemp(prefix="judge_"), f"{law.name}.so")
    r = subprocess.run(["cc", "-O2", "-shared", "-fPIC", "-o", out, path], capture_output=True, text=True)
    if r.returncode:
        sys.exit(f"{path}: does not compile on its own\n{r.stderr}")
    lib = ctypes.CDLL(out)
    f = getattr(lib, law.name)
    f.argtypes, f.restype = [ctypes.c_int32], ctypes.c_int32
    table = [f(x) for x in range(256)]
    return lambda x: table[x]


def report(law: L.Law, k, label: str, verbose: int = 3) -> int:
    R = law.reach()
    res = L.judge(law, k)
    print(f"\n  {law.title.upper()} - {label}")
    print(f"  {'reachable words':44} {len(R)}")
    rows = [("table", f"against the table, all {len(R)} reachable"),
            ("range", f"total on 0..255, lands in 0..{law.range_hi}")]
    rows += [(p.id, f"{p.id} {p.statement.split('**')[1].rstrip('.')}") for p in law.principles]
    rows += [("anchors", f"the {len(law.anchors)} anchors")]
    total = 0
    for key, name in rows:
        bad = res[key]
        total += len(bad)
        print(f"  {name[:44]:44} {len(bad)}")
        for x in bad[:verbose]:
            want = law.oracle(x) if law.reachable(x) else "-"
            print(f"      x={x:<3} got {k(x):>3}  table {want}")
    print(f"\n  TOTAL  {total} violations")
    return total


def selftest() -> int:
    total = 0
    for law in L.LAWS.values():
        total += report(law, law.oracle, "the oracle, judged as a kernel", verbose=3)
        open_cells = L.principles_fix_the_table(law)
        n = len(law.reach()) * law.range_hi
        print(f"  single-cell changes the principles alone miss {len(open_cells)} of {n}")
        total += len(open_cells)
    print(f"\n  SELFTEST TOTAL  {total}")
    return total


def main(argv: list[str]) -> int:
    anchors.attach()
    if not argv or argv[0] in ("-h", "--help"):
        print(__doc__)
        return 0
    if argv[0] == "--selftest":
        return int(selftest() != 0)
    if argv[0] == "--all":
        folder = argv[1] if len(argv) > 1 else "laws"
        total, found = 0, 0
        for law in L.LAWS.values():
            for ext in (".c", ".py"):
                p = os.path.join(folder, law.name + ext)
                if os.path.exists(p):
                    found += 1
                    total += report(law, load_kernel(law, p), p)
        print(f"\n  {found} kernels judged, {total} violations")
        return int(total != 0 or found == 0)
    name, path = argv[0], argv[1]
    law = L.LAWS[name]
    return int(report(law, load_kernel(law, path), path) != 0)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
