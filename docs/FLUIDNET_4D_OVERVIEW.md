# fluidnet 4D

**A model-free code-repair system: small rule-based repair nets, each taught a few bug shapes once, arranged on a
regular 4D polytope — so a broken file can travel between them collecting test-proven fixes — with every decision
made by tiny, exhaustively verified integer laws, and a 4D router that generalises what was taught across up to
20,000x more relabellings than fluidnet's ring.**

Everything below is measured by code in this folder; every number names the file that produced it. Nothing was
tuned per case. Where something is estimated, or not shown, it says so.

---

## 1. The idea in three sentences

fluidnet (github.com/devkancheti4-design/fluidnet) repairs the bug shapes you teach it — no model, a proof per fix —
using many small nets under one overseer, because each net's dictionary is capped at 7 taught classes. It is built
**static**: an overseer tries each net alone from the original code, and its generalisation law (the router) works
on a ring of 16. **fluidnet 4D** puts the nets on a 4D shape so partial repairs can travel between them, and gives
the router a 4D structure so one worked example generalises much further — while the AI, where it is used at all,
only points at the bug.

```
   AI (optional)            4D swarm of nets                               4D router
   "the bug is at   --->    job travels node to node, each net     --->    one worked example generalises
    parser.py:437"          adds the fixes it knows; only a                 across 322,560 relabellings
                            green, certified module ships                   (affine GF(2)^4), or 120 kinds
                                                                            (600-cell) - and refuses when unsure
```

---

## 2. The six 4D shapes, measured (`polytopes.py`)

Every invariant is computed from coordinates and checked against Coxeter's table (0 disagreements).

| shape | nodes | links each | diameter | node-disjoint routes | antipode | pairs with a choice of nearer neighbour |
|---|---|---|---|---|---|---|
| 5-cell | 5 | 4 | 1 | 4 | no | 0% |
| 8-cell (tesseract) | 16 | 4 | 4 | 4 | yes | 73% |
| 16-cell | 8 | 6 | 2 | 6 | yes | 14% |
| 24-cell | 24 | 8 | 3 | 8 | yes | 30% |
| 120-cell | 600 | 4 | 15 | 4 | yes | 31% |
| 600-cell | 120 | 12 | 5 | 12 | yes | 60% |

What each gives a swarm:

- **8-cell:** a node's id *is* its address — linked iff the ids differ in one bit, distance = popcount(a XOR b).
  Routing needs one XOR, no table. 24 shortest routes to the antipode.
- **5-cell:** everyone is one hop from everyone — a vote finishes in one round.
- **all but the 5-cell:** a unique antipode at maximum distance, never a neighbour — the natural place for a copy.
  On the 8-, 24-, 120- and 600-cell the antipode's neighbours are disjoint from the home's.
- **every shape:** node-disjoint routes = links per node, so it stays connected through links − 1 failures.
- Honest: the 24-, 120- and 600-cell are *not* distance-regular (the measurement caught it); random graphs with the
  same degree have equal or smaller diameter.

---

## 3. The laws

fluidnet's rule, kept: **the law decides and the body only measures.** Eight measured bits in, one decision out,
branchless integer arithmetic, verified by enumeration.

### The swarm laws — prompts for your superoptimizer (`prompts/`, specs in `laws.py`)

| law | decides | shape |
|---|---|---|
| HOP | which link to cross — one XOR | 8-cell |
| STEP | how good one neighbour is as the next hop | every shape |
| MIRROR | home or antipodal copy; when to repair | the 5 antipodal shapes |
| CARRY | after a net works on a job: carry, accept, recheck, refuse | every shape |
| SEEK | which net holding a wanted dictionary to visit next | every shape |
| ADMIT | what a net does with an arriving job | every shape |
| QUORUM | commit / abort / wait on a one-round 5-way vote | 5-cell |

Each prompt carries bits, principles, the full 256-word truth table, anchors computed on the real shapes, and the
judge. **The principles fix every table**: all 10,343 single-cell changes across the seven tables break at least
one principle (`judge.py --selftest`). Until kernels arrive the swarm runs on the reference tables.

### The vector generalisation law — authored by you (`laws/router4d.c`)

fluidfix's only decision-maker is the router, `route(F1, A1, Fq) = (Fq + A1 - F1) mod 16` (fluid-router,
authored by a program-synthesis engine): one worked example, a whole relabelling inferred, on a **ring of 16**.

`prompts/ROUTER4D_LAW_PROMPT.md` posed it on a 4D structure without authoring it. Your engine returned
`route4d`: the router on **affine maps of GF(2)^4**, k = 3 worked examples, refusing when the examples do not
determine the answer.

**Judged independently here (`judge_router4d.py`): 0 violations.**

