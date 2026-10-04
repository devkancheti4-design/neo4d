# neo4d

**A self-learning core that generalises on 4D structures.** It mutates the code it is pointed at to harvest its own
worked examples, routes them through a 4D relabelling space so five examples determine the whole mapping, and makes
every decision with a small integer law that is judged by exhaustive enumeration. No model inside. It refuses instead
of guessing.

Built on fluidnet / fluidfix (github.com/devkancheti4-design) - their vocabulary of fault classes, their descent, and
their router, whose structure is a ring of 16. neo4d replaces the ring with 4D structures and adds the laws that let
the system learn by itself.

---

## What it does, measured

| | static fluidnet (ring router) | neo4d (4D) |
|---|---|---|
| relabellings one law generalises across | 16 | **322,560** (affine GF(2)^4) - 20,160x |
| kinds one router handles from one example | 16 | **120** (600-cell) - 7.5x |
| wrong when the true relabelling is 4D | **58-92%** | **0%** |
| worked examples | typed by a person | **harvested by itself**: 5 trials, 20 test runs |
| real decisions after self-learning (click, two secret renumberings) | - | **60/60 right, 0 wrong** |

`results/` holds every measurement; `docs/GENERALIZATION.md` is the full account.

## The laws - authored externally, judged here

| law | decides | judged |
|---|---|---|
| `route4d` | the relabelling from 3 worked examples, affine GF(2)^4 | 0 violations; every word of its difference space (1,048,576) |
| `route4d5` | the relabelling from 5 worked examples, 64-bit | 0 violations; 200,000 words + 50,000/50,000 harvest-shaped answered |
| `harvest` | keep / skip / recheck / stop one mutation trial | 0 violations; the unique kernel its principles allow |
| `pick` | which mutation to try next | 0 violations; the unique kernel |
| `induce` | admit / keep / retire / reject a newly mined class | 0 violations; the unique kernel |

Each law's specification is in `prompts/` - bits, principles, the measurement that motivated it - and each judge
checks the principles by enumeration, including that every single-cell change to the kernel's table breaks one.

## Quick start

```bash
python3 -m venv .venv && .venv/bin/pip install -e .
.venv/bin/neo4d judge --quick          # every law, judged (a C compiler is needed: cc)
.venv/bin/neo4d shapes                 # the six 4D polytopes, measured
.venv/bin/neo4d generalize             # how far each 4D structure generalises
scripts/fetch_bench.sh                 # the benchmark data (BugsInPy, Defects4J, Defects4C, QuixBugs, click, ...)
.venv/bin/neo4d corpus-big             # 4D-native vocabulary on 1,566 real fixes
.venv/bin/neo4d learn                  # the self-learning loop live on click
```

## How the loop learns

1. **PICK** ranks every candidate mutation by facts known before any test runs (is the statement executed, does any
   other act compete on the mutant, how many tests run it).
2. The mutant is injected; the project's own suite judges it; **HARVEST** keeps it as a worked example only if it is
   caught, restored by exactly one act, stable, and a new direction.
3. **route4d5** turns five such examples into the whole kind -> act relabelling - or refuses.
4. **INDUCE** (next) turns recurring changes into new classes, so the vocabulary - the knowledge - grows.

## Where it fits

The laws run in nanoseconds on one CPU core (route4d5: 4.7 ns per mapping; harvest, pick: 1 ns). Its cost is the
target's own test runs. It is meant as an ingredient: a generalisation engine inside larger, GPU-heavy training - a
teacher that discovers exact rules from few examples, a symmetry space that shows a model the same knowledge under
322,560 relabellings, a curriculum of the most informative examples, and a vocabulary that grows.

## What is not shown yet

- Repair is bounded by the vocabulary: fluidfix's nine shipped classes generate 14 of 1,729 real benchmark fixes.
  Growing that vocabulary is INDUCE's job, and its learning curve is the next measurement.
- The secret renumberings in the live runs were affine - inside the structure by construction.
- On fluid-router's corpus the numbering decided the winner: 4D wins under a 4D-native numbering, the ring under
  fluidfix's ring numbering.
- The training-time A/B test on a GPU is designed, not run.

## Layout

```
neo4d/kernels/   the five laws in C
neo4d/           judges, the 4D structures, the self-learning loop, benchmarks, the v1 swarm
prompts/         every law's specification
results/         every measurement
docs/            the full accounts
scripts/         benchmark fetch
tests/           the laws, judged
```

License: AGPL-3.0-or-later.
