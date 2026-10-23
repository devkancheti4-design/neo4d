"""The decisive test: is neo4d's verified data worth more for training a model than plain sampled data?

THE QUESTION. A small model fails some tasks. Sampling it many times and keeping what passes the task's tests
(rejection sampling, as in STaR / ReST / RFT) gives verified training data. neo4d adds solutions sampling misses: it
mutates near-miss samples (single-token changes on the lines the tests run, PICK choosing the order) until they pass,
and its SHIP law keeps only certified ones. Train the same model on each set and compare on benchmarks none of them saw.

DATA TASKS. MBPP's train, validation and prompt splits (task_id 1-10 and 511-974): the task text and its three test
asserts. The asserts are the checker - they belong to the training tasks, as in RFT.

HELD OUT. HumanEval+ (164) and the MBPP+ problems from MBPP's test split (task_id 11-510), scored by EvalPlus on its
hidden tests (base + plus). No data task appears there.

THE ARMS - one pool of 64 samples per task (temperature 0.8), so every arm draws on the same samples
    base         no training
    sample16     up to 4 distinct passing programs among the first 16 samples
    sample64     the same among all 64 samples - the same checker budget as neo4d (64 runs of the asserts per task)
    neo4d        sample16, and for a task none of its 16 samples solved: up to 48 mutation trials on the failing
                 samples (nearest miss first, PICK ordering), up to 4 distinct passing programs kept
    neo4d_ship   sample16, and a mutated program only when SHIP certifies it: the one green variant of the task,
                 stable on a re-run; greens that behave differently on probe calls made from the task's own tests
                 are ambiguity - SHIP asks, and the task is left out (equivalent rewrites count as one repair)
Training: LoRA on the same base model, the same hyperparameters, 3 seeds per arm. Reported: pass@1 (greedy) on the
hidden tests, per seed; paired permutation tests per problem against sample16 and sample64; dataset sizes; the share
of neo4d's mutated programs that a second check refutes (MBPP's challenge tests where a task has them).

    python -m neo4d.decisive sample   --base Qwen/Qwen2.5-Coder-0.5B-Instruct      (GPU, vLLM)
    python -m neo4d.decisive check                                                 (CPU)
    python -m neo4d.decisive search                                                (CPU)
    python -m neo4d.decisive datasets
    python -m neo4d.decisive train    --arm neo4d --seed 0                          (GPU, TRL + PEFT)
    python -m neo4d.decisive generate --arm neo4d --seed 0                          (GPU, vLLM)
    python -m neo4d.decisive evaluate --arm neo4d --seed 0                          (CPU, EvalPlus)
    python -m neo4d.decisive report                                                 -> results/DECISIVE.md
"""
from __future__ import annotations

import argparse
import ast
import json
import os
import random
import re
import subprocess
import sys
import tempfile
from collections import Counter, defaultdict
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

from neo4d import REPO

WORK = Path(os.environ.get("DECISIVE_DIR", REPO / ".build" / "decisive"))
BASE = "Qwen/Qwen2.5-Coder-0.5B-Instruct"
POOL, FIRST, BUDGET, KEEP = 64, 16, 64, 4
ARMS = ("sample16", "sample64", "neo4d", "neo4d_ship")
SEEDS = (0, 1, 2)
TIMEOUT = 5.0
TAIL = "Reply with the complete Python function in one ```python code block."
SCRATCH = Path(tempfile.gettempdir()) / "decisive_run"           # model-written code runs here, never in the repository


def _limits():
    import resource
    try:
        resource.setrlimit(resource.RLIMIT_AS, (4 << 30, 4 << 30))  # 4 GB per candidate (Linux; macOS refuses)
    except (ValueError, OSError):
        pass


def jl(path):
    return [json.loads(l) for l in Path(path).read_text().splitlines() if l.strip()]


def wjl(path, rows):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text("".join(json.dumps(r) + "\n" for r in rows))


def code_of(reply):
    m = re.findall(r"```(?:python|py)?\n(.*?)```", reply or "", re.S)
    return (max(m, key=len) if m else (reply or "")).strip() + "\n"


# --------------------------------------------------------------------------------------------------- the tasks