- 30,000 seeded words and 20,000 renumbering draws: G0–G5, 0 violations
- **every one of the 1,048,576 words of the difference space**, against a brute-force version space: 0 violations
- the counts match yours exactly: 177,751 determined, 538,665 open inside the class, 332,160 with no affine map
- calibration: fluidfix's own router judged by the same judge scores 0 violations as the ring law — and fails
  every 4D class

The only law in fluidfix bound to 16 kinds is the router: the engine, rank, sight and pair laws read evidence
bytes, never kind numbers; the lanes (`m & -m`) are width-agnostic but verified only at 8 bits.

---

## 4. How much 4D increases generalisation (`generalize.py`, `results/GENERALIZE.md`)

Every number is a **version space** — the relabellings a structure leaves consistent with the worked examples — so
it bounds what *any* law on that structure can know.

| | static fluidnet (ring) | 4D | increase |
|---|---|---|---|
| relabellings it generalises across | 16 | 384 (8-cell symmetries) / **322,560** (affine — your law) | **24x / 20,160x** |
| kinds one router handles | 16 | 120 (600-cell, one example) | **7.5x** |
| taught classes per net | 7 | ~111 (600-cell router) | **~16x** |
| rotations, 120 kinds | — | 7,200 (600-cell, 4 examples) | **450x** |
| wrong when the truth is outside its structure | **58–88%** (your harness) / 62–92% (mine) | **0%** on every 4D class (your law) | confidently wrong -> never wrong |

**The price:** more worked examples (1 -> 3–8), and refusals. At k = 3 your law answers 22.5% of queries — 25% is
the ceiling for *any* affine law at k = 3 — and refuses the rest; on ring truths it is wrong 2.2% (yours) / 2.7%
(mine), because an affine map can fit three points of a rotation by coincidence.

Why 4D fits fluidfix's classes structurally: most shipped classes are **flips** (`<`<->`<=`, `+`<->`-`,
`True`<->`False`, `min`<->`max`). A flip is its own inverse. The ring has room for exactly one such flip as a
translation; the 8-cell's vector space GF(2)^4 has fifteen, all at once.

---

## 5. fluidnet on a 4D shape — the swarm (v1, frozen in `v1/`; `experiment.py`, `results/RESULT.md`)

Same nets, same dictionaries, same jobs (fluidfix 0.16.0's nine shipped classes in every net, at most seven taught
per net, fluidnet's own descent); 60 seeded jobs per cell; two runs, identical.

**Composition** — faults whose taught classes live in k different nets:

| | k = 1 | k = 2 | k = 3 |
|---|---|---|---|
| static fluidnet, every shape | 300/300 | **0/300** | **0/300** |
| on the shape, partial repair carried | 300/300 | **300/300** | **300/300** |

On the 600-cell, k = 2: 2,007 suite runs (static tries all 60 nets) against 98. Honest: a star overseer that also
carries partial repairs does as well (88 runs) — this win is *carrying*, which the shape makes natural.

**Traffic:** no overseer — the busiest node carries 10–27% of messages instead of 50%, and nothing is a single
point of failure. Hops: fewer than the star on the 16-, 8- and 24-cell, more on the 600-cell (9.60 vs 7.73); a
random graph with the same links does about as well (8-cell 6.07 vs 6.05).

**Resilience** — a local outage (a node and all its neighbours):

| | fluidnet as built | antipodal copy | random copy |
|---|---|---|---|
| 8-cell | 38/60 | **60/60** | 48/60 |
| 24-cell | 39/60 | **60/60** | 50/60 |
| 600-cell | 53/60 | **60/60** | 59/60 |
| 16-cell | 9/60 | 15/60 | 17/60 |

Routing alone adds nothing to resilience (no copies = fluidnet as built, cell for cell); the antipodal copy is the
geometric win. The 16-cell is the exception — its antipode shares all of a node's neighbours.

The HOP law replayed on the real 8-cell (`replay.py`): 100% delivered with any 1 or 2 dead nodes, 99.87% with 3.

---

## 6. On real bugs (`realfix.py`, `results/REALFIX.md`)

Fix patches of three real benchmarks, 1,729 bugs, nothing executed:

| | BugsInPy (Python) | Defects4J (Java) | Defects4C (C/C++) |
|---|---|---|---|
| bugs | 501 | 864 | 364 |
| every changed line generated by fluidfix's 9 shipped classes | **1** | **9** | **4** |

Only 57 of 1,729 real fixes swap one operator or literal token; 51% of those are flips (the reverse also occurs).
Held out, 10-fold: ring 21/57, XOR 21/57, 8-cell symmetries 19/57, plain table 23/57 — **the data is too small to
prefer any structure**. The 4D advantage above is structural; whether real vocabularies use all of it is open.

---

## 7. AI locates, fluidnet fixes — tokens (fluidnet's recorded click race)

Ten real click bugs (click 06b2a67, 2,240 tests), recorded by fluidnet's own race:

| | tokens, 10 bugs | beyond the AI runtime's fixed ~44k per call |
|---|---|---|
| AI agent locates **and** fixes | 506,431 | 68,801 |
| **AI points, fluidnet fixes** | 481,390 | 43,760 |
| saved | **5%** | **36%** |

- What is saved is the *fix*, not the locating — the AI still reads to point. So
  **saved ≈ coverage x fix share**: coverage = located bugs the vocabulary can fix (fluidnet's real-history study:
  16% exact repeats, 38–43% pattern families as teaching grows); fix share = 36% on one-token bugs, expected higher
  on 5–20-line bugs (91% of real fixes are ≤20 lines, per fluidnet), not yet measured.
- The big lever is a **lean pointer**: the race's pointer went through a full agent runtime (~47k tokens); a
  facts-only call should be ~1–5k. Not measurable here — this machine's Claude CLI reports "Credit balance is too low".
- **Where 4D fits:** vocabulary capacity — 7 -> ~111 classes per net — so coverage can rise, so tokens fall.

---

## 8. Green benchmark — energy per certified repair (`green.py`; in progress)

fluidnet re-run here on the race's bugs (Apple M4 Pro, whole-system power telemetry, CPU-seconds of fluidnet's own
processes); the agent's run is the race's recorded one, its energy **estimated** from Epoch AI's serving model.

