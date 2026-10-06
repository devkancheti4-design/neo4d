/* ===========================================================================
   THE 32-KIND ROUTER -- the version space of GL(5,2) in closed form.
   (authored externally; saved verbatim from the conversation - the full
    header with the lane derivation is in the author's original)

   int64_t route5(int64_t x)
   x = D2 | E2<<5 | D3<<10 | E3<<15 | D4<<20 | E4<<25
     | D5<<30 | E5<<35 | D6<<40 | E6<<45 | Dq<<50      (55 bits; 55-63 unused)
   result & 63:  0..31 the answer Eq,  32..63 REFUSE

   Over all 32 subsets lam, with v(lam) and e(lam) the XORs of the chosen Di
   and Ei: some invertible L fits iff v(lam) == 0 exactly when e(lam) == 0;
   the query is determined iff Dq = v(lam) for some lam, and the answer is
   that e(lam). Thirty-two 5-bit values fit in four int64 words as eight bytes
   each; a field holds 0..31, so adding 127 sets its top bit exactly when it
   is nonzero and never carries out of its byte.

   BUILD  cc -O2 -Wall -Wextra -Werror -std=c99 -c router5.c
   =========================================================================== */
#include <stdint.h>

#define SV 0x7F7F7F7F7F7F7F7FULL      /* 127 in every byte */
#define HB 0x8080808080808080ULL      /* 128 in every byte */

static inline uint64_t BC(uint64_t v){ v |= v<<8; v |= v<<16; return v | (v<<32); }

int64_t route5(int64_t x)
{
    uint64_t u = (uint64_t)x, bD[5], bE[5], bq, bd, be;
    uint64_t VD, VE, acc = 0, ins = 0, sel = 0, dz, ez, X, z, m;
    uint32_t ans, ok, good; int j;

    for (j = 0; j < 5; j++) {                 /* the five differences        */
        bD[j] = BC((u >> (10*j))     & 31);
        bE[j] = BC((u >> (10*j + 5)) & 31);
    }
    bq = BC((u >> 50) & 31);

    /* lam bits 0,1,2 across the eight bytes of a word                       */
    bd = (bD[0] & 0xFF00FF00FF00FF00ULL) ^ (bD[1] & 0xFFFF0000FFFF0000ULL)
       ^ (bD[2] & 0xFFFFFFFF00000000ULL);
    be = (bE[0] & 0xFF00FF00FF00FF00ULL) ^ (bE[1] & 0xFFFF0000FFFF0000ULL)
       ^ (bE[2] & 0xFFFFFFFF00000000ULL);

    for (j = 0; j < 4; j++) {                 /* lam bits 3 and 4            */
        VD = bd ^ ((j&1 ? bD[3] : 0) ^ (j&2 ? bD[4] : 0));
        VE = be ^ ((j&1 ? bE[3] : 0) ^ (j&2 ? bE[4] : 0));
        dz  = HB & (VD + SV);                 /* L_NZB, eight at a time      */
        ez  = HB & (VE + SV);
        acc |= dz ^ ez;                       /* exactly one of them zero    */
        X    = VD ^ bq;
        z    = HB ^ (HB & (X + SV));          /* L_ZB, carry-safe            */
        ins |= z;
        m    = z >> 7;                        /* 0x01 in each matching byte  */
        sel |= VE & ((m << 5) - m);           /* L_SPR: 0x01 -> 0x1F         */
    }
    sel |= sel >> 32;  sel |= sel >> 16;  sel |= sel >> 8;
    ins |= ins >> 32;  ins |= ins >> 16;  ins |= ins >> 8;
    acc |= acc >> 32;  acc |= acc >> 16;  acc |= acc >> 8;

    ok   = 1u - (uint32_t)((acc >> 7) & 1u);  /* no lam disagrees            */
    good = ok & (uint32_t)((ins >> 7) & 1u);  /* and Dq lies in the span     */
    ans  = (uint32_t)(sel & 31);
    return (int64_t)(uint64_t)((ans | (good << 5)) ^ 32u);   /* L_EMIT       */
}