def data_tasks():
    """MBPP's non-test splits. -> [dict(task_id, text, tests, setup, challenge)]"""
    from datasets import load_dataset
    out = []
    for split in ("prompt", "train", "validation"):
        for x in load_dataset("google-research-datasets/mbpp", "full", split=split):
            out.append(dict(task_id=int(x["task_id"]), text=x["text"], tests=list(x["test_list"]),
                            setup=x["test_setup_code"] or "", challenge=list(x["challenge_test_list"] or [])))
    assert not [t for t in out if 11 <= t["task_id"] <= 510], "a test-split task among the data tasks"
    return sorted(out, key=lambda t: t["task_id"])


def prompt_mbpp(text, test):
    return f"{text}\nYour code should pass this test:\n{test}\n{TAIL}"


def prompt_humaneval(prompt):
    return f"Complete the following Python function.\n```python\n{prompt}```\n{TAIL}"


# ---------------------------------------------------------------------------------------- checking a candidate

RUNNER = r'''
import json, sys
src, setup, tests, trace = json.loads(sys.stdin.read())
hits = set()
def local(frame, event, arg):
    if event == "line" and frame.f_code.co_filename == "<candidate>":
        hits.add(frame.f_lineno)
    return local
def outer(frame, event, arg):
    return local if frame.f_code.co_filename == "<candidate>" else None
res = []
try:
    g = {"__name__": "__candidate__"}
    exec(compile(setup, "<setup>", "exec"), g)
    if trace: sys.settrace(outer)
    exec(compile(src, "<candidate>", "exec"), g)
    for t in tests:
        try:
            exec(compile(t, "<test>", "exec"), g)
            res.append(True)
        except BaseException:
            res.append(False)
except BaseException:
    res = [False] * len(tests)
finally:
    sys.settrace(None)
print(json.dumps([res, sorted(hits)]))
'''


def run_tests(src, setup, tests, trace=False):
    """-> (per-test pass list, lines of the candidate executed (1-based) when traced). A crash or timeout fails all."""
    try:
        SCRATCH.mkdir(exist_ok=True)
        r = subprocess.run([sys.executable, "-I", "-c", RUNNER], input=json.dumps([src, setup, tests, trace]),
                           capture_output=True, text=True, timeout=TIMEOUT, cwd=SCRATCH, preexec_fn=_limits)
        res, hits = json.loads(r.stdout.strip().splitlines()[-1])
        return res, set(hits)
    except (subprocess.TimeoutExpired, ValueError, IndexError):
        return [False] * len(tests), set()


PROBE = r'''
import json, sys
src, setup, calls = json.loads(sys.stdin.read())
g = {"__name__": "__candidate__"}
out = []
try:
    exec(compile(setup, "<setup>", "exec"), g)
    exec(compile(src, "<candidate>", "exec"), g)
    for c in calls:
        try:
            out.append(repr(eval(compile(c, "<probe>", "eval"), g))[:500])
        except BaseException as e:
            out.append("raises " + type(e).__name__)
except BaseException as e:
    out = ["broken " + type(e).__name__] * len(calls)
print(json.dumps(out))
'''


def probes(tests):
    """Calls to tell programs apart, made from the task's own test calls: each call as written, and with every integer
    argument moved by one and every list argument reversed. No expected values - only whether two programs agree."""
    out = []
    for t in tests:
        try:
            node = ast.parse(t)
        except SyntaxError:
            continue
        for call in [n for n in ast.walk(node) if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)][:1]:
            try:
                args = [ast.literal_eval(x) for x in call.args]
            except (ValueError, SyntaxError, TypeError):
                continue
            name = call.func.id
            out.append((name, args))
            for k, v in enumerate(args):
                if isinstance(v, int) and not isinstance(v, bool):
                    out += [(name, args[:k] + [v + d] + args[k + 1:]) for d in (-1, 1)]
                if isinstance(v, list) and len(v) > 1:
                    out.append((name, args[:k] + [v[::-1]] + args[k + 1:]))
    calls = [f"{n}({', '.join(map(repr, a))})" for n, a in out]
    return list(dict.fromkeys(calls))


def behaviour(src, setup, calls):
    try:
        SCRATCH.mkdir(exist_ok=True)
        r = subprocess.run([sys.executable, "-I", "-c", PROBE], input=json.dumps([src, setup, calls]),
                           capture_output=True, text=True, timeout=TIMEOUT, cwd=SCRATCH, preexec_fn=_limits)
        return tuple(json.loads(r.stdout.strip().splitlines()[-1]))
    except (subprocess.TimeoutExpired, ValueError, IndexError):
        return ("timeout",)


