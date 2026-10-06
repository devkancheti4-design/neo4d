/* Brute force: the oracles themselves checked against the class. Every one of the 9,999,360 invertible linear maps
   of GF(2)^5 is tried on each sampled word - the fitting maps' answers on the query decide (one answer: that answer;
   several, or no fitting map: REFUSE) - and compared with both oracles, ref5 and spec5. No elimination: rank is used
   only to list GL(5,2), and that list is checked against |GL(5,2)| = 9,999,360.
   Usage: bf5 <seed> <words>. Prints: words, ref5 mismatches, determined, open, out of class, first bad, spec5
   mismatches. */
#include <stdio.h>
#include <stdlib.h>
#include "gen5.h"

int main(int argc, char **argv){
    (void)argc;
    g5_s = strtoull(argv[1], 0, 10) * 0x9E3779B97F4A7C15ULL + 7;
    long n = atol(argv[2]);
    uint32_t *gl = malloc(sizeof(uint32_t) * 10000000);
    long ng = 0;
    for (uint32_t c0 = 1; c0 < 32; c0++) for (uint32_t c1 = 1; c1 < 32; c1++) for (uint32_t c2 = 1; c2 < 32; c2++)
    for (uint32_t c3 = 1; c3 < 32; c3++) for (uint32_t c4 = 1; c4 < 32; c4++){
        uint32_t v[5] = {c0, c1, c2, c3, c4};
        if (r5_rank(v, 5, 5) == 5) gl[ng++] = c0 | c1 << 5 | c2 << 10 | c3 << 15 | c4 << 20;
    }
    if (ng != 9999360){ printf("GL(5,2) has %ld maps, expected 9999360\n", ng); return 1; }
    long bad = 0, bads = 0, det = 0, open = 0, out = 0;
    uint64_t first = 0;
    for (long it = 0; it < n; it++){
        uint64_t x = gen_word(1 + (int)(it % 5));
        uint32_t d[5], e[5], q;
        unpack5(x, d, e, &q);
        uint32_t answers = 0;
        long fits = 0;
        for (long g = 0; g < ng; g++){
            mat5 m;
            for (int i = 0; i < 5; i++) m.col[i] = (gl[g] >> (5 * i)) & 31;
            int ok = 1;
            for (int i = 0; i < 5 && ok; i++) ok = m5_apply(&m, d[i]) == e[i];
            if (ok){ fits++; answers |= 1u << m5_apply(&m, q); }
        }
        int want;
        if (!fits){ want = 32; out++; }
        else if (__builtin_popcount(answers) == 1){ want = __builtin_ctz(answers); det++; }
        else { want = 32; open++; }
        if (ref5(x) != want){ if (!bad) first = x; bad++; }
        bads += spec5(x) != want;
    }
    printf("%ld %ld %ld %ld %ld %llx %ld\n", n, bad, det, open, out, (unsigned long long)first, bads);
    return 0;
}
