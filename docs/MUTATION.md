# How neo4d mutates - and where it fits

neo4d's tool is mutation: it changes a candidate in small, systematic steps and lets a checker judge every change. A
model guesses; neo4d turns a close guess into an exact answer and remembers only what was verified. This document
explains each part - with the file that implements it and the result that measured it - and then where the same
machinery fits beyond code, including science. Claims that have not been tested are marked as such.

## 1. The idea

```
model guess  ->  mutate (every small change)  ->  check every variant  ->  ship the first that passes
                                                         |
                                       verified work -> memory (patterns with slots), trusted by the RELATE v2 law
```

A model need not be exactly right; it needs to land close. A near-miss one token away from the answer becomes the
answer, because neo4d tries every one-token change and the checker recognises the right one.

## 2. Mutation in code - the operators

`neo4d/domain_mutation.py` (`mutants`) applies the standard operators of mutation testing to a line's tokens
(`neo4d/relations.py`, `toks`), one change at a time:

| operator | what changes | example |
|---|---|---|
| ROR | a comparison: `<` `<=` `>` `>=` `==` `!=` (and `===` `!==` in JavaScript) | `lo <= hi` -> `lo < hi` |
| AOR | arithmetic: `+` `-` `*` `/` `%` | `a % b` -> `a / b` |
| ASR | an assignment operator: `+=` `-=` `*=` `/=` | `count += 1` -> `count -= 1` |
| LCR | `and` <-> `or` | |
| BCR | `True` <-> `False` | |
| NEG | add or remove a `not` | `if x:` -> `if not x:` |
| CRP | a number: `n` -> `n + 1`, `0` <-> `1` | `range(0, n)` -> `range(1, n)` |
| BRK | `break` <-> `continue` | |
| RET | `return x` -> `return None` | |
| *harder set* ARG, IDX, DEL, UOI | swap two adjacent arguments; a subscript off by one; delete a call statement; `++` <-> `--` (C family) | |

It works in Python, C, C++, Java and JavaScript. On the programs measured here it gives about 3.4 variants per code
line. A mutant is written back into the line's own text, touching only the changed span (`local_model.to_text`).

## 3. Grading every variant