def _check(args):
    src, setup, tests = args
    return run_tests(src, setup, tests)[0]


# --------------------------------------------------------------------------------------------- neo4d's search

def search_task(task, failing):
    """neo4d on one task none of the first samples solved: mutate the failing samples, nearest miss first, PICK
    ordering trials on each, up to BUDGET - FIRST runs of the asserts. -> dict(greens, verdict, tried)"""
    from neo4d import domain_mutation as D
    from neo4d import local_model as LM
    from neo4d import relations as R
    from neo4d import swe_full as F
    left = BUDGET - FIRST
    greens, seen, tried = [], set(), 0
    cold = Counter()
    for s in sorted(failing, key=lambda s: (-sum(s["passed"]), s["i"])):
        if left <= 0:
            break
        src = s["code"]
        try:
            code_lines = set(LM.code_lines(src))
        except SyntaxError:
            continue
        _, hits = run_tests(src, task["setup"], task["tests"], trace=True)
        executed = {i for i in code_lines if (i + 1) in hits}
        lines = src.split("\n")
        cands = []
        for i in sorted(code_lines):
            for m, op in D.mutants(R.toks(lines[i])).items():
                new = LM.to_text(lines[i], list(m))
                var = "\n".join(lines[:i] + [new] + lines[i + 1:])
                if new != lines[i] and var not in seen:
                    seen.add(var)
                    cands.append(dict(text=var, line=i, kind=op, trusted=False))
        while cands and left > 0:
            scored = [(F.pick(F.pick_word(c, executed, set(), cold)), c) for c in cands]
            scored = [(r, c) for r, c in scored if r > 0]
            if not scored:
                break
            _, c = min(scored, key=lambda rc: (-rc[0], rc[1]["line"]))
            cands.remove(c)
            try:
                ast.parse(c["text"])
            except SyntaxError:
                continue
            res, _ = run_tests(c["text"], task["setup"], task["tests"])
            left -= 1
            tried += 1
            if all(res):
                stable = all(run_tests(c["text"], task["setup"], task["tests"])[0])
                greens.append(dict(code=c["text"], stable=stable, sample=s["i"], line=c["line"], kind=c["kind"]))
            elif sum(res) <= sum(s["passed"]):
                cold[c["kind"]] += 1
    # UNIQUE counts different behaviours, not different texts: `a > b` and `a >= b` returning the larger of two numbers
    # are one repair. Behaviour = what a program returns on probe calls made from the task's own tests.
    calls = probes(task["tests"])
    for g in greens:
        g["behaviour"] = behaviour(g["code"], task["setup"], calls) if calls else (g["code"],)
    distinct = {g["behaviour"] for g in greens if g["stable"]}
    verdict = None
    if greens:
        g = greens[0]
        x = (F.WAS_RED | F.GREEN | F.STABLE * g["stable"] | F.UNIQUE * (g["stable"] and len(distinct) == 1)
             | F.THIN * (len(task["tests"]) <= 1) | F.ROUTED)
        verdict = F.ship(x)
    for g in greens:
        g["behaviour"] = list(g["behaviour"])
    return dict(task_id=task["task_id"], greens=greens, distinct=len(distinct), distinct_texts=len({g["code"] for g in greens}),
                probes=len(calls), verdict=verdict, tried=tried)


def _search(args):
    return search_task(*args)


# ------------------------------------------------------------------------------------------------ the commands

def cmd_sample(a):
    from vllm import LLM, SamplingParams
    tasks = data_tasks()
    llm = LLM(model=a.base, seed=0, gpu_memory_utilization=0.85, max_model_len=2048)
    conv = [[{"role": "user", "content": prompt_mbpp(t["text"], t["tests"][0])}] for t in tasks]
    outs = llm.chat(conv, SamplingParams(n=POOL, temperature=0.8, top_p=0.95, max_tokens=512, seed=0))
    rows = [dict(task_id=t["task_id"], i=k, code=code_of(o.text)) for t, out in zip(tasks, outs)
            for k, o in enumerate(out.outputs)]
    wjl(WORK / "pool.jsonl", rows)
    wjl(WORK / "tasks.jsonl", tasks)
    print(f"{len(rows)} samples for {len(tasks)} tasks -> {WORK / 'pool.jsonl'}")


