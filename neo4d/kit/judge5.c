/* The sampling judge for the 32-kind router: a kernel `int64_t route5(int64_t x)` against the reference, on seeded
   stratified words, plus renumbering draws (G4) and harvest-shaped sets run end to end through the body's affine
   wrapper. Usage: judge5 <seed> <words>. Prints one line of counts (see judge_router5.py). */
#include <stdio.h>
#include <stdlib.h>
#include "gen5.h"

int64_t route5(int64_t x);

static int norm(int64_t v){ int a = (int)(v & 63); return a < 32 ? a : 32; }

/* the body: move example 1 to the origin, ask the law, move the answer back */
static int route5_affine(const uint32_t *F, const uint32_t *A, uint32_t Fq){
    uint32_t d[5], e[5];
    for (int i = 0; i < 5; i++){ d[i] = F[i + 1] ^ F[0]; e[i] = A[i + 1] ^ A[0]; }
    int v = norm(route5((int64_t)pack5(d, e, Fq ^ F[0])));
    return v == 32 ? 32 : v ^ (int)A[0];
}

int main(int argc, char **argv){
    (void)argc;
    g5_s = strtoull(argv[1], 0, 10) * 0x2545F4914F6CDD1DULL + 1;
    long n = atol(argv[2]);
    long cnt[4] = {0}, bad[4] = {0}, g0n = 0, g0bad = 0, g4n = 0, g4bad = 0, hsets = 0, hq = 0, hans = 0, hwrong = 0;
    uint64_t first[6] = {0};
    for (long it = 0; it < n; it++){
        int s = (int)(it % 8);
        if (s <= 5){
            uint64_t x = gen_word(s);
            if (s == 0) (void)route5((int64_t)(x | g5_next() << 55));   /* G5: any word, only UB is checked */
            int why = classify5(x), want = ref5(x), got = norm(route5((int64_t)x));
            cnt[why]++;
            if (got != want){ if (!bad[why]) first[why] = x; bad[why]++; }
            uint32_t d[5], e[5], q;
            unpack5(x, d, e, &q);
            int is_case = q == 0;
            for (int i = 0; i < 5; i++) is_case |= q == d[i];
            if (why == 2 && is_case){ g0n++; if (got != want){ if (!g0bad) first[0] = x; g0bad++; } }
        } else if (s == 6){
            uint64_t x = gen_word(1 + (int)g5_below(5));
            uint32_t d[5], e[5], q, d2[5], e2[5];
            unpack5(x, d, e, &q);
            mat5 P = m5_random(5), Q = m5_random(5);
            for (int i = 0; i < 5; i++){ d2[i] = m5_apply(&P, d[i]); e2[i] = m5_apply(&Q, e[i]); }
            int a = norm(route5((int64_t)x)), b = norm(route5((int64_t)pack5(d2, e2, m5_apply(&P, q))));
            int expect = a == 32 ? 32 : (int)m5_apply(&Q, (uint32_t)a);
            g4n++;
            if (b != expect){ if (!g4bad) first[4] = x; g4bad++; }
        } else {
            mat5 L = m5_random(5);
            uint32_t c = g5_below(32), F[6], A[6], diff[5];
            F[0] = g5_below(32);
            for (int got = 0; got < 5;){
                uint32_t f = g5_below(32);
                diff[got] = f ^ F[0];
                if (r5_rank(diff, got + 1, 5) == got + 1){ F[got + 1] = f; got++; }
            }
            for (int i = 0; i < 6; i++) A[i] = m5_apply(&L, F[i]) ^ c;
            hsets++;
            for (uint32_t fq = 0; fq < 32; fq++){
                int v = route5_affine(F, A, fq);
                hq++;
                if (v != 32) hans++;
                if (v != (int)(m5_apply(&L, fq) ^ c)){ if (!hwrong) first[5] = F[0] | (uint64_t)fq << 8; hwrong++; }
            }
        }
    }
    printf("%ld %ld %ld %ld %ld %ld %ld %ld %ld %ld %ld %ld %ld %ld %ld",
           cnt[1], bad[1], cnt[2], bad[2], cnt[3], bad[3], g0n, g0bad, g4n, g4bad, hsets, hq, hans, hwrong, n);
    for (int i = 0; i < 6; i++) printf(" %llx", (unsigned long long)first[i]);
    printf("\n");
    return 0;
}
