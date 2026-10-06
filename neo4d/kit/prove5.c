/* The formal proof for the 32-kind router, by CBMC (bit-precise model checking): no word is sampled - the SAT solver
   reasons about every 64-bit input at once.

       default        on every word with bits 55-63 clear (2^55 words): route5(x) & 63 is the oracle's answer, or a
                      REFUSE (32..63) exactly where the oracle refuses. The oracle is spec5, the subset
                      characterisation (router5_ref.h): a SAT solver handles it far better than elimination - on
                      route4d5 the same proof takes 8 s against it and 4-16 minutes against elimination
       -DGAUSS        the elimination ref5 as the oracle instead (much slower)
       -DANY_WORD     on all 2^64 words: route5 has no undefined behaviour (no signed overflow, no shift out of range)

       -DQUERY=n      only the words whose query difference Dq is n (bits 50-54): the 2^55 words split into 32
                      independent proofs that run in parallel; together they are the whole proof

   cbmc prove5.c <kernel.c> -I neo4d/kit --unwind 11 --unwinding-assertions [-DANY_WORD | -DQUERY=n] */
#include <assert.h>
#include <stdint.h>
#include "router5_ref.h"

int64_t route5(int64_t x);
uint64_t nondet_u64(void);

int main(void){
    uint64_t x = nondet_u64();
#ifdef ANY_WORD
    (void)route5((int64_t)x);
#else
    __CPROVER_assume((x >> 55) == 0);
#ifdef QUERY
    __CPROVER_assume((x >> 50) == QUERY);
#endif
    int v = (int)(route5((int64_t)x) & 63);
#ifdef GAUSS
    assert((v < 32 ? v : 32) == ref5(x));
#else
    assert((v < 32 ? v : 32) == spec5(x));
#endif
#endif
    return 0;
}