def cmd_check(a):
    tasks = {t["task_id"]: t for t in jl(WORK / "tasks.jsonl")}
    pool = jl(WORK / "pool.jsonl")
    with ProcessPoolExecutor(a.jobs) as ex:
        res = list(ex.map(_check, [(r["code"], tasks[r["task_id"]]["setup"], tasks[r["task_id"]]["tests"]) for r in pool],
                          chunksize=32))
    for r, p in zip(pool, res):
        r["passed"] = p
    wjl(WORK / "pool_checked.jsonl", pool)
    by = defaultdict(list)
    for r in pool:
        by[r["task_id"]].append(r)
    s16 = sum(any(all(r["passed"]) for r in v if r["i"] < FIRST) for v in by.values())
    s64 = sum(any(all(r["passed"]) for r in v) for v in by.values())
    print(f"tasks solved by sampling: {s16} with 16 samples, {s64} with 64, of {len(by)}")


def cmd_search(a):
    tasks = {t["task_id"]: t for t in jl(WORK / "tasks.jsonl")}
    by = defaultdict(list)
    for r in jl(WORK / "pool_checked.jsonl"):
        by[r["task_id"]].append(r)
    todo = [(tasks[k], [r for r in v if r["i"] < FIRST]) for k, v in sorted(by.items())
            if not any(all(r["passed"]) for r in v if r["i"] < FIRST)]
    with ProcessPoolExecutor(a.jobs) as ex:
        found = list(ex.map(_search, todo, chunksize=1))
    wjl(WORK / "search.jsonl", found)
    print(f"neo4d searched {len(found)} tasks no 16 samples solved: {sum(bool(f['greens']) for f in found)} with a green "
          f"program, {sum(f['verdict'] in (2, 3) for f in found)} certified by SHIP; "
          f"{sum(f['tried'] for f in found)} trials")


def norm(code):
    try:
        return ast.dump(ast.parse(code))
    except SyntaxError:
        return code


def cmd_datasets(a):
    tasks = {t["task_id"]: t for t in jl(WORK / "tasks.jsonl")}
    by = defaultdict(list)
    for r in jl(WORK / "pool_checked.jsonl"):
        by[r["task_id"]].append(r)
    search = {f["task_id"]: f for f in jl(WORK / "search.jsonl")}

    def passing(rows, k):
        out, seen = [], set()
        for r in sorted(rows, key=lambda r: r["i"]):
            if r["i"] < k and all(r["passed"]) and norm(r["code"]) not in seen:
                seen.add(norm(r["code"]))
                out.append(r["code"])
        return out[:KEEP]
    arms = {arm: [] for arm in ARMS}
    for tid in sorted(by):
        t = tasks[tid]
        ex = lambda codes, how: [dict(task_id=tid, prompt=prompt_mbpp(t["text"], t["tests"][0]), code=c, how=how)
                                 for c in codes]
        s16, s64 = passing(by[tid], FIRST), passing(by[tid], POOL)
        arms["sample16"] += ex(s16, "sample")
        arms["sample64"] += ex(s64, "sample")
        arms["neo4d"] += ex(s16, "sample")
        arms["neo4d_ship"] += ex(s16, "sample")
        f = search.get(tid)
        if f and f["greens"]:
            seen, mut = set(), []
            for g in f["greens"]:
                if g["stable"] and norm(g["code"]) not in seen:
                    seen.add(norm(g["code"]))
                    mut.append(g["code"])
            arms["neo4d"] += ex(mut[:KEEP], "neo4d")
            if f["verdict"] in (2, 3):
                arms["neo4d_ship"] += ex(mut[:1], "neo4d")
    for arm, rows in arms.items():
        wjl(WORK / "data" / f"{arm}.jsonl", rows)
    # a second check on what neo4d's mutation kept: MBPP's challenge tests, where the task has them
    refuted = Counter()
    for tid, f in search.items():
        t = tasks[tid]
        for g in f["greens"][:KEEP]:
            if t["challenge"]:
                ok = all(run_tests(g["code"], t["setup"], t["challenge"])[0])
                refuted["checked"] += 1
                refuted["refuted"] += not ok
                refuted["shipped_checked"] += f["verdict"] in (2, 3) and g is f["greens"][0]
                refuted["shipped_refuted"] += f["verdict"] in (2, 3) and g is f["greens"][0] and not ok
    sizes = {arm: dict(examples=len(rows), tasks=len({r["task_id"] for r in rows})) for arm, rows in arms.items()}
    (WORK / "data" / "sizes.json").write_text(json.dumps(dict(sizes=sizes, challenge=dict(refuted)), indent=1))
    print(json.dumps(sizes), dict(refuted))


