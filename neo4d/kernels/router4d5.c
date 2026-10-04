/* ===========================================================================
   THE k = 5 AFFINE ROUTER -- the version space of GF(2)^4 in closed form.
   (authored externally; saved verbatim from the conversation - the
    full header with the derivation is in the author's original)

   int64_t route4d5(int64_t x)
   x = F1 | A1<<4 | F2<<8 | A2<<12 | F3<<16 | A3<<20 | F4<<24 | A4<<28
     | F5<<32 | A5<<36 | Fq<<40            (44 bits; bits 44-63 carry nothing)
   result & 31:  0..15 the action,  16..31 REFUSE
   =========================================================================== */
#include <stdint.h>

#define LO 0x0F0F0F0F0F0F0F0FULL
#define SV 0x7F7F7F7F7F7F7F7FULL
#define HB 0x8080808080808080ULL

static inline uint64_t BC(uint64_t v){ v |= v<<8; v |= v<<16; return v | (v<<32); }

int64_t route4d5(int64_t x)
{
    uint64_t u = (uint64_t)x;
    uint32_t F1 = (uint32_t)(u & 15), A1 = (uint32_t)((u >> 4) & 15);
    uint64_t w[4], P0, P1, bdq, acc = 0, ins = 0, sel = 0, L, H, X, z, m;
    uint32_t dq, ok, good, ans; int j;

    for (j = 0; j < 4; j++) {
        uint32_t F = (uint32_t)((u >> (8*j + 8))  & 15);
        uint32_t A = (uint32_t)((u >> (8*j + 12)) & 15);
        w[j] = (uint64_t)((F ^ F1) | ((A ^ A1) << 4));
    }
    dq  = (uint32_t)((u >> 40) & 15) ^ F1;
    bdq = BC((uint64_t)dq);

    P0  = (BC(w[0]) & 0xFF00FF00FF00FF00ULL)
        ^ (BC(w[1]) & 0xFFFF0000FFFF0000ULL)
        ^ (BC(w[2]) & 0xFFFFFFFF00000000ULL);
    P1  = P0 ^ BC(w[3]);

    L = P0 & LO;  H = (P0 >> 4) & LO;
    acc |= ((L + SV) & HB) ^ ((H + SV) & HB);
    X = L ^ bdq;  z = (~(X + SV)) & HB;  ins |= z;
    m = z >> 7;   sel |= H & ((m << 4) - m);
    L = P1 & LO;  H = (P1 >> 4) & LO;
    acc |= ((L + SV) & HB) ^ ((H + SV) & HB);
    X = L ^ bdq;  z = (~(X + SV)) & HB;  ins |= z;
    m = z >> 7;   sel |= H & ((m << 4) - m);

    sel |= sel >> 32;  sel |= sel >> 16;  sel |= sel >> 8;
    ins |= ins >> 32;  ins |= ins >> 16;  ins |= ins >> 8;
    acc |= acc >> 32;  acc |= acc >> 16;  acc |= acc >> 8;

    ok   = 1u - (uint32_t)((acc >> 7) & 1u);
    good = ok & (uint32_t)((ins >> 7) & 1u);
    ans  = A1 ^ (uint32_t)(sel & 15);
    return (int64_t)(uint64_t)((ans | (good << 4)) ^ 16u);
}
