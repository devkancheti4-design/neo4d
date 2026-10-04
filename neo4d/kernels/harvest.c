/* ===========================================================================
   THE HARVEST LAW -- what to do with one mutation trial, from eight bits.
   (authored externally; saved verbatim from the conversation - the
    full header with the lane derivations is in the author's original)

   harvest(x) -> 0 SKIP   1 TAKE   2 STOP   3 RECHECK
   x = KILLED | RESTORES<<1 | UNIQUE<<2 | STABLE<<3
     | NEW_SPAN<<4 | RECHECKED<<5 | FULL<<6 | SPENT<<7
   =========================================================================== */
#include <stdint.h>

static inline int32_t L_STOP(int32_t x){ return (1 & (x | (x >> 1))); }
static inline int32_t L_TAKE(int32_t x){ return ((x + 1) >> 3); }
static inline int32_t L_RECK(int32_t x){ return (x & (((x - 1) - 1) >> 31)); }
static inline int32_t L_ACT (int32_t x){
    return ((1 + ((x - 2) >> 31)) - (x | ((x >> 1) - x))); }

int32_t harvest(int32_t x)
{
    int32_t st = L_STOP(x >> 6);          /* FULL or SPENT          0..1 */
    int32_t tk = L_TAKE((x >> 2) & 7);    /* UNIQUE & STABLE & NEW  0..1 */
    int32_t rc = L_RECK(x & 41);          /* KILLED & !STABLE & !RE 0..1 */
    return L_ACT(tk | (st << 1) | (rc << 2));              /* act    0..3 */
}