def cmd_train(a):
    import torch
    from datasets import Dataset
    from peft import LoraConfig
    from trl import SFTConfig, SFTTrainer
    rows = jl(WORK / "data" / f"{a.arm}.jsonl")
    ds = Dataset.from_list([dict(prompt=[{"role": "user", "content": r["prompt"]}],
                                 completion=[{"role": "assistant", "content": f"```python\n{r['code']}```"}]) for r in rows])
    out = WORK / "adapters" / f"{a.arm}_s{a.seed}"
    cfg = SFTConfig(output_dir=str(out), num_train_epochs=3, per_device_train_batch_size=8, gradient_accumulation_steps=2,
                    learning_rate=2e-4, lr_scheduler_type="cosine", warmup_steps=0.05, logging_steps=10,
                    save_strategy="no", report_to="none", seed=a.seed, data_seed=a.seed,
                    bf16=torch.cuda.is_bf16_supported(), fp16=not torch.cuda.is_bf16_supported(), max_length=1024)
    peft = LoraConfig(r=16, lora_alpha=32, lora_dropout=0.05, target_modules="all-linear", task_type="CAUSAL_LM")
    tr = SFTTrainer(model=a.base, train_dataset=ds, args=cfg, peft_config=peft)
    tr.train()
    tr.save_model(str(out))
    (out / "train_log.json").write_text(json.dumps(tr.state.log_history, indent=1))
    print(f"{a.arm} seed {a.seed}: {len(rows)} examples -> {out}")


def eval_problems():
    from evalplus.data import get_human_eval_plus, get_mbpp_plus
    he = [("humaneval", k, prompt_humaneval(p["prompt"]), p) for k, p in get_human_eval_plus().items()]
    # every MBPP+ problem is generated (EvalPlus expects them all); only those of MBPP's test split are reported
    mb = [("mbpp", k, f"{p['prompt'].strip()}\n{TAIL}", p) for k, p in get_mbpp_plus().items()]
    return he + mb


def with_imports(prompt, code):
    """The prompt's top-level imports in front of the model's function (it often leaves `from typing import List` out)."""
    imports = [l for l in prompt.split("\n") if l.startswith(("import ", "from "))]
    return "\n".join(imports) + ("\n\n" if imports else "") + code


def cmd_generate(a):
    from vllm import LLM, SamplingParams
    from vllm.lora.request import LoRARequest
    probs = eval_problems()
    name = "base" if a.arm == "base" else f"{a.arm}_s{a.seed}"
    lora = None if a.arm == "base" else LoRARequest(name, 1, str(WORK / "adapters" / name))
    llm = LLM(model=a.base, seed=0, gpu_memory_utilization=0.85, max_model_len=2048, enable_lora=lora is not None,
              max_lora_rank=16)
    outs = llm.chat([[{"role": "user", "content": p}] for _, _, p, _ in probs],
                    SamplingParams(n=1, temperature=0.0, max_tokens=768), lora_request=lora)
    for bench in ("humaneval", "mbpp"):
        rows = [dict(task_id=k, solution=with_imports(p["prompt"], code_of(o.outputs[0].text)))
                for (b, k, _, p), o in zip(probs, outs) if b == bench]
        wjl(WORK / "samples" / f"{name}_{bench}.jsonl", rows)
    print(f"generated {len(probs)} -> {WORK / 'samples'}")


def cmd_evaluate(a):
    name = "base" if a.arm == "base" else f"{a.arm}_s{a.seed}"
    for bench in ("humaneval", "mbpp"):
        f = WORK / "samples" / f"{name}_{bench}.jsonl"
        subprocess.run([sys.executable, "-m", "evalplus.evaluate", "--dataset", bench, "--samples", str(f),
                        "--parallel", str(a.jobs), "--i-just-wanna-run"], check=True)


