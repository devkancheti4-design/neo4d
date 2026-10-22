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

## By exact math (`neo4d exact`, `results/EXACT_MATH.md`)

Closed forms over the affine group of GF(2)^4, each checked by brute force or simulation:

| | exact |
|---|---|
| maps surviving examples of rank r = 0..4 | 20,160 / 1,344 / 96 / 8 / 1 - prod (16 - 2^i), i = r..3 |
| examples that pin a whole relabelling | ring **1** (16 maps), neo4d **5** (322,560 maps), structure-free **15** (16! maps) |
| five random cases pin it | **8/13**; chosen span-aware: **1** |
| a truth outside the structure (random permutation) | right **3/13**, refused **5/13**, wrong **5/13** - simulated 23.09 / 38.30 / 38.61% |
| a ghost query (rank-3 span) | any guess right at most **1/8**; neo4d wrong **0** |
| test runs to learn one relabelling | neo4d **20**, structure-free 60, every kind 64 |

## Its inductive bias (`neo4d inductive`, `results/INDUCTIVE.md`)

| test | result |
|---|---|
| shootout: a random affine relabelling from N examples, unseen codes | neo4d **100% right, 0% wrong from N = 5** (refuses what is undetermined below 5); a 3-layer MLP and a small Transformer, trained on the same N and predicting the output bits: **0-12% right at every N up to 15** |
| shard: affinity broken by degree eps = 0 ... 1 | neo4d exact at eps = 0, settling at the exact 3/13 / 5/13 / 5/13 by eps = 0.6; the MLP is wrong on 98-99% of unseen codes throughout |
| active vs passive: examples until pinned | active (new direction only) **5, always** - the minimum possible; passive expected **215/39 = 5.51** (simulated 5.51) |
| out-of-distribution: five examples in the top-bit-0 subspace, a query with it set | refused **100%**, wrong **0%** |
| degeneracy (`neo4d degeneracy`): 10 redundant examples spanning only rank 2 | in-plane queries **100% right**, out-of-plane **100% refused**, **0 wrong**; every 5-subset agrees |
| one-bit contradictions: a repeated case or a dependent case, one action bit flipped | brute force finds no map in all 40,000; router refuses **640,000 / 640,000** queries |
| validation points against a non-affine truth, k = 5..8 | wrong **5/13 -> 9/286 -> 2/715 -> 7/25,740** exact (simulated 38.41 / 3.11 / 0.27 / 0.026%); zero only at k = 16 |

## The kit - five directions, tested (`results/KIT.md`)

| direction | result | new law? |
|---|---|---|
| beyond affine (`neo4d kit-scaling`) | projective = linear over GF(2) (20,160 = 20,160); 32 kinds need 6 examples and a 65-bit word; cycle rank moves in 2 of 40 fixes | a 32-kind router - **authored, judged and proved: `route5`** |
| one numbering across languages (`kit-language`) | same kind fixes the same bug in Python and Java in 4 programs; one spelling gap (`len(x)` / `x.length`); 4 of 40 fixes only add a line | no - body work |
| swarm outage (`kit-outage`) | knowledge is lost far more than cut off; 4D shapes no better than a random graph of the same degree; copies cost classes | no - a copy budget |
| formal verification (`kit-proof`) | route4d5 on **all 68,719,476,736 reduced words: 0 mismatches** against an independent reference, and **proved by CBMC on all 2^64 words**; route4d on all 1,048,576 | no - every kernel now checked on its whole input space |
| federation (`kit-federation`) | 5 span-aware anchors transfer a whole table between affine numberings, 0 wrong; **not zero-knowledge** | no integer law can supply that |

## A brain for models - local models, Claude Haiku, Claude Sonnet (`results/LOCAL_*.md`)

neo4d as the core that decides and remembers; a model reads and writes. Every model call is counted; the raw runs of
Haiku and Sonnet (run as subagents through the same tools) are in `results/data/`.

| test | without neo4d | with neo4d |
|---|---|---|
| bug fixing, phi4-mini, 176 tasks (`neo4d local-model`) | 30.7% alone, 42.0% with 3 tries | **62.5%**, 251 calls vs 407 |
| multi-step agent work, phi4-mini, 85 tasks (`neo4d local-agent`) | 25.9% alone, 40.0% with 3 tries | **47.1%** (second half 55.8%), 1,225 calls vs 1,406 |
| the same 85 tasks, Claude Sonnet | 85/85, 418 calls | **85/85, 285 calls** - Sonnet needed on 58 tasks, not 85 |
| the same 85 tasks, Claude Haiku | 84/85, 401 calls | **84/85, 226 calls** - Haiku needed on 51 tasks, not 85 |
| real bugs, round after round until it answers, phi4-mini (`neo4d local-hints --loop`) | 22/31 with test feedback, 154 calls | **25/31, 120 calls** - neo4d mutates each attempt |
| hard bugs (two faults, obfuscated), neo4d searches deep and Haiku only filters | blind search 14/29, 5,815 test runs | **17/29, 2,316 test runs**, 37 Haiku decisions |

What did not help: neo4d's evidence handed to phi4-mini as a paragraph (16/31 against 20 with plain retries - it
dilutes a small model's attention), and anything on bugs Haiku already solves (31/31 and 29/29 alone). neo4d adds
power by doing the work - remembering what worked, searching around a model's attempt, testing - not by advising.

**On SWE-bench:** `neo4d/swe_agent.py` runs the same model with and without neo4d on SWE-bench Lite or Verified, scores both with the official harness and packages the run for the leaderboard - every step in [docs/SWEBENCH.md](docs/SWEBENCH.md).

