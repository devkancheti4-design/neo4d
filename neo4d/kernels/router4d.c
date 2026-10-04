/* ===========================================================================
   THE ROUTER ON GF(2)^4 -- a sound router that refuses.
   (authored externally; saved verbatim
    from the conversation - see the full header in the author's original)

   DECLARED:  class = affine maps of GF(2)^4   (322,560 relabellings)
              k     = 3 worked examples
              packing x = F1 | A1<<4 | F2<<8 | A2<<12 | F3<<16 | A3<<20 | Fq<<24
              result & 31:  0..15 the action,  16..31 REFUSE
   Judge with:  judge_router4d.py --class affine --k 3 --name route4d laws/router4d.c
   =========================================================================== */
#include <stdint.h>

static inline int32_t L_NIB (int32_t x){ return (x & 15); }          /* 0..15  */
static inline int32_t L_Z4  (int32_t x){ return ((x - x) - ((x - 1) >> 31)); }
static inline int32_t L_SAME(int32_t x){ return ((x | 1) - (x ^ (x >> 1))); }
static inline int32_t SIG_ALL3(int32_t x){
    return ((x & ((1 - x) >> 31)) - (x & ((1 - x) >> 2))); }
static inline int32_t L_LOW (int32_t x){ return (x & (-x)); }
static inline int32_t L_EMIT(int32_t x){ return (x ^ 16); }

int32_t route4d(int32_t x)
{
    int32_t F1 = L_NIB(x),       A1 = L_NIB(x >> 4);   /* kind 0..15           */
    int32_t F2 = L_NIB(x >> 8),  A2 = L_NIB(x >> 12);
    int32_t F3 = L_NIB(x >> 16), A3 = L_NIB(x >> 20);
    int32_t Fq = L_NIB(x >> 24);
    int32_t d2 = F2 ^ F1, d3 = F3 ^ F1, dq = Fq ^ F1;  /* 0..15                */
    int32_t e2 = A2 ^ A1, e3 = A3 ^ A1;                /* 0..15                */
    int32_t ok, mt, ins, p, T, ans;

    /* the three lambda conditions: v(lam) == 0  iff  e(lam) == 0             */
    ok = SIG_ALL3( L_SAME(L_Z4(d2)      | (L_Z4(e2)      << 1))
                 | (L_SAME(L_Z4(d3)     | (L_Z4(e3)      << 1)) << 1)
                 | (L_SAME(L_Z4(d2^d3)  | (L_Z4(e2^e3)   << 1)) << 2) );

    /* which lambda has v(lam) == dq.  bit l <-> lam = l, so bit 0 is v = 0    */
    mt  =  L_Z4(dq)            | (L_Z4(dq ^ d2)      << 1)
        | (L_Z4(dq ^ d3) << 2) | (L_Z4(dq ^ d2 ^ d3) << 3);   /* 0..15         */
    ins = 1 - L_Z4(mt);                                 /* dq lies in V, 0..1  */

    /* |16 keeps it non-zero, so ctz is total; index 4 reads past T and gives
       0, and that path is discarded because ins is then 0.                   */
    p   = __builtin_ctz((uint32_t)L_LOW(mt | 16));      /* 0..4                */
    T   = (e2 << 4) | (e3 << 8) | ((e2 ^ e3) << 12);    /* lam -> e(lam)       */
    ans = A1 ^ L_NIB(T >> (p << 2));                    /* 0..15               */

    return L_EMIT(ans | ((ok & ins) << 4));             /* 0..15 or 16..31     */
}
