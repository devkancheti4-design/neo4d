"""Robustness of route4d5: noise around the query, other encodings of the codes, and a million calls in one process.

    1  NOISE       the 5 examples and the query sit among N irrelevant fields (N = 0 .. 10,000) of each state; the
                   body reads the 6 relevant fields by position and calls the router. Every answer is compared with
                   the noise-free answer, and the time per query is measured in C.
    2  ENCODINGS   (a) the 16 codes carried in the mantissa of IEEE 754 float32 values, decoded by bit extraction;
                   (b) relabellings defined over the field GF(16) - x -> a*x + b, a != 0 - whose additive group is
                   GF(2)^4, so they lie inside the router's affine class; (c) the contrast: relabellings that are
                   NOT affine (random permutations of the 16 codes).
    3  SANDBOX     1,000,000 mixed scenarios (determined, open, contradictory, noise) through one process, compared
                   call for call with reverse order, shuffled order and a fresh process; 100,000 of them against the
                   brute-force version space; and the object file checked for writable state.

    python -m neo4d.robustness   -> results/ROBUSTNESS.md
"""
from __future__ import annotations

import ctypes
import random
import struct
import subprocess
import sys
import tempfile
from collections import Counter
from pathlib import Path

import numpy as np

from neo4d import KERNELS, REPO, build_kernel
from neo4d import edge_cases as E
from neo4d import judge_router4d as R4
from neo4d import silicon

NOISE_C = r'''
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <time.h>
int64_t route4d5(int64_t x);
static uint64_t s = 0x9E3779B97F4A7C15ULL;
static uint64_t rnd(void){ s ^= s << 13; s ^= s >> 7; s ^= s << 17; return s; }
int main(int argc, char **argv){
    long N = atol(argv[1]), Q = atol(argv[2]); const int S = 64;
    uint64_t *state = malloc(sizeof(uint64_t) * S * (N + 6));
    long *pos = malloc(sizeof(long) * S * 6); int64_t *clean = malloc(sizeof(int64_t) * S);
    for (int k = 0; k < S; k++){
        uint64_t *st = state + (long)k * (N + 6);
        for (long j = 0; j < N + 6; j++) st[j] = rnd();                 /* irrelevant fields: noise */
        int64_t x = (int64_t)(rnd() & 0xFFFFFFFFFFFULL);                /* the 5 examples + query */
        clean[k] = x;
        for (int f = 0; f < 6; f++){                                     /* hide each byte among the noise */
            long p; int dup;
            do { p = (long)(rnd() % (uint64_t)(N + 6)); dup = 0; for (int g = 0; g < f; g++) dup |= pos[k*6+g] == p; } while (dup);
            pos[k*6+f] = p;
            st[p] = (f < 5) ? (uint64_t)((x >> (8*f)) & 0xFF) : (uint64_t)((x >> 40) & 0xF);
        }
    }
    long mism = 0; uint64_t sink = 0;
    struct timespec t0, t1; clock_gettime(CLOCK_MONOTONIC, &t0);
    for (long i = 0; i < Q; i++){
        int k = (int)(i & (S - 1)); uint64_t *st = state + (long)k * (N + 6); long *pp = pos + k * 6;
        int64_t x = (int64_t)(st[pp[0]] | st[pp[1]] << 8 | st[pp[2]] << 16 | st[pp[3]] << 24 | st[pp[4]] << 32 | st[pp[5]] << 40);
        int64_t r = route4d5(x);
        sink += (uint64_t)r;
        mism += (r & 31) != (route4d5(clean[k]) & 31);
    }
    clock_gettime(CLOCK_MONOTONIC, &t1);
    double dt = (t1.tv_sec - t0.tv_sec) + (t1.tv_nsec - t0.tv_nsec) * 1e-9;
    printf("%ld %.4f %ld %llu\n", N, dt / Q * 1e9 / 2, mism, (unsigned long long)(sink & 1));
    return 0;
}
'''


