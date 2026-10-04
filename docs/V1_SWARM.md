# fluidnet on a 4D shape

**The experiment:** fluidnet is built static - one overseer, many small nets, each net trying alone from the
original code, the first green winning. Put the same nets on the vertices of a regular 4D polytope, let the
job travel between them carrying its partial repair, and let integer laws make every decision. Does the
shape help?

No model anywhere. The nets are fluidfix's own vocabulary (the 9 shipped classes in every net, at most 7
taught per net - the per-process slot ceiling that is why fluidnet has many nets), fluidnet's own descent
(the property gate before any test, a step kept only when strictly fewer tests fail, nothing accepted short
of green), and seven laws in fluidnet's style: eight measured bits in, one decision out.

## The laws - you give the kernels

| law | decides | shape | prompt |
|---|---|---|---|
| HOP | which link a job crosses next - the node id IS the address | 8-cell | `prompts/HOP_LAW_PROMPT.md` |
| STEP | how good one neighbour is as the next hop | every shape | `prompts/STEP_LAW_PROMPT.md` |
| MIRROR | home or antipodal copy; when to repair | the 5 antipodal shapes | `prompts/MIRROR_LAW_PROMPT.md` |
| CARRY | after a net works on a job: carry, accept, recheck or refuse | every shape | `prompts/CARRY_LAW_PROMPT.md` |
| SEEK | which net holding a wanted dictionary to visit next | every shape | `prompts/SEEK_LAW_PROMPT.md` |
| ADMIT | what a net does with a job that just arrived | every shape | `prompts/ADMIT_LAW_PROMPT.md` |
| QUORUM | commit / abort / wait on a 5-way vote, one round | 5-cell | `prompts/QUORUM_LAW_PROMPT.md` |

Each prompt carries the bits, the principles, the full 256-word truth table, anchors computed on the real
shapes (or recorded from real swarm runs), and how it is judged. The principles fix every table: each of the
10,343 single-cell changes across the seven tables breaks at least one principle (`judge.py --selftest`).

Until your kernels arrive, the swarm runs on the reference oracles in `laws.py` - same tables. To plug yours in:

```bash
.venv/bin/python judge.py hop laws/hop.c
```

```bash
.venv/bin/python experiment.py --laws laws/
```

A kernel is loaded only if the judge finds zero violations. More laws: add one to `laws.py` (bits, reachable
words, oracle, principles), then `make_prompts.py` renders its prompt and `judge.py` judges its kernel.

## What was measured (`results/RESULT.md`, 60 seeded jobs per cell; two runs, identical)

**1. Composition - the big one.** Jobs whose faults need taught classes from k different nets:

| | k = 1 | k = 2 | k = 3 |
|---|---|---|---|
| static fluidnet, every shape | 300/300 | **0/300** | **0/300** |
| on the shape, partial repair carried | 300/300 | **300/300** | **300/300** |

Static fluidnet cannot compose across nets: every net starts over, none reaches green alone. On the
600-cell it also tries all 60 nets per refused job - 2,007 suite runs against 98 on the shape. But the
**star+carry control does as well as the shape** (88 runs): this win is *carrying*, which the shape makes
natural, not the geometry itself.

**2. Traffic.** Same jobs, same dictionaries, different wiring:

- No overseer: the busiest node carries 10-27% of all messages, against 50% through the overseer - and
  there is no single point whose death stops everything.
- Hops per job: fewer than the star on the 16-, 8- and 24-cell; more on the 600-cell (9.60 against 7.73).
- **A random regular graph with the same links per node does about as well** - 8-cell 6.07 vs 6.05 hops,
  24-cell 5.30 vs 5.83, 600-cell 9.60 vs 7.92. The polytopes do not win on hop count. What they have that a random graph does not:
  every node identical (one law serves all), routing from geometry instead of tables (one XOR on the
  8-cell), and antipodes.

**3. Resilience.** Single-fault jobs; dead nets:

