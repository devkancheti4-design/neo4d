"""neo4d on SWE-bench: the model reads the issue, finds the code, writes a reproduction and a patch; neo4d mutates the
patch and checks every variant against the reproduction and the project's own tests.

THE TWO CONDITIONS, the same model, the same budget of rounds
    model    the model alone, told after every round what its reproduction printed (self-debugging)
    neo4d    the same, and after a failed round neo4d mutates the lines the patch changed (every single-token change
             it knows), ships the first variant that makes the reproduction pass without breaking the tests that
             passed before, and otherwise reports back what its variants did

THE STEPS FOR ONE ISSUE
    1 localise     identifiers from the issue are searched in the code; the model picks the file to change
    2 reproduce    the model writes a script that exits 0 only when the issue is fixed; it must fail before the fix
    3 regression   test files that use the module are run before any change, to know what passed
    4 rounds       the model writes SEARCH/REPLACE edits; each is applied and checked; (neo4d) mutations follow
    5 output       the diff of the repository, in SWE-bench's predictions format, with the whole trajectory

Nothing from the evaluation is used: not the tests that must start passing, not the gold patch, not hints_text.

    python -m neo4d.swe_agent run --condition neo4d --model qwen2.5-coder:7b --sample 25 --out runs/pilot_neo4d
    python -m neo4d.swe_agent package --run runs/pilot_neo4d --eval-logs logs/run_evaluation/<run_id> ...
See docs/SWEBENCH.md for every step.
"""
from __future__ import annotations

import argparse
import ast
import concurrent.futures as cf
import datetime
import json
import math
import os
import random
import re
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from collections import Counter
from pathlib import Path

from neo4d import domain_mutation as D
from neo4d import local_model as LM
from neo4d import relations as R

OLLAMA = os.environ.get("OLLAMA_URL", "http://localhost:11434") + "/api/generate"
ROUNDS = 4                 # model rounds per issue
VARIANTS = 40              # neo4d variants tried per failed round (each runs the reproduction)
STOP = set("""self None True False return import from class def with this that when then have should would could
which there their where what into only also just using used issue error example value values file files code test
tests python version line lines function method object instead expected actual output result results""".split())


# ------------------------------------------------------------------------------------------------- environments

