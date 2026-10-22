# Running neo4d on SWE-bench

Everything needed to measure neo4d on SWE-bench Lite (or Verified) and to submit the result to the public leaderboard.
The agent is `neo4d/swe_agent.py`; its control flow is tested in `tests/test_swe_agent.py`. The Docker path below has
**not** been run end to end by the author yet - start with the one-instance smoke test (step 4) and read its trajectory
before spending hours on a full run.

## 1. What is measured

Two conditions, the same model, the same number of rounds, one attempt per issue (pass@1):

| condition | what happens in each round |
|---|---|
| `model` | the model writes SEARCH/REPLACE edits; it is told what its reproduction script printed (self-debugging) |
| `neo4d` | the same, and when the edit fails, neo4d mutates the lines the edit changed (every single-token change it knows), runs the reproduction and the module's existing tests on each variant, ships the first that passes, and otherwise reports back what its variants did |

For each issue the agent: finds the file (identifiers from the issue are searched in the code; the model picks), has the
model write a **reproduction script** that must fail before the fix and pass after it, runs the test files that use the
module before any change (to know what passed), then runs up to 4 rounds. Nothing from the evaluation is used - not the
tests that must start passing, not the gold patch, not `hints_text` - so the result is eligible for the leaderboard.

Outputs per run: `all_preds.jsonl` (SWE-bench's predictions format), `trajs/<instance_id>.json` (every prompt, reply,
command and result, with model calls and seconds), `run.json` (the settings and the instance list).

## 2. Machine