def per_task(name, bench):
    """-> {task_id: (passes base tests, passes base + plus tests)} for the greedy sample."""
    f = WORK / "samples" / f"{name}_{bench}_eval_results.json"
    d = json.loads(f.read_text())["eval"]
    out = {}
    for k, v in d.items():
        if bench == "mbpp" and not (11 <= int(k.split("/")[1]) <= 510):
            continue
        r = v[0]
        base_ok = r.get("base_status") == "pass"
        out[k] = (base_ok, base_ok and r.get("plus_status") == "pass")
    return out


def permutation_p(a, b, n=20000, seed=0):
    rng = random.Random(seed)
    d = [x - y for x, y in zip(a, b)]
    obs = abs(sum(d))
    hit = sum(abs(sum(x if rng.random() < 0.5 else -x for x in d)) >= obs for _ in range(n))
    return (hit + 1) / (n + 1)


def cmd_report(a):
    sizes = json.loads((WORK / "data" / "sizes.json").read_text())
    lines = ["# The decisive test: training on neo4d's verified data against plain sampled data", "",
             f"Generated by `neo4d/decisive.py`. Base model `{a.base}`; LoRA, 3 epochs, the same settings for every arm; "
             "seeds " + ", ".join(map(str, SEEDS)) + ". Held out: HumanEval+ (164) and MBPP+ problems of MBPP's test split; "
             "pass@1, greedy, on EvalPlus's hidden tests (base + plus).", "",
             "| arm | examples | tasks | HumanEval+ (per seed) | mean | MBPP+ (per seed) | mean |", "|---|---|---|---|---|---|---|"]
    table = {}
    for arm in ("base",) + ARMS:
        names = ["base"] if arm == "base" else [f"{arm}_s{s}" for s in SEEDS]
        row = {}
        for bench in ("humaneval", "mbpp"):
            got = [per_task(n, bench) for n in names if (WORK / "samples" / f"{n}_{bench}_eval_results.json").exists()]
            row[bench] = got
        table[arm] = row
        sz = sizes["sizes"].get(arm, dict(examples=0, tasks=0))
        cells = []
        for bench in ("humaneval", "mbpp"):
            vals = [sum(v[1] for v in g.values()) for g in row[bench]]
            n = len(row[bench][0]) if row[bench] else 0
            cells += [" / ".join(map(str, vals)) or "-",
                      f"{sum(vals) / len(vals):.1f} ({100 * sum(vals) / len(vals) / n:.1f}%)" if vals else "-"]
        lines.append(f"| {arm} | {sz['examples']} | {sz['tasks']} | " + " | ".join(cells) + " |")
    lines += ["", "Paired permutation tests per problem (each arm's pass rate averaged over its seeds):", ""]
    for arm in ("neo4d", "neo4d_ship"):
        for ref in ("sample16", "sample64"):
            for bench in ("humaneval", "mbpp"):
                A, B = table[arm][bench], table[ref][bench]
                if not A or not B:
                    continue
                keys = sorted(A[0])
                xa = [sum(g[k][1] for g in A) / len(A) for k in keys]
                xb = [sum(g[k][1] for g in B) / len(B) for k in keys]
                lines.append(f"- {arm} against {ref}, {bench}: {sum(xa) - sum(xb):+.2f} problems, p = {permutation_p(xa, xb):.3f}")
    ch = sizes.get("challenge", {})
    lines += ["", f"A second check on neo4d's mutated programs (MBPP's challenge tests, where a task has them): "
              f"{ch.get('refuted', 0)} of {ch.get('checked', 0)} refuted; of those SHIP certified, "
              f"{ch.get('shipped_refuted', 0)} of {ch.get('shipped_checked', 0)}."]
    (REPO / "results" / "DECISIVE.md").write_text("\n".join(lines) + "\n")
    print("\n".join(lines))


def main() -> int:
    ap = argparse.ArgumentParser(prog="neo4d.decisive")
    ap.add_argument("cmd", choices=("sample", "check", "search", "datasets", "train", "generate", "evaluate", "report"))
    ap.add_argument("--base", default=BASE)
    ap.add_argument("--arm", default="base", choices=("base",) + ARMS)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--jobs", type=int, default=os.cpu_count() or 4)
    a = ap.parse_args()
    WORK.mkdir(parents=True, exist_ok=True)
    globals()[f"cmd_{a.cmd}"](a)
    return 0


if __name__ == "__main__":
    sys.exit(main())
