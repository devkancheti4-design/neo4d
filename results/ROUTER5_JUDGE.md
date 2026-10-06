# route5 judged - the 32-kind router

Output of `python -m neo4d.judge_router5 neo4d/kernels/router5.c --prove` (M4 Pro, 12 cores):

```

  THE 32-KIND ROUTER - neo4d/kernels/router5.c
  words against the reference (seeded, stratified) 11,999,952
  G0 identity - a query equal to a case               0  of 2,152,654
  G1 sound - refuse what is open                      0  of 1,997,091
  G2 complete - answer what is fixed                  0  of 2,855,715
  G3 out of class - refuse                            0  of 7,147,146
  G4 renumber freely (P, Q in GL(5,2))                0  of 1,999,992
  harvest-shaped, end to end (affine wrapper)         0  wrong of 63,999,744 queries (1,999,992 sets); unanswered 0
  G5 no undefined behaviour (UBSan, every call)        0

  TOTAL  0 violations

  CBMC  equal to spec5 on all 2^55 words (32 query slices) and no undefined behaviour on all 2^64: PROVED  (500 s)
```
