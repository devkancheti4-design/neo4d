/* The formal proof for route4d5, by CBMC: on all 2^64 words, route4d5(x) & 31 equals the reference's answer on the
   44 data bits (16..31 exactly where it refuses) - so it also ignores bits 44-63 - with no undefined behaviour.
   The reference is exhaust5.c's Gaussian elimination, here on the full affine word (F1, A1 included).
   -DSUBSET: the subset characterisation instead (sum_S d = 0 exactly when sum_S e = 0 over every subset S of the
   differences; determined iff some sum_S d equals dq) - the form the 32-kind proof uses. Both proofs passing means
   the two oracles agree on all 2^44 data words.

   cbmc prove4d5.c ../kernels/router4d5.c --unwind 17 --unwinding-assertions [-DSUBSET]
                                                                 (M4 Pro: 4-16 minutes; with -DSUBSET, 8 seconds) */
#include <assert.h>
#include <stdint.h>

int64_t route4d5(int64_t x);
uint64_t nondet_u64(void);

static int rank8(const uint32_t *v, int n){
    uint32_t b[8] = {0};
    int r = 0;
    for (int i = 0; i < n; i++){
        uint32_t y = v[i];
        for (int bit = 7; bit >= 0; bit--){
            if (!((y >> bit) & 1)) continue;
            if (!b[bit]){ b[bit] = y; r++; break; }
            y ^= b[bit];
        }
    }
    return r;
}

static int ref(uint64_t x){
    uint32_t F1 = x & 15, A1 = (x >> 4) & 15, d[5], e[4], w[4];
    for (int i = 0; i < 4; i++){
        d[i] = ((x >> (8 * (i + 1))) & 15) ^ F1;
        e[i] = ((x >> (8 * (i + 1) + 4)) & 15) ^ A1;
        w[i] = d[i] | e[i] << 4;
    }
    uint32_t q = ((x >> 40) & 15) ^ F1;
    int rw = rank8(w, 4), rd = rank8(d, 4), re = rank8(e, 4);
    if (rw != rd || rd != re) return 16;
    d[4] = q;
    if (rank8(d, 5) != rd) return 16;
    uint32_t b[4] = {0};
    for (int i = 0; i < 4; i++){
        uint32_t y = w[i];
        for (int bit = 3; bit >= 0; bit--){
            if (!((y >> bit) & 1)) continue;
            if (!b[bit]){ b[bit] = y; break; }
            y ^= b[bit];
        }
    }
    uint32_t y = q;
    for (int bit = 3; bit >= 0; bit--) if ((y >> bit) & 1) y ^= b[bit];
    return (int)(((y >> 4) & 15) ^ A1);
}

static int subset(uint64_t x){
    uint32_t F1 = x & 15, A1 = (x >> 4) & 15, d[4], e[4], q = ((x >> 40) & 15) ^ F1;
    for (int i = 0; i < 4; i++){ d[i] = ((x >> (8 * (i + 1))) & 15) ^ F1; e[i] = ((x >> (8 * (i + 1) + 4)) & 15) ^ A1; }
    int ok = 1, ans = 16;
    for (int s = 0; s < 16; s++){
        uint32_t sd = 0, se = 0;
        for (int i = 0; i < 4; i++) if ((s >> i) & 1){ sd ^= d[i]; se ^= e[i]; }
        ok &= (sd == 0) == (se == 0);
        if (sd == q) ans = (int)(se ^ A1);
    }
    return ok ? ans : 16;
}

int main(void){
    uint64_t x = nondet_u64();
    int v = (int)(route4d5((int64_t)x) & 31);
#ifdef SUBSET
    assert((v < 16 ? v : 16) == subset(x & ((1ULL << 44) - 1)));
#else
    assert((v < 16 ? v : 16) == ref(x & ((1ULL << 44) - 1)));
#endif
    return 0;
}
