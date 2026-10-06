/* Word generators for judging the 32-kind router: seeded, stratified. A uniform 55-bit word is almost always
   inconsistent, so most strata are built from a truth and then bent. Shared by judge5.c and bf5.c. */
#ifndef GEN5_H
#define GEN5_H
#include <stdint.h>
#include "router5_ref.h"

static uint64_t g5_s;
static uint64_t g5_next(void){                 /* splitmix64 */
    uint64_t z = (g5_s += 0x9E3779B97F4A7C15ULL);
    z = (z ^ (z >> 30)) * 0xBF58476D1CE4E5B9ULL;
    z = (z ^ (z >> 27)) * 0x94D049BB133111EBULL;
    return z ^ (z >> 31);
}
static uint32_t g5_below(uint32_t n){ return (uint32_t)(g5_next() % n); }

typedef struct { uint32_t col[5]; } mat5;      /* col[i] = the image of basis vector i */

static uint32_t m5_apply(const mat5 *m, uint32_t v){
    uint32_t y = 0;
    for (int i = 0; i < 5; i++) if ((v >> i) & 1) y ^= m->col[i];
    return y;
}
static int m5_rank(const mat5 *m){ return r5_rank(m->col, 5, 5); }
static mat5 m5_random(int want_rank){          /* want_rank 5: invertible; otherwise exactly that rank */
    mat5 m;
    if (want_rank == 5){
        do { for (int i = 0; i < 5; i++) m.col[i] = g5_below(32); } while (m5_rank(&m) != 5);
        return m;
    }
    uint32_t basis[5];
    for (int got = 0; got < want_rank;){
        basis[got] = g5_below(32);
        if (r5_rank(basis, got + 1, 5) == got + 1) got++;
    }
    do {
        for (int i = 0; i < 5; i++){
            uint32_t v = 0, pick = g5_below(32);
            for (int j = 0; j < want_rank; j++) if ((pick >> j) & 1) v ^= basis[j];
            m.col[i] = v;
        }
    } while (m5_rank(&m) != want_rank);
    return m;
}

static uint64_t pack5(const uint32_t *d, const uint32_t *e, uint32_t q){
    uint64_t x = 0;
    for (int i = 0; i < 5; i++) x |= (uint64_t)(d[i] & 31) << (10 * i) | (uint64_t)(e[i] & 31) << (10 * i + 5);
    return x | (uint64_t)(q & 31) << 50;
}
static void unpack5(uint64_t x, uint32_t *d, uint32_t *e, uint32_t *q){
    for (int i = 0; i < 5; i++){ d[i] = (x >> (10 * i)) & 31; e[i] = (x >> (10 * i + 5)) & 31; }
    *q = (x >> 50) & 31;
}

/* cases drawn from a random subspace of rank r (0..5), actions from a linear truth m; the query in the span, out of
   it, or equal to a case (G0) */
static uint64_t gen_from(const mat5 *m, uint32_t *d, uint32_t *e, uint32_t *q){
    int r = (int)g5_below(6);
    uint32_t basis[5];
    int got = 0;
    while (got < r){
        uint32_t v = g5_below(32);
        basis[got] = v;
        if (r5_rank(basis, got + 1, 5) == got + 1) got++;
    }
    for (int i = 0; i < 5; i++){
        uint32_t v = 0, pick = g5_below(32);
        for (int j = 0; j < r; j++) if ((pick >> j) & 1) v ^= basis[j];
        d[i] = v;
        e[i] = m5_apply(m, v);
    }
    uint32_t how = g5_below(4);
    if (how == 0) *q = g5_below(6) == 5 ? 0 : d[g5_below(5)];
    else if (how == 1){ uint32_t v = 0, pick = g5_below(32); for (int j = 0; j < r; j++) if ((pick >> j) & 1) v ^= basis[j]; *q = v; }
    else *q = g5_below(32);
    return pack5(d, e, *q);
}

/* strata: 0 uniform, 1 consistent, 2 one action bit flipped, 3 one case bit flipped, 4 duplicated cases,
   5 a singular truth (not a bijection) */
static uint64_t gen_word(int stratum){
    uint32_t d[5], e[5], q;
    if (stratum == 0) return g5_next() & ((1ULL << 55) - 1);
    mat5 m = m5_random(stratum == 5 ? 1 + (int)g5_below(4) : 5);
    gen_from(&m, d, e, &q);
    int i = (int)g5_below(5), j = (int)g5_below(5);
    if (stratum == 2) e[i] ^= 1u << g5_below(5);
    if (stratum == 3) d[i] ^= 1u << g5_below(5);
    if (stratum == 4){
        if (g5_below(3) == 0){ d[i] = 0; e[i] = g5_below(2) ? 0 : 1u << g5_below(5); }
        else { d[i] = d[j]; e[i] = g5_below(2) ? e[j] : e[j] ^ (1u << g5_below(5)); }
    }
    return pack5(d, e, q);
}

/* what the specification demands of a word: 3 out of class (G3), 1 open (G1), 2 determined (G2) */
static inline int classify5(uint64_t x){
    uint32_t d[6], e[5], w[5], q;
    unpack5(x, d, e, &q);
    for (int i = 0; i < 5; i++) w[i] = d[i] | e[i] << 5;
    int rw = r5_rank(w, 5, 10), rd = r5_rank(d, 5, 5), re = r5_rank(e, 5, 5);
    if (rw != rd || re != rd) return 3;
    d[5] = q;
    return r5_rank(d, 6, 5) == rd ? 2 : 1;
}
#endif
