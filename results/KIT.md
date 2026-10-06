# The kit - the five directions, tested, and the laws they need

Each direction was turned into a test that can fail. All five run from the CLI (`neo4d kit-scaling`, `kit-language`,
`kit-outage`, `kit-federation`, `kit-proof`); every number below comes from the generated reports linked in each row.
**Checks failed across the kit: 0.**

| direction | what was tested | what came out | a new law? |
|---|---|---|---|
| **1. Beyond affine** ([KIT_SCALING](KIT_SCALING.md)) | projective maps; bigger spaces GF(2)^5, GF(2)^6; homology of control flow on QuixBugs | Over GF(2) the projective group *is* the linear group: 20,160 = 20,160 relabellings, nothing new. 32 kinds need 6 examples and a **65-bit** word (an int64 holds 64); 6 random cases pin a map only 128/261 = 49% of the time (16 kinds, 5 cases: 8/13). The fix changes cycle rank in only 2 of 40 programs, and cycle rank alone cannot say logic is missing | **Not now.** A 32-kind router law (two words) becomes necessary when the vocabulary passes 16 kinds; projective and homology need none |
| **2. One numbering for every language** ([KIT_LANGUAGE](KIT_LANGUAGE.md)) | the same 40 bugs in Python and Java, patch level (no Java runtime here) | The same 4-bit kind fixes the same bug in both languages in 4 programs (3 text-exact, 1 equivalent); 1 real gap - `len(x)` vs `x.length`. 4 of 40 fixes in each language only ADD a line, and nothing in the vocabulary generates that | **No.** Body work: language-aware spellings in the classes, and fluidnet's omission path |
| **3. Swarm plasticity** ([KIT_OUTAGE](KIT_OUTAGE.md)) | 25 / 50 / 75% of nodes dead, at once and one at a time, on the swarm's own graphs and a random control | Lost knowledge dominates, not cut-off: 600-cell at 75% dead loses 56% of dictionaries and cuts off 9%. The 4D shapes do no better than a random 12-regular graph (2.5% cut off at 75%). Relocation removes the loss up to 50% dead, but the placement leaves no room, and every copy costs classes: one copy per class keeps the most knowledge, (1 - p) S against (1 - p^2) S/2 | **No.** How many copies to keep is a storage budget set in the body, not a decision made per event |
| **4. Immune system / formal verification** ([KIT_PROOF](KIT_PROOF.md)) | route4d5 against an independent Gaussian-elimination reference on every reduced word | **68,719,476,736 words, 0 mismatches**; the determined count equals its closed form (7,271,038,351). route4d: all 1,048,576 reduced words, 0 violations. The 8-bit laws are enumerated by their judges | **No.** Every authored kernel is now checked on its whole input space, and route4d5 is also proved by CBMC on all 2^64 words; SHIP is the immune response |
| **5. Federation** ([KIT_FEDERATION](KIT_FEDERATION.md)) | two installations with different numberings merge from shared anchors only, through route4d5 | Affine numberings: 5 span-aware anchors transfer the whole act table, **0 wrong** (random anchors: 80.8% right, the rest refused). Arbitrary numbering: 5 queries in 13 wrong from 5 anchors, 0.03% at 8 - validation anchors, the same router. **Not zero-knowledge**: the anchors and the learned map reveal both numberings | **No integer law can make it zero-knowledge** - that needs a cryptographic protocol |

## The verdict on laws

**None of the five directions needs a new law today.** The decisions they raise are already covered:
- route4d5 covers translation between numberings.
- SHIP covers refusal and certification.
- The rest are body parameters: the copy budget, language spellings, the omission path.

**One law becomes necessary later:** a router for 32 kinds, once neo4d's vocabulary grows past the 16 kinds four bits
can name. Today it uses 11.
- It needs 6 examples instead of 5, and an input of 65 bits instead of 44, so it reads two words.
- Random cases pin a map less often: 128/261 for 6 cases, against 8/13 for 16 kinds with 5.

Its prompt is written: `prompts/ROUTER5_LAW_PROMPT.md`, with its judge (`python -m neo4d.judge_router5`), a brute-force selfcheck over all 9,999,360 maps of GL(5,2), and a CBMC proof harness waiting for the law.

## What the kit does not show

- The Java side is patch-level only; its tests were not run.
- The outage numbers are structural (who can reach which dictionary), not repair runs. The relocation rule is the
  simplest one (least-loaded live node), measured as a ceiling.
- The exhaustive proof covers route4d5's behaviour, not whether five examples are the right evidence for a real
  repair. The live and exact tests measure that.