| bug 6764, `parser.py:437` (`<` planted as `<=`) | fluidnet, measured | AI agent, recorded |
|---|---|---|
| result | byte-exact, 2,240 tests green, certified | byte-exact, unchecked |
| time | 285 s | 63 s |
| tokens | 0 | 55,985 |
| energy | 280 CPU-s; ~4.0 kJ above idle, 5.9 kJ whole machine | ~2–66 kJ estimated (cached-overhead to Epoch's pessimistic model) |

Where fluidnet's time goes: **locating the line, 90%** (buggy's mutation testing, 257 s); the taught repair plus
certification, 10% (27 s); the laws, microseconds. "Taught means instant" holds once the line is known.

Honest: fluidnet is inside the agent's estimated range, likely at the low end — not near-zero; its energy is its
own test runs. The power telemetry updates every ~30–60 s and a browser was busy, so the whole-machine figure is a
cross-check, not the headline. This run's fluidfix (0.16.0, PyPI) lacks `repair --focus`, so fluidnet's uniqueness
check was skipped. The other 8 bugs, the AI-pointer arm, and the per-core calibration are running.

---

## 9. What is not shown

- Live AI arms: blocked — no credit on this machine's Claude CLI.
- The swarm's taught classes are mostly synthetic `rename-j` migrations; two are fluidnet's real taught classes,
  nine are fluidfix's shipped ones. Its tests run in-process (fluidnet uses a subprocess).
- ADMIT and QUORUM are specified and judged but not yet exercised (jobs ran one at a time).
- Whether real fault vocabularies follow the 4D structures — the decisive test is fluid-router's 33-bug corpus,
  renumbered by each class.
- The green benchmark's agent energy is estimated, not measured.

---

## 10. Run it

```bash
python3 -m venv .venv && .venv/bin/pip install fluidfix==0.16.0 numpy pytest
.venv/bin/python polytopes.py                                   # the shapes, measured
.venv/bin/python judge.py --selftest                            # the seven swarm laws
.venv/bin/python judge_router4d.py --class affine --k 3 --name route4d --sample 30000 laws/router4d.c
.venv/bin/python judge_router4d.py --calibrate                  # fluidfix's router through the same judge
.venv/bin/python generalize.py                                  # how much 4D generalises
.venv/bin/python experiment.py                                  # the swarm (v1)
.venv/bin/python realfix.py                                     # real bugs
.venv/bin/python green.py --all && .venv/bin/python green_report.py   # energy
```

| file | what |
|---|---|
| `polytopes.py` | the six polytopes as graphs; every invariant measured |
| `laws.py`, `anchors.py`, `make_prompts.py`, `judge.py` | the seven swarm laws, their prompts and judge |
| `prompts/ROUTER4D_LAW_PROMPT.md`, `laws/router4d.c`, `judge_router4d.py` | the 4D router: prompt, your kernel, judge |
| `generalize.py` | version-space measurement of every structure |
| `classes.py`, `jobs.py`, `fnet.py`, `swarm.py`, `experiment.py` | fluidnet on the shape (v1) |
| `replay.py` | HOP and STEP replayed with dead nodes |
| `realfix.py` | BugsInPy, Defects4J, Defects4C fix patches |
| `green.py`, `green_report.py`, `calibrate_core.py` | the energy benchmark |
| `v1/` | the swarm experiment, frozen |
| `results/` | every result file quoted here |

Sources: fluidnet and fluid-router (github.com/devkancheti4-design); Epoch AI, *How much energy does ChatGPT use?*
(epoch.ai/gradient-updates/how-much-energy-does-chatgpt-use); BugsInPy, Defects4J, Defects4C (their GitHub repos).
