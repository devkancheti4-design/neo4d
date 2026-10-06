/* ===========================================================================
   THE RELATE LAW, v2 -- a barren relation weakens even when it is cheap.
   (prompts/RELATE_V2_LAW_PROMPT.md; authored externally; saved verbatim from
    the conversation - the full header with the lane derivation is in the
    author's original)

   relate_v2(x) -> 0 UNKNOWN   1 PRIMED   2 ACTIVE   3 PROVEN
   x = LEVEL | FIRE<<2 | NEWNET<<3 | PREDICTED<<4 | CHEAP<<5
     | COSTLY<<6 | BARREN<<7                                  (LEVEL 0..3)

   One principle changed, so one lane changed: R3 R4 R5 R6 R1 and R8's MAX
   are v1's lanes. The new R9 lane reads g | BARREN<<2 | PREDICTED<<3 (16
   values): ((x ^ 6) - 1) >> 31 is -1 exactly when g = 2, BARREN set,
   PREDICTED clear. It no longer reads CHEAP, so the lane is narrower than
   v1's. R4 needs no lane of its own: it still grants 2 on FIRE and CHEAP,
   and R9 sits after it and may take that back.

   BUILD  cc -O2 -Wall -Wextra -Werror -std=c99 -c relate_v2.c
   =========================================================================== */
#include <stdint.h>

/* R8 "the highest of": L_MAXZ, (x & ~(x >> 31)), on a - b                  */
static inline int32_t MAX(int32_t a, int32_t b){ return b + ((a - b) & (~((a - b) >> 31))); }

static inline int32_t R3(int32_t x){ return (((x - (1 + 3)) >> 31) - ((x - (2 + 3)) >> 31)); }
static inline int32_t R4(int32_t x){ return ((x >> 1) & (x >> 4)); }
static inline int32_t R5(int32_t x){ return (((x + 3) >> 4) + ((x + 3) >> 4)); }
static inline int32_t R6(int32_t x){ return ((x >> 3) + ((x >> 1) & (x >> 4))); }
static inline int32_t R9(int32_t x){ return ((x & 3) + (((x ^ (3 + 3)) - 1) >> 31)); }
static inline int32_t R1(int32_t x){ return (((x + 3) >> 3) + (x & ((x >> 2) - 1))); }

int32_t relate_v2(int32_t x)
{
    /* R8: the highest of LEVEL and every grant                           */
    int32_t g = MAX(MAX(MAX(MAX(x & 3,
                                R3(x & 0x27)),     /* first sight primes   */
                            R4(x & 0x24)),         /* cheap is used        */
                        R5(x & 0x0F)),             /* a second net         */
                    R6(x & 0x13));                 /* a prediction         */
    /* R9: a barren relation weakens unless proven -- cheap or not        */
    int32_t d = R9(g | ((x >> 5) & 4) | ((x >> 1) & 8));
    /* R1: a costly relation is never active                              */
    return R1(d | ((x >> 4) & 4));
}
