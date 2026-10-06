"""Judge a 32-kind router kernel against prompts/ROUTER5_LAW_PROMPT.md: `int64_t route5(int64_t x)`, GF(2)^5, k = 6.

    python -m neo4d.judge_router5 laws/route5.c            G0-G4 on seeded stratified words, harvest-shaped sets end
                                                           to end, undefined behaviour trapped (UBSan) on every call
    python -m neo4d.judge_router5 laws/route5.c --prove    + the formal proof by CBMC: every word, no sampling - 32
                                                           slices (one per query) in parallel, against the subset
                                                           characterisation spec5, and no undefined behaviour anywhere;
                                                           a slice unfinished after --limit seconds (default 3600) is
                                                           reported OPEN, never as proved
    python -m neo4d.judge_router5 --selfcheck              the judge judged: both oracles against brute force over all
                                                           9,999,360 maps of GL(5,2); two more correct routers must
                                                           pass; six wrong routers must each be caught, by the sample
                                                           and by the proof

The words: example 1 moved to the origin by the body (an affine map fits six examples iff an invertible linear map fits
the five differences), so the law reads 55 bits - 2^55 words, far too many to enumerate. The sample is stratified
(uniform words are almost all out of class), and --prove covers the rest.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from neo4d import BUILD, PKG

KIT = PKG / "kit"
TOOLS = {t for t in ("cbmc",) if shutil.which(t)}
FIELDS = ("g1n", "g1", "g2n", "g2", "g3n", "g3", "g0n", "g0", "g4n", "g4", "hsets", "hq", "hans", "hwrong", "words")
MUTANTS = {1: "reads five examples, ignores the sixth", 2: "guesses an undetermined query",
           3: "admits singular maps", 4: "refuses unless the differences span everything",
           5: "treats the codes as 4-bit (the 16-kind router reused)", 6: "skips the consistency check"}


def wrap(prefix: str, fn: str = "ref5") -> Path:
    """A kernel file that is one of the oracles (or a variant of one) - for the selfcheck only."""
    d = Path(tempfile.mkdtemp(prefix="judge5_"))
    f = d / "kernel.c"
    f.write_text(f'{prefix}\n#include "{KIT}/router5_ref.h"\n'
                 f"int64_t route5(int64_t x){{ return {fn}((uint64_t)x); }}\n")
    return f


def build(kernel: Path, ubsan: bool = True) -> Path:
    exe = Path(tempfile.mkdtemp(prefix="judge5_")) / "judge5"
    flags = ["-fsanitize=undefined", "-fno-sanitize-recover=all"] if ubsan else []
    r = subprocess.run(["cc", "-O2", "-march=native", *flags, "-I", str(KIT), "-o", str(exe), str(KIT / "judge5.c"),
                        str(kernel)], capture_output=True, text=True)
    if r.returncode:
        sys.exit(r.stderr)
    return exe


def run(exe: Path, words: int, procs: int) -> dict:
    per = max(8, words // procs // 8 * 8)
    ps = [subprocess.Popen([str(exe), str(s + 1), str(per)], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
          for s in range(procs)]
    tot = {k: 0 for k in FIELDS}
    tot["ub"], tot["first"] = "", []
    for p in ps:
        out, err = p.communicate()
        if p.returncode:
            tot["ub"] = tot["ub"] or (err.strip().splitlines() or ["crashed"])[-1]
            continue
        parts = out.split()
        for k, v in zip(FIELDS, parts):
            tot[k] += int(v)
        tot["first"].append(parts[len(FIELDS):])
    return tot


def report(t: dict, label: str, quiet: bool = False) -> int:
    rows = [("G0 identity - a query equal to a case", "g0n", "g0"),
            ("G1 sound - refuse what is open", "g1n", "g1"),
            ("G2 complete - answer what is fixed", "g2n", "g2"),
            ("G3 out of class - refuse", "g3n", "g3"),
            ("G4 renumber freely (P, Q in GL(5,2))", "g4n", "g4")]
    unanswered = t["hq"] - t["hans"]
    total = sum(t[b] for _, _, b in rows) + t["hwrong"] + unanswered + int(bool(t["ub"]))
    if quiet:
        return total
    print(f"\n  THE 32-KIND ROUTER - {label}\n  words against the reference (seeded, stratified) "
          f"{t['g1n'] + t['g2n'] + t['g3n']:,}")
    for name, n, b in rows:
        print(f"  {name:44} {t[b]:>8,}  of {t[n]:,}")
    print(f"  {'harvest-shaped, end to end (affine wrapper)':44} {t['hwrong']:>8,}  wrong of {t['hq']:,} queries "
          f"({t['hsets']:,} sets); unanswered {unanswered:,}")
    print(f"  {'G5 no undefined behaviour (UBSan, every call)':44} {'0' if not t['ub'] else '1  ' + t['ub']:>8}")
    print(f"\n  TOTAL  {total} violations")
    return total


def prove(kernel: Path, procs: int, quiet: bool = False, limit: float = 3600.0) -> int:
    """CBMC: 32 slices, one per query difference - together every word with bits 55-63 clear - each proving route5
    equal to spec5; and one run over all 2^64 words proving no undefined behaviour. A counterexample stops everything
    and counts; a slice still running after `limit` seconds is OPEN - reported, never counted as proved."""
    jobs = [(f"query {q:2}", [f"-DQUERY={q}"]) for q in range(32)] + [("any word, undefined behaviour", ["-DANY_WORD"])]
    t0, running, done, failed, opened = time.time(), [], 0, [], []
    while jobs or running:
        while jobs and len(running) < procs:
            label, extra = jobs.pop(0)
            running.append((label, time.time(), subprocess.Popen(["cbmc", str(KIT / "prove5.c"), str(kernel), "-I", str(KIT),
                                                     "--unwind", "33", "--unwinding-assertions", *extra],
                                                    stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)))
        for j in [j for j in running if j[2].poll() is None and time.time() - j[1] > limit]:
            j[2].kill()
            j[2].wait()
            running.remove(j)
            opened.append(j[0])
        finished = next((j for j in running if j[2].poll() is not None), None)
        if finished is None:
            time.sleep(0.2)
            continue
        running.remove(finished)
        label, _, p = finished
        out = p.communicate()[0]
        done += 1
        if "VERIFICATION SUCCESSFUL" not in out:          # a counterexample (or a failed run): stop everything
            failed.append(label)
            for job in running:
                job[2].kill()
                job[2].wait()
            running, jobs = [], []
    if not quiet:
        verdict = ("FAILED at " + ", ".join(failed) if failed else
                   f"OPEN - {len(opened)} slices unfinished after {limit:,.0f} s: " + ", ".join(opened) if opened else
                   "PROVED")
        print(f"\n  CBMC  equal to spec5 on all 2^55 words (32 query slices) and no undefined behaviour on all 2^64: "
              f"{verdict}  ({time.time() - t0:,.0f} s)")
    return len(failed)


def selfcheck(words: int, procs: int, bf_per: int = 4000) -> int:
    fails = 0
    exe = BUILD / "bf5"
    subprocess.run(["cc", "-O3", "-march=native", "-I", str(KIT), "-o", str(exe), str(KIT / "bf5.c")], check=True)
    ps = [subprocess.Popen([str(exe), str(s + 1), str(bf_per)], stdout=subprocess.PIPE, text=True) for s in range(procs)]
    n = bad = bads = det = opn = out = 0
    for p in ps:
        a = p.communicate()[0].split()
        n, bad, det, opn, out = n + int(a[0]), bad + int(a[1]), det + int(a[2]), opn + int(a[3]), out + int(a[4])
        bads += int(a[6])
    fails += bad != 0 or bads != 0
    print(f"\n  THE ORACLES against brute force over all 9,999,360 maps of GL(5,2)\n"
          f"  words {n:,}: determined {det:,}, open {opn:,}, out of class {out:,} - elimination (ref5) differs on "
          f"{bad}, the subset characterisation (spec5) on {bads}")
    t = run(build(wrap("")), words, procs)
    v = report(t, "the reference as the kernel (must be 0)")
    fails += v != 0
    t = run(build(wrap("#define PIVOT_LOW 1")), words, procs)
    v = report(t, "a second correct router - pivots from the low bit (must be 0)")
    fails += v != 0
    t = run(build(wrap("", "spec5")), words, procs)
    v = report(t, "a third - the subset characterisation spec5 (must be 0)")
    fails += v != 0
    print("\n  SIX WRONG ROUTERS - each must be caught")
    for m, what in MUTANTS.items():
        t = run(build(wrap(f"#define MUTANT {m}")), words, procs)
        v = report(t, what, quiet=True)
        caught = [k for k, key in (("G0", "g0"), ("G1", "g1"), ("G2", "g2"), ("G3", "g3"), ("G4", "g4"),
                                   ("harvest", "hwrong")) if t[key]]
        if t["hq"] - t["hans"]:
            caught.append("harvest-unanswered")
        fails += v == 0
        pf = prove(wrap(f"#define MUTANT {m}"), procs, quiet=True) if "cbmc" in TOOLS else None
        fails += pf == 0
        proof = "" if pf is None else ("; the proof: CAUGHT" if pf else "; the proof: MISSED")
        print(f"  {m} {what:52} {'CAUGHT' if v else 'MISSED'}  {v:,} violations: {', '.join(caught)}{proof}")
    print(f"\n  SELFCHECK {'PASSED' if not fails else f'FAILED ({fails})'}")
    return fails


def main() -> int:
    args = sys.argv[1:]
    procs = os.cpu_count() or 8
    words = 16_000_000
    if "--words" in args:
        words = int(args[args.index("--words") + 1])
    if "--selfcheck" in args:
        return int(selfcheck(words, procs) != 0)
    kernel = Path(next((a for a in args if a.endswith(".c")), "laws/route5.c"))
    total = report(run(build(kernel), words, procs), str(kernel))
    if "--prove" in args:
        limit = float(args[args.index("--limit") + 1]) if "--limit" in args else 3600.0
        total += prove(kernel, procs, limit=limit)
    return int(total != 0)


if __name__ == "__main__":
    sys.exit(main())
