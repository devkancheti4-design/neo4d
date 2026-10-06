/* The reference for the 32-kind router - the judge's oracle, NOT a law: loops and branches, written to be obviously
   right, never handed over.

   Word (55 bits of an int64; bits 55-63 are 0):
       x = D2 | E2 << 5 | D3 << 10 | E3 << 15 | D4 << 20 | E4 << 25 | D5 << 30 | E5 << 35 | D6 << 40 | E6 << 45 | Dq << 50
   Di = Fi ^ F1, Ei = Ai ^ A1, Dq = Fq ^ F1: the body moves example 1 to the origin, which loses nothing - an affine
   bijection fits the six examples iff an invertible linear map L fits the five differences (Ei = L Di).

   Gaussian elimination over GF(2): an invertible L fits iff rank{Di | Ei << 5} = rank{Di} = rank{Ei} (well defined and
   injective on span{Di}); the query is determined iff Dq lies in span{Di}; the answer is L Dq. 32 = REFUSE.

   Mutants (-DMUTANT=n) exist only to prove the judge catches a wrong router:
       1 reads five examples, ignores the sixth          4 refuses whenever the differences do not span everything
       2 guesses an undetermined query                    5 treats the codes as 4-bit (the 16-kind router reused)
       3 admits singular maps (no injectivity check)      6 skips the consistency check
   -DPIVOT_LOW: the same elimination pivoting from the low bit up - a second CORRECT router, the judge's positive
   control (it must pass with 0 violations, and the formal proof must show it equal to the reference).        */
#ifndef ROUTER5_REF_H
#define ROUTER5_REF_H
#include <stdint.h>

#ifndef MUTANT
#define MUTANT 0
#endif
#ifdef PIVOT_LOW
#define R5_BITS(bit, width) for (int bit = 0; bit < (width); bit++)
#else
#define R5_BITS(bit, width) for (int bit = (width) - 1; bit >= 0; bit--)
#endif

static int r5_rank(const uint32_t *v, int n, int width){
    uint32_t b[10] = {0};
    int r = 0;
    for (int i = 0; i < n; i++){
        uint32_t y = v[i];
        R5_BITS(bit, width){
            if (!((y >> bit) & 1)) continue;
            if (!b[bit]){ b[bit] = y; r++; break; }
            y ^= b[bit];
        }
    }
    return r;
}

static int ref5(uint64_t x){
    uint32_t d[6], e[5], w[5];
    int k = MUTANT == 1 ? 4 : 5;
    uint32_t m = MUTANT == 5 ? 15 : 31;
    for (int i = 0; i < 5; i++){
        d[i] = (uint32_t)(x >> (10 * i)) & m;
        e[i] = (uint32_t)(x >> (10 * i + 5)) & m;
        w[i] = d[i] | e[i] << 5;
    }
    uint32_t q = (uint32_t)(x >> 50) & m;
    int rw = r5_rank(w, k, 10), rd = r5_rank(d, k, 5), re = r5_rank(e, k, 5);
    if (MUTANT != 6 && rw != rd) return 32;
    if (MUTANT != 3 && MUTANT != 6 && re != rd) return 32;
    if (MUTANT == 4 && rd < 5) return 32;
    d[k] = q;
    if (MUTANT != 2 && r5_rank(d, k + 1, 5) != rd) return 32;
    uint32_t b[5] = {0};
    for (int i = 0; i < k; i++){
        uint32_t y = w[i];
        R5_BITS(bit, 5){
            if (!((y >> bit) & 1)) continue;
            if (!b[bit]){ b[bit] = y; break; }
            y ^= b[bit];
        }
    }
    uint32_t y = q;
    R5_BITS(bit, 5)
        if ((y >> bit) & 1) y ^= b[bit];
    return (int)((y >> 5) & 31);
}
/* The subset characterisation - the formal proof's oracle: no elimination, so a SAT solver handles it well. Over all
   32 subsets S of the five differences, an invertible L fits iff sum_S D = 0 exactly when sum_S E = 0 (the linear
   relations among the cases are exactly those among the actions: L is well defined and injective on span{D}, and
   extends to all of GF(2)^5); the query is determined iff some sum_S D equals Dq, and the answer is that sum_S E -
   the same for every such S, by the first condition. At 16 kinds the same characterisation and the elimination are
   both proved equal to route4d5 on every word (results/KIT_PROOF.md), so they agree there everywhere. */
static int spec5(uint64_t x){
    uint32_t d[5], e[5], q = (uint32_t)(x >> 50) & 31;
    for (int i = 0; i < 5; i++){ d[i] = (uint32_t)(x >> (10 * i)) & 31; e[i] = (uint32_t)(x >> (10 * i + 5)) & 31; }
    int ok = 1, ans = 32;
    for (int s = 0; s < 32; s++){
        uint32_t sd = 0, se = 0;
        for (int i = 0; i < 5; i++) if ((s >> i) & 1){ sd ^= d[i]; se ^= e[i]; }
        ok &= (sd == 0) == (se == 0);
        if (sd == q) ans = (int)se;
    }
    return ok ? ans : 32;
}
#endif