Every variant runs against every test case in a forked process with a time limit (`local_hints.run_all`). For each
case neo4d records pass or fail and the value returned (or the exception's type); a program's own printed output is
ignored. Three counts follow (`local_hints.mutate`):

- **fixed** - failing cases that now pass;
- **broken** - passing cases that now fail;
- **moved** - failing cases whose output changed at all, even if still wrong: the line matters to the failure.

*fixed - broken* ranks near-fixes; *moved* localises the fault, as in mutation-based fault localisation.

## 4. Searching

| search | what it does | file | measured |
|---|---|---|---|
| **around a model's attempt** | every one-token change to the attempt, the lines the model changed first; ship the first that passes, else report the best back | `local_hints.explore`, `loop` | real bugs at an equal budget: as many fixes as the best baseline with 12-35% fewer calls (`results/RIGOR.md`) |
| **deep search** | expand by every one-token change, keep 3, expand again - up to 4 changes deep; cost about M + d·3·M runs, linear in depth | `local_hints.expand`, `shortlist` | hard two-fault bugs: 14 of 29 blind |
| **a model as the filter** | at each level a model picks which 3 of the 12 most promising candidates go deeper; it writes no code | `local_hints.search_cli` | 17 of 29 with Haiku against 12.0 random, 60% fewer test runs |
| **coverage-guided** | only the lines the failing tests execute, ranked by suspicion (Ochiai) | `rigor.coverage`, `ochiai` | a fix in 5.5 runs (median) at any file size, against 222 when every line is searched in a 31-function file; misses 7 of 93 faults that sit on lines no failing test runs |

## 5. Learning by mutation - generalising to unseen code

Taught examples of a domain's mutations (`domain_mutation.teach`), neo4d turns each into **neurons**:

- `lit` - the literal edit (`< -> <=`);
- `rel` - a **relation** with placeholders: identifiers become `$I1, $I2 ...`, numbers `$N1 ...`; a new identifier in
  the fix becomes `~$Ik` (a near copy), `@ctx` (a name already in scope) or `?id` (cannot be generated). So
  `count + 1 -> count + 2` and `size - 1 -> size - 2` are one relation, `$I1 + $N1 -> $I1 + $N1+1`;
- `ctx`, `ctx2`, `ctxlr` - the relation anchored by one or two tokens around it.

A relation *generates*: applied to an unseen line it proposes every line it can make. Measured (`results/PROOF_JS.md`):
300 taught lines of JavaScript reach **85.8%** of the real mutants in packages never seen (97.3% after 30,000), and
10,000 lines of Python with **no** JavaScript reach 59.6% of new JavaScript packages.

## 6. Remembering - plans with slots, governed by a law

Verified work is abstracted so it applies again:

- **plans** (`local_agent.abstract`, `replay`): a tool trace with the task's names turned into slots
  (`replace qb/<1>.py "<1>(" -> "<2>("`), a step repeated over every file a search found as one looping step, an
  answer derived from what a search found;
- **patterns** in the domain-free core (`core.Memory`): any domain's verified solution, abstracted by its adapter.

Each pattern has a level - unknown, primed, active, proven - set by **RELATE v2** (`neo4d/kernels/relate_v2.c`) from
six bits of evidence: it fired, in a new place, it predicted correctly, it is cheap or costly to use, it keeps failing
(barren). The law is branch-free, checked on all 2^32 inputs, and proved never to erase a proven pattern or keep a
barren one active. Measured (`results/RIGOR.md`): with 10% wrong lessons, memory stays **58.4%** correct under the law
against **0.9%** without it - slots make plans reusable (85 -> 58 tasks needing Sonnet); the law keeps memory clean
when lessons can be wrong.

## 7. The domain-free core

`neo4d/core.py` holds the loop, the search, memory and the law with no domain in it (a test checks that it names
none). A domain supplies an adapter (`neo4d/domains/`):

| method | what the domain says |
|---|---|
| `prompt`, `parse` | how to ask a model, how to read its answer |
| `check` | right or wrong, and a partial score in 0..1 - never the answer itself |
| `variants` | every one-step change of a candidate |
| `key`, `abstract`, `instantiate` | the task's shape with names removed; a solution as a pattern with slots; the pattern filled in for a new task |
| `start` | where search begins without a model |

Two adapters exist besides code: **Countdown** (reach a target with given numbers; variants change an operator, swap or
replace a number, insert or delete a term, regroup) and **Blocks world** (restack blocks; variants delete, swap,
redirect or insert a move). In design runs, the core's search with no model solved about half of each; whether the core
*raises a small model* outside code is being measured (`results/CORE.md`, `neo4d/core_experiment.py`).

### Writing a new adapter

```python
from neo4d.core import Domain

class Formula(Domain):
    name = "formula"
    def prompt(self, task, feedback=None): ...      # describe the task; add the feedback line if any
    def parse(self, task, reply): ...               # -> a hashable candidate, or None
    def check(self, task, cand): ...                # -> (solved, score 0..1, a short note) - never reveal the answer
    def variants(self, task, cand): ...             # yield every one-step change
    def key(self, task): ...                        # the task's shape, names removed
    def abstract(self, task, cand): ...             # the solution with names as slots
    def instantiate(self, task, pattern): ...       # the pattern filled in for this task
    def start(self, task): ...                      # a candidate to search from without a model
```

Then `core.solve(dom, task, model, "core", core.Memory(law))`. Test the checker on known answers, test that variants
repair a near-miss, and test that a pattern replays on a new task of the same shape (`tests/test_core.py`).

## 8. Where it fits - beyond code

The core needs three things, none specific to software:

1. **something to mutate** - a representation with small, meaningful steps;
2. **a checker** - right or wrong, ideally with a partial score, that cannot be gamed;
3. **work that recurs** - so that remembering pays.

| field | mutate | checker | status |
|---|---|---|---|
| software | tokens, lines, tool steps | tests, a check of the result | **measured** (this repository) |
| puzzles, planning | numbers and operators; moves | exact evaluation; a simulator | **measuring** (`results/CORE.md`) |
| equation discovery | operators, constants, terms of a formula | fit to held-out data | not tested - the closest next step (Countdown's expression mutations apply) |
| mathematics | proof steps | a proof checker (e.g. Lean) | not tested |
| molecules, materials | substitutions, edits of a structure | a simulator or a scoring model | not tested |
| experiments | parameters | a simulation | not tested |

Why neo4d's law could matter in science: measurements are noisy, so some "verified" results are wrong - the setting in
which the law kept memory 58.4% correct against 0.9% without it. Model-plus-evolutionary-search systems for science
(for example DeepMind's FunSearch) already show that a model proposing and a program checking can discover; neo4d adds
cheap exhaustive local mutation, verified memory, and a formally checked rule for what to trust.

The limits, plainly: each field needs its own adapter; the checker is everything - a scoring model that can be gamed
will be gamed; real laboratory experiments are slow and costly, so the checker is usually a simulation; and none of the
rows marked "not tested" has evidence yet.

## 9. What has been measured

| result | file |
|---|---|
| bug fixing, a small model with and without neo4d | `results/LOCAL_MODEL.md` |
| multi-step agent work; Claude Haiku and Sonnet | `results/LOCAL_AGENT.md` |
| real bugs: evidence, exchange, deep search, a model as filter, attention marks | `results/LOCAL_HINTS.md` |
| ablations, random control, coverage-guided search, equal-budget baselines | `results/RIGOR.md` |
| learning a mutation domain; unseen code and languages | `results/DOMAIN_MUTATION.md`, `results/PROOF_*.md` |
| the law, judged and run live | `results/RELATE_V2.md` |
| the core on domains that are not code | `results/CORE.md` (in progress) |