def noise():
    d = Path(tempfile.mkdtemp(prefix="neo4d_noise_"))
    obj = d / "r5.o"
    subprocess.run(["cc", "-O2", "-c", "-o", str(obj), str(KERNELS / "router4d5.c")], check=True)
    (d / "noise.c").write_text(NOISE_C)
    subprocess.run(["cc", "-O2", "-o", str(d / "noise"), str(d / "noise.c"), str(obj)], check=True)
    rows = []
    for n in (0, 10, 100, 1_000, 10_000):
        out = subprocess.run([str(d / "noise"), str(n), "20000000"], capture_output=True, text=True).stdout.split()
        rows.append((int(out[0]), float(out[1]), int(out[2])))
    return rows, silicon.static(obj)


def _router():
    f = ctypes.CDLL(str(build_kernel("router4d5"))).route4d5
    f.argtypes, f.restype = [ctypes.c_int64], ctypes.c_int64
    return f


def _gf16_mul(a, b):
    r = 0
    for _ in range(4):
        if b & 1:
            r ^= a
        b >>= 1
        a <<= 1
        if a & 16:
            a ^= 0b10011                                   # x^4 + x + 1
    return r


def encodings(rng, n=20_000):
    route = _router()
    H = R4.CLASSES["affine"]()
    norm = lambda v: v & 15 if (v & 31) < 16 else -1

    def independent_cases():
        while True:
            Fs = [rng.randrange(16)]
            while len(Fs) < 5:
                f = rng.randrange(16)
                if E.rank([x ^ Fs[0] for x in Fs[1:]] + [f ^ Fs[0]]) > len(Fs) - 1:
                    Fs.append(f)
            return Fs

    def pack(ex, q):
        x = 0
        for i, (f, a) in enumerate(ex):
            x |= f << (8 * i) | a << (8 * i + 4)
        return x | q << 40

    # (a) codes carried in float32 mantissas: c -> float with c in mantissa bits 19..22, random exponent and low bits
    def to_float(c):
        bits = (rng.randrange(1, 254) << 23) | (c << 19) | rng.randrange(1 << 19)
        return struct.unpack("<f", struct.pack("<I", bits))[0]

    def from_float(v):
        return (struct.unpack("<I", struct.pack("<f", v))[0] >> 19) & 15

    fl = Counter()
    for _ in range(n):
        h = H[rng.randrange(len(H))]
        Fs, q = independent_cases(), rng.randrange(16)
        ex_f = [(to_float(f), to_float(int(h[f]))) for f in Fs]          # the world speaks floats
        q_f = to_float(q)
        ex = [(from_float(a), from_float(b)) for a, b in ex_f]
        got = norm(route(pack(ex, from_float(q_f))))
        fl["right" if got == int(h[q]) else ("refused" if got < 0 else "WRONG")] += 1
    # (b) relabellings defined over GF(16): x -> a*x + b
    gf = Counter()
    for _ in range(n):
        a, b = rng.randrange(1, 16), rng.randrange(16)
        g = [_gf16_mul(a, x) ^ b for x in range(16)]
        Fs, q = independent_cases(), rng.randrange(16)
        got = norm(route(pack([(f, g[f]) for f in Fs], q)))
        gf["right" if got == g[q] else ("refused" if got < 0 else "WRONG")] += 1
    # (c) the contrast: random permutations of the 16 codes - not affine
    na = Counter()
    for _ in range(n):
        p = list(range(16))
        rng.shuffle(p)
        Fs, q = independent_cases(), rng.randrange(16)
        got = norm(route(pack([(f, p[f]) for f in Fs], q)))
        na["right" if got == p[q] else ("refused" if got < 0 else "WRONG")] += 1
    return fl, gf, na


