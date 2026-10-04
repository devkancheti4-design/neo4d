/* ===========================================================================
   THE PICK LAW -- how good one (kind, site) trial is as the next mutation.
   (authored externally; saved verbatim from the conversation - the
    full header with the derivation is in the author's original)

   pick(x) -> 0 never this trial, 1..12 run it, higher first.
   x = NEW_SPAN | EXECUTED<<1 | TRIED<<2 | ALT_NONE<<3
     | MANY_TESTS<<4 | NAMED<<5 | COLD<<6        (bit 7 reserved, always 0)
   =========================================================================== */
#include <stdint.h>

/* (x & 7) == 3  ->  -1, else 0.  The veto, as a mask.            3 ops */
static inline int32_t L_GATEM(int32_t x){ return (((x ^ 3) - 1) >> 31); }

/* 2 + 6*ALT_NONE + 2*(MANY + NAMED) - COLD, over the four bits.  10 ops */
static inline int32_t L_SCORE(int32_t x){
    return ((x + (2 ^ (8 - (3 ^ (x | 6))))) - ((3 - (6 ^ (3 - x))) >> 3)); }

int32_t pick(int32_t x)
{
    return L_SCORE((x >> 3) & 15)      /* 1..12, never 0            */
         & L_GATEM(x & 7);             /* 0 or -1                   */
}