class LocalEnv:
    """A checkout on this machine (for tests, and for trying the agent without Docker)."""

    def __init__(self, path, python=sys.executable):
        self.root, self.python = Path(path), python
        self.repro = str(Path(tempfile.mkdtemp(prefix="neo4d_repro_")) / "repro.py")

    def run(self, cmd, timeout=300):
        try:
            r = subprocess.run(cmd, shell=True, cwd=self.root, capture_output=True, text=True, timeout=timeout,
                               env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"})
            return r.returncode, (r.stdout + r.stderr)
        except subprocess.TimeoutExpired:
            return 124, "timed out"

    def read(self, path):
        p = Path(path) if Path(path).is_absolute() else self.root / path
        return p.read_text(errors="replace")

    def write(self, path, text):
        p = Path(path) if Path(path).is_absolute() else self.root / path
        p.write_text(text)

    def py(self, script):
        return self.run(f"{self.python} {script}", timeout=120)

    def close(self):
        pass


class DockerEnv:
    """The official SWE-bench image of an instance: the repository at /testbed, its environment `testbed`."""

    ACTIVATE = "source /opt/miniconda3/bin/activate && conda activate testbed"

    def __init__(self, image, name):
        self.name, self.repro = name, "/tmp/neo4d_repro.py"
        subprocess.run(["docker", "rm", "-f", name], capture_output=True)
        r = subprocess.run(["docker", "run", "-d", "--name", name, image, "sleep", "infinity"], capture_output=True,
                           text=True)
        if r.returncode:
            raise RuntimeError(f"docker run {image}: {r.stderr.strip()}")

    def run(self, cmd, timeout=300):
        try:
            r = subprocess.run(["docker", "exec", self.name, "bash", "-lc", f"{self.ACTIVATE} && cd /testbed && {cmd}"],
                               capture_output=True, text=True, timeout=timeout)
            return r.returncode, (r.stdout + r.stderr)
        except subprocess.TimeoutExpired:
            subprocess.run(["docker", "exec", self.name, "pkill", "-f", "neo4d_repro"], capture_output=True)
            return 124, "timed out"

    def read(self, path):
        p = path if path.startswith("/") else f"/testbed/{path}"
        return subprocess.run(["docker", "exec", self.name, "cat", p], capture_output=True, text=True).stdout

    def write(self, path, text):
        p = path if path.startswith("/") else f"/testbed/{path}"
        subprocess.run(["docker", "exec", "-i", self.name, "bash", "-c", f"cat > {p}"], input=text, text=True,
                       capture_output=True)

    def py(self, script):
        return self.run(f"python {script}", timeout=120)

    def close(self):
        subprocess.run(["docker", "rm", "-f", self.name], capture_output=True)


def image_of(instance_id, template):
    """SWE-bench's published instance images replace '__' by '_1776_' (Docker Hub forbids '__')."""
    return template.format(id=instance_id.replace("__", "_1776_"), raw=instance_id)


# ------------------------------------------------------------------------------------------------------ the model

def generate(model, prompt, temperature, seed, traj, predict=2048):
    body = json.dumps({"model": model, "prompt": prompt, "stream": False,
                       "options": {"temperature": temperature, "seed": seed, "num_predict": predict,
                                   "num_ctx": 16384}}).encode()
    reply = ""
    for wait in (2, 5, 10, 30, None):
        try:
            req = urllib.request.Request(OLLAMA, data=body, headers={"Content-Type": "application/json"})
            with urllib.request.urlopen(req, timeout=900) as r:
                reply = json.loads(r.read())["response"]
            break
        except (urllib.error.URLError, TimeoutError, ConnectionError):
            if wait is None:
                break
            time.sleep(wait)
    traj.append(dict(kind="model", prompt=prompt, response=reply))
    return reply


def code_block(reply):
    m = re.findall(r"```(?:python)?\n(.*?)```", reply or "", re.S)
    return max(m, key=len) if m else None


EDIT = re.compile(r"([\w./-]+\.py)\s*\n<<<<<<< SEARCH\n(.*?)\n=======\n(.*?)\n>>>>>>> REPLACE", re.S)


def edits_of(reply):
    def clean(p):
        p = p.strip()
        for pre in ("/testbed/", "a/", "b/", "./"):
            if p.startswith(pre):
                p = p[len(pre):]
        return p
    return [(clean(p), old, new) for p, old, new in EDIT.findall(reply or "")]


NUMBERED = re.compile(r"^ {0,5}\d+  ", re.M)


def apply_edit(text, old, new):
    """Exact match first; then the same lines ignoring trailing whitespace; then without the line numbers the model was
    shown (small models copy them). -> new text or None."""
    if old and old in text:
        return text.replace(old, new, 1)
    if NUMBERED.search(old) and all(NUMBERED.match(l) or not l.strip() for l in old.split("\n")):
        return apply_edit(text, NUMBERED.sub("", old), NUMBERED.sub("", new))
    lines, want = text.split("\n"), [l.rstrip() for l in old.split("\n")]
    for i in range(len(lines) - len(want) + 1):
        if [l.rstrip() for l in lines[i:i + len(want)]] == want:
            return "\n".join(lines[:i] + new.split("\n") + lines[i + len(want):])
    return None


# ------------------------------------------------------------------------------------------------------ the steps

def keywords(issue, k=12):
    found = re.findall(r"`([^`\n]{3,60})`", issue)
    found += re.findall(r"\b[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)+\b", issue)
    found += re.findall(r"\b[a-z]+_[a-z0-9_]+\b|\b[A-Z][a-z]+(?:[A-Z][a-z0-9]+)+\b", issue)
    words = []
    for f in found:
        for w in re.findall(r"[A-Za-z_][A-Za-z0-9_]{2,}", f):
            if w.lower() not in STOP:
                words.append(w)
    return [w for w, _ in Counter(words).most_common(k)]


def localise(env, issue, model, traj, seed):
    """A file scores the specificity of the issue's identifiers it mentions - a word found in few files says more than
    one found in hundreds (log(N / files with it)) - and that much again where it defines one (class / def)."""
    kws = keywords(issue)
    _, out = env.run("git ls-files '*.py' | wc -l", timeout=120)
    n = int(out.split()[-1]) if out.split() and out.split()[-1].isdigit() else 1000
    hits = Counter()

    def source(out):
        return [p.lstrip("./") for p in out.split()
                if "test" not in p.lower() and not p.lstrip("./").startswith(("doc", "docs/", "examples"))]
    for w in kws:
        _, out = env.run(f"grep -rl --include=*.py -w {json.dumps(w)} . 2>/dev/null", timeout=120)
        found = source(out)
        if not found:
            continue
        weight = math.log((max(n, len(found)) + 1) / len(found))
        for p in found:
            hits[p] += weight
        _, out = env.run(f"grep -rlE --include=*.py {json.dumps(rf'^[[:space:]]*(class|def)[[:space:]]+{w}[^A-Za-z0-9_]')} . "
                         "2>/dev/null", timeout=120)
        for p in source(out):
            hits[p] += weight
    top = [p for p, _ in sorted(hits.items(), key=lambda kv: (-kv[1], kv[0]))[:15]]
    traj.append(dict(kind="localise", keywords=kws, candidates=top))
    if not top:
        return None
    reply = generate(model, f"An issue in a Python repository:\n\n{issue[:6000]}\n\nFiles that mention its identifiers "
                     "(most first):\n" + "\n".join(top) + "\n\nWhich ONE file most likely needs the change? Reply with "
                     "only its path.", 0.0, seed, traj, predict=60)
    for p in top:
        if p in reply:
            return p
    return top[0]


def excerpt(text, kws, width=60, whole=600):
    lines = text.split("\n")
    if len(lines) <= whole:
        return "\n".join(f"{i + 1:5d}  {l}" for i, l in enumerate(lines))
    marks = Counter()
    for i, l in enumerate(lines):
        marks[i] += sum(w in l for w in kws)
    centres = [i for i, c in marks.most_common(3) if c]
    keep = sorted({j for c in centres for j in range(max(0, c - width), min(len(lines), c + width))})
    out, prev = [], -2
    for j in keep:
        if j != prev + 1:
            out.append("  ...")
        out.append(f"{j + 1:5d}  {lines[j]}")
        prev = j
    return "\n".join(out)


def package_of(path):
    """The importable package a repository file belongs to: its first directory that is not lib/ or src/."""
    dirs = [p for p in Path(path).parts[:-1] if p not in ("lib", "src")]
    return dirs[0] if dirs else Path(path).stem


def imports(script, pkg):
    names = "|".join(sorted({re.escape(pkg), re.escape(pkg.lstrip("_"))}))
    return re.search(rf"^\s*(from|import)\s+({names})\b", script, re.M) is not None


def reproduce(env, issue, path, shown, model, traj, seed, tries=3):
    """A script that fails now and should pass once the issue is fixed. It must import the repository's package: a
    script that re-implements the code it is about can never be fixed by an edit to the repository."""
    pkg = package_of(path)
    for k in range(tries):
        reply = generate(model, f"An issue in a Python repository (the repository is the current directory and is "
                         f"importable):\n\n{issue[:6000]}\n\nThe code most likely involved, `{path}`:\n```\n{shown}\n```\n\n"
                         "Write a short standalone Python script that REPRODUCES the issue: it must exit with status 0 "
                         "only if the issue is fixed, and fail (for example with an AssertionError) while it is not. "
                         f"It must import and call the repository's own code (the package `{pkg}`), not a copy of it. "
                         "Reply with the script in one ```python code block.", 0.0 if k == 0 else 0.7, seed + k, traj,
                         predict=900)
        script = code_block(reply)
        if not script:
            continue
        if not imports(script, pkg):
            traj.append(dict(kind="reproduce", rejected=f"does not import {pkg}"))
            continue
        env.write(env.repro, script)
        code, out = env.py(env.repro)
        traj.append(dict(kind="reproduce", code=code, output=out[-2000:], script=script))
        broken = any(s in out for s in ("SyntaxError", "ModuleNotFoundError", "ImportError: cannot import name"))
        if code != 0 and not broken:
            return script, out
    return None, None


def related_tests(env, path):
    stem = Path(path).stem
    _, out = env.run(f"grep -rl --include=*.py -w {json.dumps(stem)} . 2>/dev/null | grep -i test | head -2", timeout=120)
    return [p.lstrip("./") for p in out.split()][:2]


def test_command(instance, files):
    try:
        from swebench.harness.constants import MAP_REPO_VERSION_TO_SPECS
        cmd = MAP_REPO_VERSION_TO_SPECS[instance["repo"]][instance["version"]]["test_cmd"]
        cmd = cmd if isinstance(cmd, str) else " ".join(cmd)
    except Exception:                                          # noqa: BLE001 - no swebench (local runs): pytest
        cmd = "python -m pytest -q -x"
    if instance.get("repo") == "django/django":
        labels = sorted({f.split("/")[1] for f in files if f.startswith("tests/") and f.count("/") >= 2})
        return f"{cmd} {' '.join(labels)}" if labels else None
    return f"{cmd} {' '.join(files)}" if files else None


def check(env, regress):
    """-> (the reproduction passes, the tests that passed before still pass, the reproduction's output)"""
    code, out = env.py(env.repro)
    if code != 0:
        return False, None, out
    if regress is None:
        return True, True, out
    rcode, rout = env.run(regress, timeout=900)
    return True, rcode == 0, rout[-1500:]


def mutate_patch(env, path, original, patched, regress, base_ok, traj, cap=VARIANTS):
    """neo4d: every single-token change on the lines the patch changed (and their neighbours). -> a passing text or None,
    and what the variants did."""
    old, new = original.split("\n"), patched.split("\n")
    import difflib
    sm = difflib.SequenceMatcher(None, old, new)
    changed = sorted({j for tag, _, _, j1, j2 in sm.get_opcodes() if tag != "equal" for j in range(j1, j2)})
    try:
        code = set(LM.code_lines(patched))
    except SyntaxError:
        return None, ["the patched file is not valid Python"]
    near = sorted({j for c in changed for j in range(c - 2, c + 3)} & code, key=lambda j: (min(abs(j - c) for c in changed), j))
    tried, notes = 0, []
    for li in near:
        for m in D.mutants(R.toks(new[li])):
            t = LM.to_text(new[li], list(m))
            if t == new[li]:
                continue
            var = "\n".join(new[:li] + [t] + new[li + 1:])
            try:
                ast.parse(var)
            except SyntaxError:
                continue
            env.write(path, var)
            ok, still, out = check(env, regress if base_ok else None)
            tried += 1
            if ok and still is not False:
                traj.append(dict(kind="neo4d", tried=tried, shipped=f"line {li + 1}: {t.strip()}"))
                return var, notes
            if len(notes) < 3 and out and "Error" in out:
                notes.append(f"line {li + 1}: `{new[li].strip()}` -> `{t.strip()}`: {out.strip().splitlines()[-1][:160]}")
            if tried >= cap:
                env.write(path, patched)
                traj.append(dict(kind="neo4d", tried=tried, shipped=None))
                return None, notes
    env.write(path, patched)
    traj.append(dict(kind="neo4d", tried=tried, shipped=None))
    return None, notes


def solve(env, instance, model, condition, seed=0, rounds=ROUNDS):
    """-> (the diff to submit, the trajectory)"""
    traj = [dict(kind="start", instance_id=instance["instance_id"], condition=condition, model=model)]
    issue = instance["problem_statement"]
    path = localise(env, issue, model, traj, seed)
    traj.append(dict(kind="file", path=path))
    if not path:
        return "", traj
    original = env.read(path)
    kws = keywords(issue)
    script, failing = reproduce(env, issue, path, excerpt(original, kws), model, traj, seed)
    traj.append(dict(kind="reproduction", script=script))
    files = related_tests(env, path)
    regress = test_command(instance, files)
    base_ok = False
    if regress:
        base_ok = env.run(regress, timeout=900)[0] == 0
    traj.append(dict(kind="regression", command=regress, passes_before=base_ok))
    feedback = f"The reproduction fails now:\n{(failing or '')[-1500:]}" if script else ""
    for r in range(rounds):
        text = env.read(path)
        prompt = (f"An issue in a Python repository:\n\n{issue[:6000]}\n\nThe file `{path}` (with line numbers):\n```\n"
                  f"{excerpt(text, kws)}\n```\n\n" + (f"A script that reproduces the issue:\n```python\n{script}\n```\n\n" if script else "")
                  + (f"{feedback}\n\n" if feedback else "")
                  + "Fix the issue. Reply with one or more edits in exactly this form, nothing else:\n"
                  f"{path}\n<<<<<<< SEARCH\n<exact lines from the file>\n=======\n<the new lines>\n>>>>>>> REPLACE")
        reply = generate(model, prompt, 0.0 if r == 0 else 0.7, seed * 100 + r, traj)
        before = text
        applied = False
        for p, old, new in edits_of(reply):
            if p != path:
                continue
            out = apply_edit(text, old, new)
            if out is not None:
                text, applied = out, True
        if not applied:
            feedback = "Your last edit could not be applied: the SEARCH text must match lines of the file exactly."
            continue
        env.write(path, text)
        if not script:                                          # nothing to check against: keep the model's edit
            traj.append(dict(kind="round", round=r, applied=True, checked=False))
            break
        ok, still, out = check(env, regress if base_ok else None)
        traj.append(dict(kind="round", round=r, reproduction=ok, regression_ok=still, output=(out or "")[-1500:]))
        if ok and still is not False:
            break
        if condition == "neo4d":
            var, notes = mutate_patch(env, path, original, text, regress, base_ok, traj)
            if var is not None:
                break
            feedback = (f"Your edit was applied, but the reproduction still fails:\n{(out or '')[-1200:]}\n"
                        + (("neo4d tried single-token changes around your edit; what some did:\n" + "\n".join(notes))
                           if notes else "neo4d tried single-token changes around your edit; none made it pass."))
        else:
            feedback = f"Your edit was applied, but the reproduction still fails:\n{(out or '')[-1500:]}"
        env.write(path, before if r < rounds - 1 else text)
    _, diff = env.run("git -c core.fileMode=false diff", timeout=120)
    traj.append(dict(kind="end", diff=diff))
    return diff, traj


# ---------------------------------------------------------------------------------------------------- the runner

def load_instances(dataset, split):
    from datasets import load_dataset                         # pip install datasets
    return [dict(x) for x in load_dataset(dataset, split=split)]


def run(args):
    out = Path(args.out)
    (out / "trajs").mkdir(parents=True, exist_ok=True)
    insts = load_instances(args.dataset, args.split)
    if args.ids:
        want = set(Path(args.ids).read_text().split())
        insts = [x for x in insts if x["instance_id"] in want]
    if args.sample:
        insts = random.Random(args.seed).sample(insts, min(args.sample, len(insts)))
    preds = out / "all_preds.jsonl"
    done = {json.loads(l)["instance_id"] for l in preds.read_text().splitlines()} if preds.exists() else set()
    todo = [x for x in insts if x["instance_id"] not in done]
    name = f"neo4d+{args.model}" if args.condition == "neo4d" else args.model
    (out / "run.json").write_text(json.dumps(dict(vars(args), started=datetime.datetime.now().isoformat(),
                                                   instances=[x["instance_id"] for x in insts]), indent=1))
    print(f"{len(todo)} instances to do ({len(done)} already done) -> {out}", flush=True)

    def one(inst):
        t0 = time.time()
        env = DockerEnv(image_of(inst["instance_id"], args.image), f"neo4d_{args.condition}_{inst['instance_id']}".replace("/", "_"))
        try:
            diff, traj = solve(env, inst, args.model, args.condition, args.seed, args.rounds)
        finally:
            env.close()
        traj.append(dict(kind="time", seconds=round(time.time() - t0, 1),
                         model_calls=sum(e["kind"] == "model" for e in traj)))
        (out / "trajs" / f"{inst['instance_id']}.json").write_text(json.dumps(traj, indent=1))
        return dict(instance_id=inst["instance_id"], model_name_or_path=name, model_patch=diff)

    with cf.ThreadPoolExecutor(max_workers=args.workers) as pool:
        for n, pred in enumerate(pool.map(one, todo), 1):
            with preds.open("a") as f:
                f.write(json.dumps(pred) + "\n")
            print(f"  {n}/{len(todo)} {pred['instance_id']}: {'patch' if pred['model_patch'] else 'no patch'}", flush=True)
    return 0


def package(args):
    """The folder SWE-bench/experiments expects: evaluation/<split>/<date>_<name>/ with all_preds.jsonl, logs/, trajs/,
    metadata.yaml, README.md and the harness's report."""
    runp = Path(args.run)
    meta = json.loads((runp / "run.json").read_text())
    name = args.name or (f"neo4d_{meta['model']}" if meta["condition"] == "neo4d" else meta["model"]).replace(":", "-").replace("/", "-")
    dest = Path(args.dest) / f"{datetime.date.today():%Y%m%d}_{name}"
    (dest / "trajs").mkdir(parents=True, exist_ok=True)
    shutil.copy(runp / "all_preds.jsonl", dest / "all_preds.jsonl")
    for t in (runp / "trajs").glob("*.json"):
        shutil.copy(t, dest / "trajs" / t.name)
    if args.eval_logs:
        shutil.copytree(args.eval_logs, dest / "logs", dirs_exist_ok=True)
    if args.report:
        shutil.copy(args.report, dest / Path(args.report).name)
    (dest / "metadata.yaml").write_text(
        f"name: neo4d + {meta['model']}\noss: true\nsite: https://github.com/devkancheti4-design/neo4d\nverified: false\n")
    (dest / "README.md").write_text(
        f"# neo4d + {meta['model']}\n\nA model-free mutation and memory engine around an open model. The model reads the "
        "issue, localises the file, writes a reproduction script and SEARCH/REPLACE edits; neo4d mutates each edit "
        "(single-token changes on the changed lines), runs the reproduction and the module's existing tests on every "
        "variant, and ships the first that passes; otherwise it reports back. One attempt per instance (pass@1). No "
        "hints_text, no oracle files, no evaluation tests are used.\n\nCode: github.com/devkancheti4-design/neo4d "
        "(neo4d/swe_agent.py). Run settings: " + json.dumps({k: meta[k] for k in ('model', 'condition', 'rounds', 'seed')}) + "\n")
    print(f"packaged -> {dest}")
    return 0


def resolved(report):
    d = json.loads(Path(report).read_text())
    for k in ("resolved_ids", "resolved"):
        if isinstance(d.get(k), list):
            return set(d[k])
    raise SystemExit(f"{report}: no resolved_ids in this report")


def _kept_script(tr):
    """The reproduction the run kept (from the explicit entry, or - for older runs - the last model reply whose
    reproduction failed for a reason other than a broken script)."""
    for e in tr:
        if e["kind"] == "reproduction":
            return e["script"]
    kept, last = None, None
    for e in tr:
        if e["kind"] == "model" and "REPRODUCES" in e["prompt"]:
            last = code_block(e["response"])
        elif e["kind"] == "reproduce" and last is not None:
            broken = any(x in e["output"] for x in ("SyntaxError", "ModuleNotFoundError", "ImportError: cannot import name"))
            if e["code"] != 0 and not broken:
                kept = last
            last = None
    return kept


def diagnose(args):
    """Where a run loses issues. ANALYSIS ONLY: it reads the gold patch, so nothing it shows may shape a reported run -
    if it changes the agent, the pilot becomes a design run and results come from fresh seeds."""
    insts = {x["instance_id"]: x for x in load_instances(args.dataset, args.split)}
    resolved_ids = resolved(args.report) if args.report else None
    steps = Counter()
    rows = []
    for t in sorted((Path(args.run) / "trajs").glob("*.json")):
        tr, iid = json.loads(t.read_text()), t.stem
        inst = insts[iid]
        gold = set(re.findall(r"^diff --git a/(\S+)", inst["patch"], re.M))
        cands = next((e["candidates"] for e in tr if e["kind"] == "localise"), [])
        chosen = next((e["path"] for e in tr if e["kind"] == "file"), None)
        if chosen is None:
            m = next((re.search(r"The file `(.+?)` \(with line numbers\)", e["prompt"]) for e in tr
                      if e["kind"] == "model" and "Fix the issue" in e["prompt"]), None)
            chosen = m.group(1) if m else None
        script = _kept_script(tr)
        fix_calls = sum(e["kind"] == "model" and "Fix the issue" in e["prompt"] for e in tr)
        applied = sum(e["kind"] == "round" for e in tr)
        passed = any(e["kind"] == "round" and e.get("reproduction") for e in tr)
        shipped = any(e["kind"] == "neo4d" and e.get("shipped") for e in tr)
        diff = next((e["diff"] for e in tr if e["kind"] == "end"), "")
        row = dict(id=iid, gold_in_candidates=bool(gold & set(cands)), right_file=chosen in gold, reproduction=bool(script),
                   edit_applied=applied > 0, failed_edits=fix_calls - applied, reproduction_passed=passed or shipped,
                   neo4d_shipped=shipped, patch=bool(diff.strip()),
                   resolved=(iid in resolved_ids) if resolved_ids is not None else None)
        if args.gold_repro and script:
            env = DockerEnv(image_of(iid, args.image), f"neo4d_diag_{iid}".replace("/", "_"))
            try:
                env.write("/tmp/gold.patch", inst["patch"])
                env.run("git apply /tmp/gold.patch", timeout=120)
                env.write(env.repro, script)
                row["reproduction_valid"] = env.py(env.repro)[0] == 0
            finally:
                env.close()
        rows.append(row)
        for k, v in row.items():
            if v is True:
                steps[k] += 1
    n = len(rows)
    order = ["gold_in_candidates", "right_file", "reproduction", "reproduction_valid", "edit_applied",
             "reproduction_passed", "neo4d_shipped", "patch", "resolved"]
    print(f"{args.run}: {n} issues (analysis only - uses the gold patch)")
    for k in order:
        if k == "reproduction_valid" and not args.gold_repro:
            continue
        if k == "resolved" and resolved_ids is None:
            continue
        print(f"  {k:22s} {steps[k]:3d} / {n}")
    print(f"  {'failed_edits (total)':22s} {sum(r['failed_edits'] for r in rows):3d}")
    (Path(args.run) / "diagnose.json").write_text(json.dumps(rows, indent=1))
    return 0


def compare(args):
    """The paper's numbers from two official reports (the same instances): resolved, the paired exact test, the cost."""
    from math import comb
    a, b = resolved(args.model_report), resolved(args.neo4d_report)
    ids = json.loads((Path(args.neo4d_run) / "run.json").read_text())["instances"]
    only_a, only_b = len(a - b), len(b - a)
    n = only_a + only_b
    p = min(1.0, 2 * sum(comb(n, k) for k in range(0, min(only_a, only_b) + 1)) / 2 ** n) if n else 1.0

    def cost(run):
        calls = secs = 0
        for t in (Path(run) / "trajs").glob("*.json"):
            last = json.loads(t.read_text())[-1]
            calls, secs = calls + last.get("model_calls", 0), secs + last.get("seconds", 0)
        return calls, secs
    ca, cb = cost(args.model_run), cost(args.neo4d_run)
    lines = [f"| condition | resolved of {len(ids)} | model calls | hours |", "|---|---|---|---|",
             f"| model alone | {len(a)} ({len(a) / len(ids):.1%}) | {ca[0]} | {ca[1] / 3600:.1f} |",
             f"| neo4d + model | {len(b)} ({len(b) / len(ids):.1%}) | {cb[0]} | {cb[1] / 3600:.1f} |", "",
             f"Resolved only with neo4d: {only_b}; only without: {only_a}; exact McNemar p = {p:.3f}."]
    print("\n".join(lines))
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(prog="neo4d.swe_agent")
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run")
    r.add_argument("--condition", choices=("neo4d", "model"), required=True)
    r.add_argument("--model", required=True, help="an ollama model, e.g. qwen2.5-coder:7b")
    r.add_argument("--dataset", default="princeton-nlp/SWE-bench_Lite")
    r.add_argument("--split", default="test")
    r.add_argument("--ids", help="a file of instance ids, one per line")
    r.add_argument("--sample", type=int, help="a seeded random sample of this many instances")
    r.add_argument("--seed", type=int, default=0)
    r.add_argument("--rounds", type=int, default=ROUNDS)
    r.add_argument("--workers", type=int, default=2, help="instances in parallel (one container each)")
    r.add_argument("--image", default="swebench/sweb.eval.x86_64.{id}:latest",
                   help="instance image template; {id} has '__' replaced by '_1776_', {raw} is the instance id")
    r.add_argument("--out", required=True)
    p = sub.add_parser("package")
    p.add_argument("--run", required=True)
    p.add_argument("--dest", default="experiments/evaluation/lite")
    p.add_argument("--name")
    p.add_argument("--eval-logs")
    p.add_argument("--report")
    g = sub.add_parser("diagnose", help="where a run loses issues (analysis only: reads the gold patch)")
    g.add_argument("--run", required=True)
    g.add_argument("--dataset", default="princeton-nlp/SWE-bench_Lite")
    g.add_argument("--split", default="test")
    g.add_argument("--report", help="the harness report, to add the resolved step")
    g.add_argument("--gold-repro", action="store_true", help="(Docker) does each kept reproduction pass with the gold patch?")
    g.add_argument("--image", default="swebench/sweb.eval.x86_64.{id}:latest")
    c = sub.add_parser("compare")
    c.add_argument("--model-report", required=True)
    c.add_argument("--neo4d-report", required=True)
    c.add_argument("--model-run", required=True)
    c.add_argument("--neo4d-run", required=True)
    a = ap.parse_args()
    return {"run": run, "package": package, "compare": compare, "diagnose": diagnose}[a.cmd](a)


if __name__ == "__main__":
    sys.exit(main())