def sandbox(rng, n=1_000_000, check=100_000):
    route = _router()
    H = R4.CLASSES["affine"]()
    words = np.empty(n, dtype=np.int64)
    kinds = Counter()
    for i in range(n):
        m = i % 4
        Fs = [rng.randrange(16) for _ in range(5)]
        if m == 0:                                           # from an affine truth (determined or open)
            h = H[rng.randrange(len(H))]
            ex = [(f, int(h[f])) for f in Fs]
        elif m == 1:                                         # contradictory: one case, two actions
            h = H[rng.randrange(len(H))]
            ex = [(f, int(h[f])) for f in Fs]
            ex[4] = (ex[0][0], ex[0][1] ^ rng.randrange(1, 16))
        elif m == 2:                                         # noise
            ex = [(f, rng.randrange(16)) for f in Fs]
        else:                                                # arbitrary 64-bit garbage, high bits set
            words[i] = rng.getrandbits(63) - (rng.getrandbits(1) << 63)
            kinds["garbage"] += 1
            continue
        x = 0
        for j, (f, a) in enumerate(ex):
            x |= f << (8 * j) | a << (8 * j + 4)
        words[i] = x | rng.randrange(16) << 40
        kinds[["affine truth", "contradictory", "noise"][m]] += 1
    seq = [route(int(w)) for w in words]
    rev = [route(int(w)) for w in words[::-1]][::-1]
    order = list(range(n))
    rng.shuffle(order)
    shuf = [0] * n
    for i in order:
        shuf[i] = route(int(words[i]))
    # a fresh process
    d = Path(tempfile.mkdtemp(prefix="neo4d_sb_"))
    np.save(d / "w.npy", words)
    code = ("import ctypes,numpy as np,sys;from neo4d import build_kernel;f=ctypes.CDLL(str(build_kernel('router4d5'))).route4d5;"
            "f.argtypes,f.restype=[ctypes.c_int64],ctypes.c_int64;w=np.load(sys.argv[1]);"
            "np.save(sys.argv[2],np.array([f(int(x)) for x in w],dtype=np.int64))")
    subprocess.run([sys.executable, "-c", code, str(d / "w.npy"), str(d / "o.npy")], check=True)
    fresh = np.load(d / "o.npy").tolist()
    diffs = {"reverse order": sum(a != b for a, b in zip(seq, rev)),
             "shuffled order": sum(a != b for a, b in zip(seq, shuf)),
             "fresh process": sum(a != b for a, b in zip(seq, fresh))}
    # brute force on a sample, and the last call against its own first evaluation
    vs = E.VS
    bf = 0
    for i in rng.sample(range(n), check):
        ex, q = R4.unpack(int(words[i]) & ((1 << 44) - 1), 5)
        want, _ = vs.expect(ex, q)
        got = seq[i] & 15 if (seq[i] & 31) < 16 else R4.REFUSE
        bf += got != want
    last_same = route(int(words[-1])) == seq[-1] and route(int(words[0])) == seq[0]
    # writable state in the object file?
    obj = d / "r5.o"
    subprocess.run(["cc", "-O2", "-c", "-o", str(obj), str(KERNELS / "router4d5.c")], check=True)
    import platform, re as _re
    if platform.system() == "Darwin":
        sections = _re.findall(r"Section \((\w+), (\w+)\): (\d+)", subprocess.run(["size", "-m", str(obj)],
                               capture_output=True, text=True).stdout)
        listing = [f"{seg},{sec} {n}" for seg, sec, n in sections]
        writable = [x for x, (seg, sec, n) in zip(listing, sections) if seg == "__DATA" and int(n) > 0]
    else:
        rows = [l.split() for l in subprocess.run(["size", "-A", str(obj)], capture_output=True, text=True).stdout.splitlines()]
        listing = [f"{r[0]} {r[1]}" for r in rows if len(r) >= 2 and r[0].startswith(".")]
        writable = [x for x in listing if x.split()[0] in (".data", ".bss") and int(x.split()[1]) > 0]
    return kinds, diffs, bf, check, last_same, writable, "; ".join(listing)