## The laws - authored externally, judged here

| law | decides | judged |
|---|---|---|
| `route4d` | the relabelling from 3 worked examples, affine GF(2)^4 | 0 violations; every word of its difference space (1,048,576) |
| `route4d5` | the relabelling from 5 worked examples, 64-bit | 0 violations; all 68,719,476,736 reduced words exhaustively; **CBMC proof on all 2^64 words** |
| `route5` | the relabelling for **32 kinds** from 6 worked examples, GL(5,2) | 0 violations on 12M stratified words, 2M renumberings, 64M end-to-end queries (UBSan); **CBMC proof on every word** (8 min, 12 cores); live at 32 kinds: federation at the exact values, 0 wrong in class, every one-bit contradiction refused |
| `relate_v1` | one relation is one neuron: its new strength (unknown / primed / active / proven) on every fix event | 0 violations; the unique table R1-R9 allow, every cell fixed; 54 instructions, 0 branches, 0 memory ops. **Live: real-fix coverage 3.4% -> 10.3% across 49 projects (rising to 13.7%), 0.4% -> 17.4% on click's history (INDUCE: 1.2%)** - `results/RELATE_LIVE.md` |
| `relate_v2` | as v1, but a barren relation weakens even when cheap - a noisy teacher no longer leaves junk rules active | 0 violations; 5 of 114 cells moved, exactly as specified; 48 instructions, 0 branches, 0 memory ops; every 32-bit input clean (CBMC). **Live: 58.4% precision at 10% wrong lessons where v1 falls to 1.9%**; real bugs 10.0% (v1 10.3%), click 17.4% - `results/RELATE_V2.md` |
| `harvest` | keep / skip / recheck / stop one mutation trial | 0 violations; the unique kernel its principles allow |
| `pick` | which mutation to try next | 0 violations; the unique kernel |
| `induce` | admit / keep / retire / reject a newly mined class | 0 violations; the unique kernel |
| `ship` | refuse / ask / ship / ship-proven one candidate repair | 0 violations; the unique kernel; every bit earns its place |

Edge cases against the brute-force group (`neo4d edge`, `results/EDGE_CASES.md`): survivor counts match the group
at every rank (20,160 / 1,344 / 96 / 8 / 1), every contradiction is refused, and 200,000 random scenarios per router
show 0 disagreements.

Stress tests (`results/`):

| test | result |
|---|---|
| obfuscation (`neo4d quixbugs`): 396 names hashed, 1,950 dead statements, formatting stripped | same repair outcome on **40/40** QuixBugs programs; 5 repaired, 1 ambiguous (refused), 34 out of vocabulary |
| ghost-space queries (`neo4d adversarial`): 20,000 queries one bit outside a rank-3 span | neo4d refuses **100%**, wrong **0%**; a nearest-example heuristic is wrong 93.5% |
| noise (`neo4d robustness`): 10 to 10,000 irrelevant fields around the query | **0** answers changed; 5.4-6.2 ns per query (read + route), flat; noise never reaches the router |
| encodings (`neo4d robustness`): codes in IEEE 754 float mantissas; relabellings over GF(16) | **100% right, 0% wrong** for both; a non-affine truth (random permutation) is wrong 38.6% - the structure's limit, stated |
| a million mixed calls in one process (`neo4d robustness`) | **0** differences vs reverse order, shuffled order and a fresh process; 0 vs brute force on 100,000; no writable section in the object |
| silicon (`neo4d silicon`): the compiled routers, M4 Pro | route4d5: 91 instructions, route5: 105 - both **0 conditional branches, 0 memory ops**; route5 **IPC 7.02, 4.03 ns** per call |

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
.venv/bin/neo4d kit-proof              # route4d5 on every one of its 2^36 reduced inputs (~10 min)
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
- INDUCE's learning curve on click's history (`neo4d induce-live`) is **flat** at 1.2%: one-token patterns rarely
  recur. The RELATE law (`neo4d relate-live`) answers it with richer patterns - relations and literal edits as neurons -
  and reaches 17.4% on click and 10.3% across 49 projects; the price is 50-75 candidates per fix line, each a suite run.
- A noisy teacher breaks RELATE's precision: with 10% wrong lessons it falls from 82% to 2% on the mutation domain, because R9 spares cheap relations from weakening. Dropping that one exemption restores 58% (`results/DOMAIN_HARD.md`) - the RELATE v2 law, authored and judged (`results/RELATE_V2.md`). Taught on Python, the mutation domain carries to C at 93% coverage and 85% precision, to C++ and Java at 88-90% coverage but 26-46% precision.
- Topology (`neo4d kit-topology`): in a closed domain the swarm absorbs the domain's rewrite graph exactly - all 70 edges, 7 components, Betti number 19, no junk edge - by 10,000 taught lines; on real bugs the learned graph is still growing at 706 fixes (1.6x from mid-stream to the end), though every order of the bugs reaches the same graph (99% overlap).
- The secret renumberings in the live runs were affine - inside the structure by construction.
- On fluid-router's corpus the numbering decided the winner: 4D wins under a 4D-native numbering, the ring under
  fluidfix's ring numbering.
- The training-time A/B test on a GPU is designed, not run.

## Layout

```
neo4d/kernels/   the nine authored laws in C
neo4d/           judges, the 4D structures, the self-learning loop, benchmarks, the v1 swarm
prompts/         every law's specification
results/         every measurement
docs/            the full accounts
scripts/         benchmark fetch
tests/           the laws, judged
```

License: AGPL-3.0-or-later.
