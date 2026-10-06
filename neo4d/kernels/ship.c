/* ===========================================================================
   THE SHIP LAW -- refuse, ask, or ship one candidate repair, and say how
   strongly it is certified.
   (authored externally; saved verbatim from the conversation - the full header
    with the lane derivation is in the author's original)

   ship(x) -> 0 REFUSE   1 ASK   2 SHIP   3 SHIP_PROVEN
   x = WAS_RED | GREEN<<1 | STABLE<<2 | UNIQUE<<3
     | PROVEN<<4 | REFUTED<<5 | THIN<<6 | ROUTED<<7
   =========================================================================== */
#include <stdint.h>

/* the premise: (x & 0xA7) == 0x87  ->  -1, else 0                     3 ops */
static inline int32_t L_GATEM(int32_t x){ return (((x ^ 135) - 1) >> 31); }

/* the verdict from UNIQUE, PROVEN, THIN -- always 1, 2 or 3, never 0  8 ops */
static inline int32_t L_SEL(int32_t x){
    return ((1 + (2 & ((x + 8) >> 4))) - (((x ^ 8) - 1) >> 31)); }

int32_t ship(int32_t x)
{
    return L_SEL(x & 0x58)        /* ASK, SHIP or SHIP_PROVEN            */
         & L_GATEM(x & 0xA7);     /* 0 unless the premise holds          */
}
