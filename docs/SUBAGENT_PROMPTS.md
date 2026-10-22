# The prompts given to Claude subagents

Claude Haiku and Claude Sonnet were run as subagents (Claude Code's Agent tool, `model: haiku` / `model: sonnet`,
`subagent_type: general-purpose`). These are their prompts, verbatim except that this machine's paths are written as
`<REPO>` (the repository root) and `<PYTHON>` (the virtual environment's python). Reuse them unchanged for comparable
runs; a changed prompt is a new condition and must be reported as one.

How they were run:
- **agent work** (`results/LOCAL_AGENT.md`): run names `haiku` and `sonnet`, three subagents per model, task ids
  0-28, 29-56 and 57-84 (the stream order of `make_tasks` in `neo4d/local_agent.py`).
- **real bugs** (`results/LOCAL_HINTS.md`): run names `haiku-tests` and `haiku-exchange`, two subagents each, bugs in
  the order of `.build/hints/bugs.json` split 16 / 15.
- **hard bugs**: `haiku-hard-tests`, `haiku-hard-exchange`, `haiku-hard-search`, two subagents each, ids 15 / 14.
- One subagent stopped after reaching the action limit on a task and was told: "Please continue: task N is over
  (reaching the 10-action limit ends a task; its result stands as it is), so carry on with tasks ... in order, under
  exactly the same rules and the same commands. Whenever a task hits the 10-action limit, simply move on to the next
  ID." Nothing else was ever sent to a subagent during a run.

## 1. Agent work (`neo4d/local_agent.py`, run name `RUN` = haiku | sonnet)

```
You are acting as a coding agent on a series of small tasks in a sandboxed Python project. This is a benchmark: work honestly and only through the interface below.

THE ONLY WAY TO INTERACT with the project is this command, run with the Bash tool:

  Start a task (shows the task text; creates a fresh working copy):
    cd <REPO> && <PYTHON> -m neo4d.local_agent --agent-start RUN <ID>

  Perform ONE action on that task (always pass the JSON on stdin with a quoted heredoc, exactly like this):
    cd <REPO> && <PYTHON> -m neo4d.local_agent --agent-act RUN <ID> <<'EOF'
    {"tool": "read", "path": "qb/gcd.py"}
    EOF

The actions (one JSON object per command):
  {"tool": "ls", "path": "<directory>"}                                list a directory
  {"tool": "read", "path": "<file>"}                                   show a file
  {"tool": "grep", "pattern": "<regex>", "path": "<directory or file>"}   search (Python regex); path "." searches the whole project
  {"tool": "replace", "path": "<file>", "old": "<exact text>", "new": "<new text>"}   replace EVERY occurrence of the exact text in that file
  {"tool": "write", "path": "<file>", "content": "<text>"}             create or overwrite a file
  {"tool": "test"}                                                     run all the tests
  {"tool": "done"}                                                     finish the task

The project: qb/<name>.py defines the function <name>. tests/test_<name>.py imports it (`from qb.<name> import <name>`) and calls it. tests/run_all.py runs every test. Note that some modules end with a docstring that contains alternative versions of the code.

RULES
- Use ONLY the two commands above. Do not read, list, grep or open any file in the repository or the working copies yourself (no Read/Grep/Glob tools, no cat/ls/find in Bash) - every look at the project must be an --agent-act action. Do not read neo4d/local_agent.py or anything under .build/.
- At most 10 actions per task (the command refuses more). End every task with {"tool": "done"}.
- One try per task: you are not told whether the task was accepted, and you must not restart a task.
- Work through these task IDs in order, one after another, without skipping: <IDS>
- Be efficient but careful; answers for counting/listing tasks go in answer.txt exactly as the task asks.

When all tasks are done, reply with only: "finished" and the list of task IDs you completed.
```

## 2. Real bugs, test results only (`neo4d/local_hints.py`, run name `haiku-tests` or `haiku-hard-tests`)

```
You are fixing bugs in small Python programs. This is a benchmark: work honestly and only through the interface below.

THE ONLY WAY TO INTERACT is this command, run with the Bash tool:

  Start a bug (prints the buggy program and a failing test):
    cd <REPO> && <PYTHON> -m neo4d.local_hints --hints-start RUN <NAME>

  Submit a complete corrected program (always on stdin with a quoted heredoc, exactly like this; no line numbers):
    cd <REPO> && <PYTHON> -m neo4d.local_hints --hints-submit RUN <NAME> <<'EOF'
    def gcd(a, b):
        ...
    EOF

The reply tells you whether all tests pass ("FIXED") or what still fails.

RULES
- Use ONLY these two commands. Do not read, list, grep or open any file yourself (no Read/Grep/Glob tools, no cat/ls/find in Bash). Do not look at other versions of these programs anywhere on the machine.
- At most 3 submissions per bug. Move to the next bug as soon as a bug is FIXED or closed.
- Work through these bugs in order: <NAMES>

When all are done, reply with only "finished" and the list of bugs.
```

For the hard bugs the same prompt names them by opaque id (`<ID>` instead of `<NAME>`), shows `def f_xxxxxx(...):` in
the example, adds "keep the function's name" to the submit line, adds "A program may contain more than one fault."
after the reply sentence, and replaces "Do not look at other versions of these programs anywhere on the machine" by
"Do not look for these programs anywhere on the machine."

## 3. Real bugs, the exchange with neo4d (run name `haiku-exchange` or `haiku-hard-exchange`)

```
You are fixing bugs in small Python programs, working together with neo4d, a tool that mutates code and runs the tests. This is a benchmark: work honestly and only through the interface below.

THE ONLY WAY TO INTERACT is this command, run with the Bash tool:

  Start a bug (prints the buggy program, a failing test, and neo4d's evidence from mutating the code):
    cd <REPO> && <PYTHON> -m neo4d.local_hints --hints-start RUN <NAME>

  Submit a complete corrected program (always on stdin with a quoted heredoc, exactly like this; no line numbers):
    cd <REPO> && <PYTHON> -m neo4d.local_hints --hints-submit RUN <NAME> <<'EOF'
    def gcd(a, b):
        ...
    EOF

After each submission neo4d runs the tests; if they fail, it mutates your program, and either finds a variant that passes ("FIXED by neo4d") or reports back what your program and its best variants pass. Use its evidence and reports to direct your next attempt - even a partly right attempt helps, because neo4d explores around it.

RULES
- Use ONLY these two commands. Do not read, list, grep or open any file yourself (no Read/Grep/Glob tools, no cat/ls/find in Bash). Do not look at other versions of these programs anywhere on the machine.
- At most 3 submissions per bug. Move to the next bug as soon as a bug is FIXED (by you or by neo4d) or closed.
- Work through these bugs in order: <NAMES>

When all are done, reply with only "finished" and the list of bugs.
```

The hard-bug version makes the same changes as in section 2 and says "A program may contain more than one fault: use
neo4d's evidence and reports to direct your attempts".

## 4. neo4d searches, the model only filters (run name `haiku-hard-search`)

```
You are steering a code-search tool called neo4d, which fixes bugs in small Python programs by trying many small changes and running the tests. You do NOT write code: neo4d generates and tests the candidate programs; your only job is to FILTER - to pick which candidates are worth exploring one change deeper. A program may contain two faults, so a candidate that fixes one fault may pass only some tests. This is a benchmark: work honestly and only through the interface below.

THE ONLY WAY TO INTERACT is this command, run with the Bash tool:

  Start a bug (shows the buggy program, a failing test, and neo4d's most promising candidates):
    cd <REPO> && <PYTHON> -m neo4d.local_hints --search-start haiku-hard-search <ID>

  Pick up to 3 of the listed candidates (by number) for neo4d to explore one change deeper:
    cd <REPO> && <PYTHON> -m neo4d.local_hints --search-pick haiku-hard-search <ID> "1 4 7"

Each pick shows the next level of candidates, or "FIXED", or that the bug is closed. Think about what the program is meant to do and which changes move it the right way - not only the test counts.

RULES
- Use ONLY these two commands. Do not read, list, grep or open any file yourself (no Read/Grep/Glob tools, no cat/ls/find in Bash). Do not look for these programs anywhere on the machine.
- At most 3 picks per bug. Move to the next bug as soon as it is FIXED or closed.
- Work through these bug IDs in order: <IDS>

When all are done, reply with only "finished" and the list of IDs.
```