| local outage (a node and all its neighbours) | fluidnet as built | antipodal mirror | random mirror |
|---|---|---|---|
| 8-cell | 38/60 | **60/60** | 48/60 |
| 24-cell | 39/60 | **60/60** | 50/60 |
| 600-cell | 53/60 | **60/60** | 59/60 |
| 16-cell | 9/60 | 15/60 | 17/60 |

Under independent failures, any second copy helps and placement does not matter. Under a **local outage**,
the antipodal copy survives every time on the 8-, 24- and 600-cell - the measured geometric advantage. The
16-cell is the honest exception: a node and its neighbours are 7 of its 8 nodes, and its antipode shares
all of them; with 5 of its 8 nets dead, random pairing beats antipodal there (44/60 against 33/60).
Routing alone adds nothing to resilience - the shape with no copies scores exactly what fluidnet as built
scores, cell for cell; the copies are what help.

## What this does not show yet

- Most taught classes are synthetic `rename-j` migrations; only two (`len-as-last-index`,
  `wrong-attribute-sibling`) are fluidnet's real taught classes. The shipped nine are fluidfix's own.
- Tests run in-process, deterministic and memoised - so `STABLE` is always set and RECHECK never fires.
  fluidnet runs each verdict in a subprocess.
- Jobs run one at a time: no queues, so ADMIT, and STEP's load lanes (`ROOM`, `QUIET`, `FULL`), are
  constant here, and QUORUM is not exercised. Next: concurrent jobs, a 5-cell quorum certifying patches,
  and real `fluidfix guard` processes as nets on real repositories.
- Strict mode certifies nothing here: every job carries a shipped-class fault, and fluidfix ships no
  property for its shipped classes - so CARRY's `STRICT` refuses, exactly as its principle C3 says.

## Files

| file | what |
|---|---|
| `polytopes.py` | the six 4D polytopes as graphs; every invariant measured, checked against Coxeter |
| `laws.py` | the seven laws: bits, reachable words, oracles, principles as enumeration checks |
| `anchors.py` | anchors computed on the real shapes and recorded from real swarm runs |
| `make_prompts.py` | renders `prompts/` - nothing typed that can be computed |
| `judge.py` | judges a kernel (`.c` or `.py`) exhaustively; `--selftest` |
| `replay.py` | HOP and STEP replayed on the real shapes with dead nodes |
| `classes.py`, `jobs.py`, `fnet.py` | fluidfix's classes, generated red jobs, one net's descent |
| `swarm.py` | static fluidnet, the star+carry control, and fluidnet on the shape |
| `experiment.py` | E1-E3 -> `results/RESULT.md` |

Set up: `python3 -m venv .venv && .venv/bin/pip install fluidfix==0.16.0 numpy`.

---

## v2 - a 4D structure for fluidfix's vector generalization law (in progress)

v1 is frozen in `v1/`. v2 asks the question one level down: fluidfix's **router**
(`route(F1, A1, Fq) == (Fq + A1 - F1) mod 16`, authored by a program-synthesis engine) is its vector generalization
law - one worked example, a whole relabelling inferred. Its structure is a ring of 16. Can a 4D structure
generalise better? **No law is authored here** - the prompt is for you.

| | |
|---|---|
| `generalize.py` | measures, by version space, what each structure lets ANY law know -> `results/GENERALIZE.md` |
| `prompts/ROUTER4D_LAW_PROMPT.md` | the superoptimizer task: the defect, the structures, your choices, G0-G5 |
| `judge_router4d.py` | judges your kernel against the class you declare; `--calibrate` judges fluidfix's own router |

Measured: one worked example leaves the router **confidently wrong on 62-92%** of queries whenever the true
relabelling is not a ring translation. A law confined to the 8-cell's 384 symmetries is wrong on at most 6% outside
its class - it refuses instead - and covers 24x the relabellings, at the price of more worked examples (90% of
queries answered at k = 5). The 600-cell's rotations: 7,200 relabellings of 120 kinds, pinned by 4 examples.
Whether real vocabularies follow any of these is measured next, on fluid-router's 33-bug corpus.