SWE-bench's harness runs every issue in its own Docker container. Its maintainers recommend an **x86_64 Linux** machine
with Docker, **at least 120 GB free disk, 16 GB RAM and 8 CPU cores** for full runs (a 25-issue pilot needs far less
disk). On Apple-silicon Macs the instance images must be built locally, which is slow. The model is served by
[ollama](https://ollama.com) on the same machine or anywhere reachable (set `OLLAMA_URL`); pick a model the machine can
serve at a useful speed.

## 3. Setup

```bash
git clone https://github.com/devkancheti4-design/neo4d.git
cd neo4d
python3.11 -m venv .venv && source .venv/bin/activate
pip install -e .
pip install swebench datasets
docker run --rm hello-world                       # Docker works for this user
```

The model server (see ollama's site for the install command for your system), then a model:

```bash
ollama pull qwen2.5-coder:7b                      # or any model; phi4-mini and gemma3:4b were used in the paper
export OLLAMA_URL=http://localhost:11434           # where ollama listens
```

Instance images: `swe_agent` starts each issue's container from SWE-bench's published image,
`swebench/sweb.eval.x86_64.<id>:latest`, where `<id>` is the instance id with `__` replaced by `_1776_`
(e.g. `django__django-11099` -> `swebench/sweb.eval.x86_64.django_1776_django-11099:latest`). Docker pulls it the
first time. If your harness version names images differently, pass `--image` with a template (`{id}` is the converted
id, `{raw}` the instance id); the harness's README explains how to build the images yourself.

## 4. Smoke test - one issue, both conditions (do this first)

```bash
echo django__django-11099 > ids_smoke.txt
python -m neo4d.swe_agent run --condition model --model qwen2.5-coder:7b --ids ids_smoke.txt --workers 1 --out runs/smoke_model
python -m neo4d.swe_agent run --condition neo4d --model qwen2.5-coder:7b --ids ids_smoke.txt --workers 1 --out runs/smoke_neo4d
```

Check `runs/smoke_*/trajs/django__django-11099.json` (and, for any run, `python -m neo4d.swe_agent diagnose --run <run>
--report <harness report> [--gold-repro]` - where issues are lost; it reads the gold patch, so use it for analysis only):

- a `localise` entry with candidate files (empty means the keyword search found nothing),
- a `reproduce` entry with a non-zero `code` (the reproduction fails before the fix),
- a `regression` entry with the test command it will use,
- `round` entries, and in the neo4d run a `neo4d` entry with how many variants it `tried`,
- `end` with the diff; `all_preds.jsonl` holds the same diff.

If a container command fails, run it by hand: `docker run -it --rm <image> bash`, then
`source /opt/miniconda3/bin/activate && conda activate testbed && cd /testbed` - the agent runs every command this way.

## 5. Pilot - 25 issues, both conditions

```bash
python -m neo4d.swe_agent run --condition model --model qwen2.5-coder:7b --sample 25 --seed 0 --workers 2 --out runs/pilot_model
python -m neo4d.swe_agent run --condition neo4d --model qwen2.5-coder:7b --sample 25 --seed 0 --workers 2 --out runs/pilot_neo4d
```

The same seed gives both conditions the same 25 issues. A run that stops can be started again with the same command:
issues already in `all_preds.jsonl` are skipped. `--workers` runs issues in parallel (one container each); the model
server must keep up.

## 6. Score with the official harness

```bash
python -m swebench.harness.run_evaluation --dataset_name princeton-nlp/SWE-bench_Lite \
    --predictions_path runs/pilot_model/all_preds.jsonl --max_workers 8 --run_id pilot_model
python -m swebench.harness.run_evaluation --dataset_name princeton-nlp/SWE-bench_Lite \
    --predictions_path runs/pilot_neo4d/all_preds.jsonl --max_workers 8 --run_id pilot_neo4d
```

Each writes a report `<model_name_or_path>.<run_id>.json` in the current directory (model names are
`qwen2.5-coder:7b` and `neo4d+qwen2.5-coder:7b`) and logs under `logs/run_evaluation/<run_id>/`.

Instead of local scoring, SWE-bench's own service `sb-cli` scores predictions on its servers (`pip install sb-cli`;
you request an API key with your e-mail - see `sb-cli --help` and swebench.com/sb-cli).

## 7. The paper's numbers

```bash
python -m neo4d.swe_agent compare \
    --model-report "qwen2.5-coder:7b.pilot_model.json" --neo4d-report "neo4d+qwen2.5-coder:7b.pilot_neo4d.json" \
    --model-run runs/pilot_model --neo4d-run runs/pilot_neo4d
```

It prints resolved counts for both conditions, the issues resolved only with or only without neo4d, an exact McNemar
p-value, and the model calls and hours of each run. Run more seeds (`--seed 1`, `--seed 2`) for a spread.

## 8. The full run

Drop `--sample` to run every issue of the split (300 for Lite; `--dataset princeton-nlp/SWE-bench_Verified` for the 500
of Verified). Expect roughly 5-15 minutes per issue per condition with one worker, depending on the model's speed and
the project's tests.

## 9. Submitting to the leaderboard

1. Fork and clone https://github.com/SWE-bench/experiments.
2. Package the run in the layout it expects:

   ```bash
   python -m neo4d.swe_agent package --run runs/full_neo4d --dest experiments/evaluation/lite \
       --eval-logs "logs/run_evaluation/full_neo4d/neo4d+qwen2.5-coder:7b" \
       --report "neo4d+qwen2.5-coder:7b.full_neo4d.json"
   ```

   This writes `evaluation/lite/<date>_neo4d_<model>/` with `all_preds.jsonl`, `trajs/`, `logs/`, the report,
   `metadata.yaml` (name, oss, site, `verified: false`) and a `README.md` describing the system.
3. Follow the repository's `checklist.md` and README for anything newer than this guide (for example the script that
   generates the `results/` folder).
4. Open a pull request with the new folder.

The rules this agent already keeps: pass@1 (one attempt per issue), no `hints_text`, no oracle telling it which files
to edit, trajectories included. The leaderboard links to your code: it is public at `github.com/devkancheti4-design/neo4d`. A "verified" checkmark needs the SWE-bench team to reproduce the run - open an issue there
explaining how to run it.

## 10. Honest expectations

A 7B-or-smaller open model resolves few SWE-bench issues. The result worth reporting is the **difference between the
two conditions with the same model** (and the calls and time each used), with the McNemar test, not a rank near the top
of the leaderboard. Report both conditions, every seed, and the issues where neo4d's mutation shipped the fix (the
`neo4d` entries with `shipped` set in the trajectories).

## 11. Troubleshooting

| symptom | what to check |
|---|---|
| `docker run <image>: ... not found` | the image name (step 3); pass `--image` |
| every trajectory has an empty `localise` | the issue names no identifiers found in the code; read the issue and the keywords in the trajectory |
| `reproduce` never fails | the model's reproduction does not exercise the bug; the run continues without a check (both conditions alike) |
| the model server times out | `OLLAMA_URL`, fewer `--workers`, a smaller model |
| tests time out | the regression command in the trajectory; long test suites are cut at 900 s |
| the disk fills up | `docker system prune` between runs removes stopped containers and unused images |
