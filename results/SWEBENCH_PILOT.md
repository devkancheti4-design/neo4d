# SWE-bench Lite: the smoke test, the design runs and the stopped pilot (2026-10-22)

qwen2.5-coder:7b (ollama, NVIDIA L4), `neo4d/swe_agent.py`; scored by SWE-bench's harness (swebench 5.0.2,
`SWE-bench/SWE-bench_Lite`). Every trajectory, prediction and official report is in
`results/data/swebench_2026-10-22/runs.tar.gz` (logs left out). The commands are those of `docs/SWEBENCH.md`; the agent
ran with swebench 4.1.0 installed (its table of each project's test command, which swebench 5 dropped).

**This is not a result.** The pilot was stopped by the owner after two of its three seeds; the numbers below are a
record, not evidence for or against neo4d.

| run | issues | model alone resolved | neo4d (mutation) resolved | commit |
|---|---|---|---|---|
| smoke (django__django-11099, Lite) | 1 | 0 | 0 | 4adb45c |
| design v0, 25 SWE-bench issues not in Lite | 25 | 0 | 0 | 4adb45c |
| design v1 (reproductions must import the package; localisation by identifier specificity) | 25 | 0 | 1 | 26fed29 |
| pilot seed 0, Lite | 25 | 1 | 2 | 26fed29 |
| pilot seed 1, Lite | 25 | 1 | 1 | 26fed29 |
| pilot seed 2 | - | not run | not run | - |

- Across the two pilot seeds: 2/50 alone, 3/50 with neo4d; neo4d's mutations shipped no fix in the pilot (227 variants
  tried); the extra issue (django__django-14382) came after neo4d's feedback changed the model's later tries.
- Design changes were made on 25 SWE-bench issues that are not in Lite (`ids_design.txt` in the archive), after the
  smoke test showed the reproduction scripts often did not touch the repository and the test command was missing.
- The `neo4d_full` condition (PICK, SHIP, RELATE v2 memory, attention marks; `neo4d/swe_full.py`) was started on the
  design issues and stopped after 3 of 25; it was never run on Lite.
- The commits above are on the branch `swebench-pilot-2026-10-22`.
