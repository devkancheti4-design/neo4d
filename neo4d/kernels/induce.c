/* ===========================================================================
   THE INDUCE LAW -- admit, keep, retire or reject one candidate class.
   (authored externally; saved verbatim from the conversation - the
    full header with the derivation and the two traps is in the author's original)

   induce(x) -> 0 REJECT   1 KEEP   2 ADMIT   3 RETIRE
   x = SEEN2 | SEEN5<<1 | CONFIRMED<<2 | REFUTED<<3
     | PROVABLE<<4 | CONFLICT<<5 | NOISY<<6 | ADMITTED<<7
   =========================================================================== */
#include <stdint.h>

/* CONFIRMED and PROVABLE and not CONFLICT and (not NOISY or SEEN5)    0 or 1 */
static inline int32_t L_ADM(int32_t x){
    return ((1 + ((22 - x) >> 6)) + ((x - (20 + (x >> 5))) >> 6)); }

/* (REFUTED, ADMITTED, adm) -> the act                                   0..3 */
static inline int32_t L_ACT(int32_t x){
    return ((2 & (x >> 2)) ^ (1 - ((128 - (x ^ 128)) >> 31))); }

int32_t induce(int32_t x)
{
    int32_t adm = L_ADM(x & 0x76);              /* the evidence, 0 or 1       */
    return L_ACT((x & 0x88) | (adm << 4));      /* REFUTED, ADMITTED, adm     */
}
