/* Exhaustive check of route4d5 over its whole reduced input space, against an independent reference.
   Reduced space: F1 = A1 = 0 (route4d5 reads F1, A1 only through XOR differences and the final A1 ^, so it is
   translation-equivariant by construction; the judge's G4 also checks it). Remaining: F2..F5, A2..A5, Fq = 36 bits
   = 68,719,476,736 words. Reference: Gaussian elimination over GF(2) on the pairs (d, e) - an affine map fits iff
   rank{d|e<<4} = rank{d} = rank{e}; the query is determined iff Fq lies in span{d}; the answer is e of that
   combination. Usage: exhaust5 <slice> <slices>   (slices split the range; the last one also takes the remainder)
                     exhaust5 --range <lo> <hi> */
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
int64_t route4d5(int64_t x);

static int rank8(const uint32_t *v, int n){
    uint32_t b[8] = {0}; int r = 0;
    for (int i = 0; i < n; i++){
        uint32_t x = v[i];
        for (int bit = 7; bit >= 0; bit--){
            if (!((x >> bit) & 1)) continue;
            if (!b[bit]){ b[bit] = x; r++; break; }
            x ^= b[bit];
        }
    }
    return r;
}

/* reference: 0..15 answer, or 16 refuse */
static int reference(const uint32_t *d, const uint32_t *e, uint32_t q){
    uint32_t w[4], dd[5];
    for (int i = 0; i < 4; i++){ w[i] = d[i] | (e[i] << 4); dd[i] = d[i]; }
    int rw = rank8(w, 4), rd = rank8(d, 4), re = rank8(e, 4);
    if (!(rw == rd && rd == re)) return 16;                  /* no affine map fits */
    dd[4] = q;
    if (rank8(dd, 5) != rd) return 16;                        /* query outside the span: open */
    /* solve: reduce (q | 0) by an echelon basis of w on the low nibble */
    uint32_t b[4] = {0};
    for (int i = 0; i < 4; i++){
        uint32_t x = w[i];
        for (int bit = 3; bit >= 0; bit--){
            if (!((x >> bit) & 1)) continue;
            if (!b[bit]){ b[bit] = x; break; }
            x ^= b[bit];
        }
    }
    uint32_t x = q;
    for (int bit = 3; bit >= 0; bit--) if ((x >> bit) & 1) x ^= b[bit];
    return (int)((x >> 4) & 15);                             /* A1 = 0, so the answer is e(lambda) */
}

int main(int argc, char **argv){
    uint64_t total = 1ULL << 36, lo, hi;
    long slice = -1;
    if (argc == 4){ lo = strtoull(argv[2], 0, 10); hi = strtoull(argv[3], 0, 10); }
    else {
        long slices = atol(argv[2]);
        uint64_t per = total / (uint64_t)slices;
        slice = atol(argv[1]);
        lo = per * (uint64_t)slice;
        hi = slice == slices - 1 ? total : lo + per;
    }
    uint64_t bad = 0, det = 0, ref = 0, first_bad = 0;
    for (uint64_t r = lo; r < hi; r++){
        uint32_t d[4], e[4];
        for (int i = 0; i < 4; i++){ d[i] = (r >> (8*i)) & 15; e[i] = (r >> (8*i + 4)) & 15; }
        uint32_t q = (r >> 32) & 15;
        int want = reference(d, e, q);
        int64_t x = (int64_t)(r << 8);                       /* F1 = A1 = 0 in the low byte */
        int v = (int)(route4d5(x) & 31);
        int got = v < 16 ? v : 16;
        if (got != want){ if (!bad) first_bad = r; bad++; }
        if (want == 16) ref++; else det++;
    }
    printf("%ld %llu %llu %llu %llu %llu\n", slice, (unsigned long long)(hi - lo), (unsigned long long)bad,
           (unsigned long long)det, (unsigned long long)ref, (unsigned long long)first_bad);
    return 0;
}