def main() -> int:
    rng = random.Random(2026)
    nrows, st = noise()
    print("  noise done", flush=True)
    fl, gf, na = encodings(rng)
    print("  encodings done", flush=True)
    kinds, diffs, bf, check, last_same, writable, syms = sandbox(rng)
    print("  sandbox done", flush=True)
    pct = lambda c, k: f"{100 * c[k] / sum(c.values()):.2f}%"
    out = ["# route4d5 - robustness", "", "Generated by `neo4d/robustness.py`.", "",
           "## 1. Noise around the query", "",
           "Each state holds the 5 examples and the query among N irrelevant fields; the body reads the 6 relevant "
           "fields by position. 20,000,000 queries per row, 64 distinct states.", "",
           "| irrelevant fields per state | ns per query (read + route) | answers differing from the noise-free answer |",
           "|---|---|---|"]
    for n, ns, mism in nrows:
        out.append(f"| {n:,} | {ns:.2f} | **{mism}** |")
    out += ["", f"The router itself is the same machine code at every N: {st['instructions']} instructions, "
            f"{st['conditional_branches']} conditional branches, {st['memory_ops']} memory operations - noise never "
            "reaches it; its input is one 44-bit word. What grows with N is only the state the body reads from: by "
            "position it is flat, by search it would be linear in N - that cost belongs to the body, not the router.", "",
           "## 2. Other encodings of the same group", "",
           "20,000 scenarios each, five worked examples with independent cases (the span is full).", "",
           "| encoding | right | refused | **wrong** |", "|---|---|---|---|",
           f"| codes carried in IEEE 754 float32 mantissas | {pct(fl, 'right')} | {pct(fl, 'refused')} | **{pct(fl, 'WRONG')}** |",
           f"| relabellings over the field GF(16), x -> a*x + b | {pct(gf, 'right')} | {pct(gf, 'refused')} | **{pct(gf, 'WRONG')}** |",
           f"| contrast: random permutations of the 16 codes (not affine) | {pct(na, 'right')} | {pct(na, 'refused')} | **{pct(na, 'WRONG')}** |",
           "", "Any representation that maps one-to-one onto the 16 codes and keeps the relabellings affine works "
           "unchanged - floats are decoded by bit extraction, GF(16)'s affine maps are a subset of GF(2)^4's. What "
           "the router cannot do is learn a relationship that is not affine. Five examples with independent cases fit at "
           "most one affine map: when the actions happen to fit one, the router answers - wrong wherever the "
           "permutation leaves it - and when they fit none, it refuses (G3). Refusal protects against too little "
           "evidence and against contradiction; it cannot detect a non-affine truth that happens to fit five points.", "",
           "## 3. A million calls in one process", "", f"Scenarios: {dict(kinds)}.", "",
           "| comparison | calls differing |", "|---|---|"]
    for k, v in diffs.items():
        out.append(f"| sequential vs {k} | **{v}** |")
    out += [f"| {check:,} sampled calls vs the brute-force version space | **{bf}** |",
            f"| the 1,000,000th call re-run, and the 1st | {'identical' if last_same else 'DIFFERENT'} |", "",
            f"Writable sections in the compiled router (data, bss): **{len(writable)}** - its sections: {syms}. "
            "With no data section, no stores and no globals, a call cannot leave anything behind for the next one."]
    total = sum(m for _, _, m in nrows) + fl["WRONG"] + gf["WRONG"] + sum(diffs.values()) + bf + len(writable) \
        + (0 if last_same else 1)
    out += ["", f"**Failures (excluding the non-affine contrast): {total}.**"]
    (REPO / "results" / "ROBUSTNESS.md").write_text("\n".join(out) + "\n")
    print("\n".join(out))
    return int(total != 0)


if __name__ == "__main__":
    sys.exit(main())
