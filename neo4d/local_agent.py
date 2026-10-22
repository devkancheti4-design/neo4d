"""A small local model doing multi-step work the way Claude does - with neo4d as its brain, does it get better?

THE WORK. A real project (31 QuixBugs programs as modules under qb/, one test file each under tests/) and a stream of
tasks of six kinds - the everyday work of a coding agent. Each needs several tool calls and is accepted only by a check
(the tests, plus a check of the result itself):

    rename a function      definition, recursive calls and the test file's import and calls; tests still pass
    rename a parameter     and every use inside the function; tests still pass
    add a parameter        a keyword parameter with a default, last; tests still pass
    count                  how many modules use a keyword in code (docstrings and comments do not count) -> answer.txt
    who calls              which modules call a built-in -> answer.txt
    fix a bug              a module broken by the mutation teacher; its tests fail; make them pass

Each kind is phrased two ways. The agent's tools are Claude's, reduced: ls, read, grep, replace, write, test, done.

THE SOLVERS, on the same seeded stream:

    model alone        the model is the agent: one episode, one JSON action per turn, at most 10 actions
    model + checks     up to 3 episodes (later ones sampled), keeping the first the check accepts
    neo4d + model      neo4d decides first: if it holds a plan for this kind of task it runs it - placing the task's
                       names into the plan, repeating a step over every file a search found, deriving an answer from
                       what a search found - and the model is asked only for the steps a plan cannot fill (the code a
                       fix writes): it reads and writes, neo4d decides. Otherwise the model works as above. Every
                       accepted piece of work becomes a plan, and the RELATE v2 law decides which plans are trusted:
                       FIRE when accepted work exhibits the plan, NEWNET on a module (or keyword, or built-in) it was
                       not seen on, PREDICTED when the plan, run, was accepted, CHEAP when it needs no model call,
                       BARREN when it keeps failing.

    python -m neo4d.local_agent [--model phi4-mini]      -> results/LOCAL_AGENT.md
"""
from __future__ import annotations

import ast
import io
import json
import random
import re
import shutil
import subprocess
import sys
import tempfile
import time
import tokenize
import urllib.error
import urllib.request
from collections import defaultdict
from pathlib import Path

from neo4d import KERNELS, REPO
from neo4d import domain_mutation as D
from neo4d import relate_live as RL
from neo4d import relations as R
from neo4d import local_model as LM

BUILD = REPO / ".build"
BASE = BUILD / "agent_project"
MAX_STEPS = 10
ATTEMPTS = 3
PER = 15                                     # tasks per kind
SAMPLE = 5                                   # tasks per kind for the comparison with Claude, from the second half

TEST = '''import json
from qb.{name} import {name}

CASES = {cases!r}


def check():
    for input_data, expected in CASES:
        got = {left}
        assert {cmp}, "{name}(%r) returned %r, expected %r" % (input_data, got, expected)
'''

RUN_ALL = '''import importlib
import pathlib
import signal
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))


def alarm(*_):
    raise TimeoutError("timed out")


signal.signal(signal.SIGALRM, alarm)
names = sorted(p.stem for p in pathlib.Path(__file__).parent.glob("test_*.py"))
failed = []
for n in names:
    signal.alarm(2)
    try:
        importlib.import_module("tests." + n).check()
    except BaseException as e:
        failed.append(f"{n}: {type(e).__name__}: {e}"[:200])
    finally:
        signal.alarm(0)
print(f"{len(names) - len(failed)}/{len(names)} test files pass")
for f in failed:
    print("FAIL", f)
'''

SYSTEM = """You are a coding agent working in a small Python project, using tools. Each turn, reply with exactly ONE JSON \
object - the next action - and nothing else.

Tools:
{"tool": "ls", "path": "<directory>"}                                list a directory
{"tool": "read", "path": "<file>"}                                   show a file
{"tool": "grep", "pattern": "<regex>", "path": "<directory or file>"}   search; path "." searches the whole project
{"tool": "replace", "path": "<file>", "old": "<exact text>", "new": "<new text>"}   replace every occurrence in that file
{"tool": "write", "path": "<file>", "content": "<text>"}             create or overwrite a file
{"tool": "test"}                                                     run all the tests
{"tool": "done"}                                                     finish the task

The project: qb/<name>.py defines the function <name>. tests/test_<name>.py imports it (`from qb.<name> import <name>`) \
and calls it. tests/run_all.py runs every test.
"""


# ------------------------------------------------------------------------------------------------ the project

def build_project():
    if BASE.exists():
        shutil.rmtree(BASE)
    (BASE / "qb").mkdir(parents=True)
    (BASE / "tests").mkdir()
    (BASE / "qb" / "__init__.py").write_text("")
    (BASE / "tests" / "__init__.py").write_text("")
    (BASE / "tests" / "run_all.py").write_text(RUN_ALL)
    meta = {}
    for name, expr in LM.json_programs().items():
        src = (LM.QB / "correct_python_programs" / f"{name}.py").read_text()
        cases = [json.loads(l) for l in (LM.QB / "json_testcases" / f"{name}.json").read_text().splitlines() if l.strip()]
        fast = []
        for c in cases:
            t = time.time()
            if LM.run(src, expr, [c], 1.0)[0] and time.time() - t < 0.3:
                fast.append(c)
            if len(fast) == 5:
                break
        if len(fast) < 2:
            continue
        left = ast.unparse(ast.parse(expr, mode="eval").body.left)
        cmp = ("abs(got - expected) <= input_data[-1]" if "approx" in expr
               else "json.loads(json.dumps(got, default=list)) == expected")
        (BASE / "qb" / f"{name}.py").write_text(src)
        (BASE / "tests" / f"test_{name}.py").write_text(TEST.format(name=name, cases=fast, left=left, cmp=cmp))
        meta[name] = (expr, fast)
    return meta


# ---------------------------------------------------------------------------------------------------- the tools

class Sandbox:
    """A fresh copy of the project for one piece of work; the agent's tools act on it."""

    def __init__(self, task):
        self.dir = Path(tempfile.mkdtemp(prefix="agent_")).resolve()
        shutil.copytree(BASE, self.dir, dirs_exist_ok=True)
        for rel, text in task.get("setup", {}).items():
            (self.dir / rel).write_text(text)
        self.files = None

    @classmethod
    def attach(cls, path):
        """The tools on an existing working copy (a large model's, kept between its actions)."""
        sb = cls.__new__(cls)
        sb.dir, sb.files = Path(path).resolve(), None
        return sb

    def close(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    def path(self, p):
        q = (self.dir / str(p).strip().lstrip("/")).resolve()
        if not str(q).startswith(str(self.dir.resolve())):
            raise ValueError("path outside the project")
        return q

    def act(self, a):
        t = a.get("tool")
        self.files = None
        try:
            if t == "ls":
                q = self.path(a.get("path", "."))
                return "\n".join(sorted(x.name + ("/" if x.is_dir() else "") for x in q.iterdir() if x.name != "__pycache__"))
            if t == "read":
                return self.path(a["path"]).read_text()[:4000]
            if t == "grep":
                rx = re.compile(a["pattern"])
                base = self.path(a.get("path") or ".")
                paths = [base] if base.is_file() else sorted(p for p in base.rglob("*") if p.suffix in (".py", ".txt")
                                                             and "__pycache__" not in p.parts)
                out, files = [], []
                for p in paths:
                    rel = str(p.relative_to(self.dir))
                    for i, line in enumerate(p.read_text().split("\n"), 1):
                        if rx.search(line):
                            out.append(f"{rel}:{i}: {line.strip()[:120]}")
                            if rel not in files:
                                files.append(rel)
                self.files = files
                more = f"\n... {len(out) - 40} more lines" if len(out) > 40 else ""
                return "\n".join(out[:40]) + more if out else "no matches"
            if t == "replace":
                q = self.path(a["path"])
                s = q.read_text()
                n = s.count(a["old"]) if a.get("old") else 0
                if n:
                    q.write_text(s.replace(a["old"], a.get("new", "")))
                return f"replaced {n} occurrence(s)" if n else "not found: nothing replaced"
            if t == "write":
                q = self.path(a["path"])
                q.parent.mkdir(parents=True, exist_ok=True)
                q.write_text(str(a.get("content", "")))
                return "written"
            if t == "test":
                r = subprocess.run([sys.executable, "tests/run_all.py"], cwd=self.dir, capture_output=True, text=True,
                                   timeout=60)
                return (r.stdout + r.stderr)[-1500:]
            if t == "done":
                return "done"
            return f"unknown tool {t!r}"
        except Exception as e:                                   # noqa: BLE001 - the agent sees whatever went wrong
            return f"error: {type(e).__name__}: {e}"[:300]

    def tests_pass(self):
        out = self.act({"tool": "test"})
        m = re.match(r"(\d+)/(\d+) test files pass", out)
        return bool(m) and m.group(1) == m.group(2)


# ---------------------------------------------------------------------------------------------------- the tasks

def code_names(src):
    """NAME tokens of the code - docstrings, strings and comments excluded."""
    out = set()
    for tok in tokenize.generate_tokens(io.StringIO(src).readline):
        if tok.type == tokenize.NAME:
            out.add(tok.string)
    return out


def calls_of(src):
    return {n.func.id for n in ast.walk(ast.parse(src)) if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)}


def top_def(src, name):
    return next(n for n in ast.parse(src).body if isinstance(n, ast.FunctionDef) and n.name == name)


PHRASES = {
    "rename function": ("Rename the function `{f}` to `{g}` everywhere in the project, and make sure the tests still pass.",
                        "Change the name of `{f}` to `{g}` - its definition and every place that uses it - keeping all "
                        "tests passing."),
    "rename parameter": ("In the function `{f}`, rename the parameter `{p}` to `{q}`, including every use inside the "
                         "function.",
                         "The parameter `{p}` of `{f}` should be called `{q}`; rename it and all its uses."),
    "add parameter": ("Add a keyword parameter `{p}` with default value `{v}` as the last parameter of `{f}`.",
                      "Give `{f}` a new last parameter `{p}` that defaults to `{v}`; behaviour must not change."),
    "count": ("How many modules in `qb/` use the keyword `{k}` in their code (docstrings and comments do not count)? "
              "Write only the number to `answer.txt`.",
              "Count the modules under `qb/` whose code contains the keyword `{k}` (ignore docstrings and comments) and "
              "write the count to `answer.txt`."),
    "who calls": ("Which modules in `qb/` call the built-in `{b}`? Write their module names, one per line, to "
                  "`answer.txt`.",
                  "List every module under `qb/` that calls `{b}` - one module name per line - in `answer.txt`."),
    "fix a bug": ("The tests for `{f}` fail. Fix the bug in `qb/{f}.py` so that all tests pass.",
                  "Something in `{f}` is broken and its tests fail; find the bug and fix it."),
}
KEYWORDS = ("while", "for", "if", "else", "elif", "return", "in", "not", "and", "or", "break", "lambda", "yield",
            "import", "None", "True", "False", "is", "del", "try", "with", "assert", "continue")
BUILTINS = ("len", "range", "max", "min", "sorted", "list", "enumerate", "abs", "int", "str", "zip", "reversed", "sum",
            "set", "dict", "any", "all", "iter", "next", "map", "float", "tuple", "pow", "divmod", "print", "isinstance")


def make_tasks(meta, seed=2026, per=PER):
    rng = random.Random(seed)
    mods = sorted(meta)
    src = {m: (BASE / "qb" / f"{m}.py").read_text() for m in mods}
    tasks = []

    def add(kind, net, check, setup=None, **kw):
        tasks.append(dict(kind=kind, net=net, check=check, setup=setup or {},
                          text=rng.choice(PHRASES[kind]).format(**kw)))

    for m in rng.sample(mods, per):
        g = rng.choice(("compute_{m}", "{m}_impl", "run_{m}", "{m}_v2")).format(m=m)
        add("rename function", m, ("rename function", m, g), f=m, g=g)
    for m in rng.sample(mods, per):
        p = top_def(src[m], m).args.args[0].arg
        q = rng.choice(("{p}_in", "input_{p}", "{p}_value")).format(p=p)
        add("rename parameter", m, ("rename parameter", m, p, q), f=m, p=p, q=q)
    for m in rng.sample(mods, per):
        p, v = rng.choice((("verbose", "False"), ("debug", "False"), ("strict", "True"), ("limit", "None"), ("trace", "False")))
        add("add parameter", m, ("add parameter", m, p, v), f=m, p=p, v=v)
    counts = {k: sum(k in code_names(src[m]) for m in mods) for k in KEYWORDS}
    for k in rng.sample([k for k in KEYWORDS if 0 < counts[k] < len(mods)], min(per, sum(0 < c < len(mods) for c in counts.values()))):
        add("count", k, ("count", counts[k]), k=k)
    callers = {b: sorted(m for m in mods if b in calls_of(src[m])) for b in BUILTINS}
    usable = [b for b in BUILTINS if 0 < len(callers[b]) < len(mods)]
    for b in rng.sample(usable, min(per, len(usable))):
        add("who calls", b, ("who calls", callers[b]), b=b)
    bugs = []
    for m in mods:
        lines = src[m].split("\n")
        cands = [(li, LM.to_text(lines[li], list(mu))) for li in LM.code_lines(src[m]) for mu in D.mutants(R.toks(lines[li]))]
        rng.shuffle(cands)
        for li, bad in cands:
            if bad == lines[li]:
                continue
            buggy = "\n".join(lines[:li] + [bad] + lines[li + 1:])
            try:
                ast.parse(buggy)
            except SyntaxError:
                continue
            if not LM.run(buggy, *meta[m], 1.0)[0]:
                bugs.append((m, buggy))
                break
    for m, buggy in rng.sample(bugs, min(per, len(bugs))):
        add("fix a bug", m, ("fix a bug", m), setup={f"qb/{m}.py": buggy}, f=m)
    rng.shuffle(tasks)
    for i, t in enumerate(tasks):
        t["id"] = i
    return tasks


def accepted(task, sb):
    kind = task["check"][0]
    try:
        if kind == "count":
            return (sb.dir / "answer.txt").read_text().strip() == str(task["check"][1])
        if kind == "who calls":
            got = {Path(l.strip()).stem for l in (sb.dir / "answer.txt").read_text().split("\n") if l.strip()}
            return got == set(task["check"][1])
        if not sb.tests_pass():
            return False
        if kind == "fix a bug":
            return True
        m = task["check"][1]
        mod = (sb.dir / "qb" / f"{m}.py").read_text()
        if kind == "rename function":
            g = task["check"][2]
            for p in (sb.dir / "qb" / f"{m}.py", sb.dir / "tests" / f"test_{m}.py"):
                t = ast.parse(p.read_text())
                for n in ast.walk(t):
                    if (isinstance(n, ast.FunctionDef) and n.name == m) or (isinstance(n, ast.Name) and n.id == m) or \
                            (isinstance(n, ast.alias) and n.name == m):
                        return False
            return any(isinstance(n, ast.FunctionDef) and n.name == g for n in ast.parse(mod).body)
        fn = top_def(mod, m)
        orig = [a.arg for a in top_def((BASE / "qb" / f"{m}.py").read_text(), m).args.args]
        names = [a.arg for a in fn.args.args]
        if kind == "rename parameter":
            p, q = task["check"][2:]
            uses = {n.id for n in ast.walk(fn) if isinstance(n, ast.Name)}
            return names == [q if a == p else a for a in orig] and p not in uses
        if kind == "add parameter":
            p, v = task["check"][2:]
            d = fn.args.defaults
            return names == orig + [p] and bool(d) and isinstance(d[-1], ast.Constant) and d[-1].value == ast.literal_eval(v)
    except Exception:                                           # noqa: BLE001 - a broken result is not accepted
        return False
    return False


# -------------------------------------------------------------------------------------------------- the model

def generate(model, prompt, temperature, seed, stats):
    stats["model calls"] += 1
    body = json.dumps({"model": model, "prompt": prompt, "stream": False,
                       "options": {"temperature": temperature, "seed": seed, "num_predict": 700, "num_ctx": 8192,
                                   "stop": ["\nResult"]}}).encode()
    for wait in (2, 5, 10, None):           # the local server sometimes answers 500 under load: try again
        try:
            req = urllib.request.Request(LM.OLLAMA, data=body, headers={"Content-Type": "application/json"})
            with urllib.request.urlopen(req, timeout=600) as r:
                return json.loads(r.read())["response"]
        except (urllib.error.URLError, TimeoutError, ConnectionError):
            if wait is None:
                stats["model errors"] += 1
                return ""
            time.sleep(wait)


def parse_action(reply):
    i = reply.find("{")
    while i >= 0:
        try:
            a, _ = json.JSONDecoder().raw_decode(reply[i:])
            if isinstance(a, dict) and "tool" in a:
                return a
        except ValueError:
            pass
        i = reply.find("{", i + 1)
    return None


def episode(model, task, temperature, seed, stats):
    """The model as the agent. -> (trace [(action, result, files found)], accepted)"""
    sb = Sandbox(task)
    trace = []
    try:
        for step in range(MAX_STEPS):
            prompt = (SYSTEM + f"\nTask: {task['text']}\n\n"
                      + "".join(f"Action: {json.dumps(a)}\nResult:\n{obs}\n\n" for a, obs, _ in trace) + "Action:")
            a = parse_action(generate(model, prompt, temperature, seed + step, stats))
            stats["model actions"] += 1
            if a is None:
                trace.append(({"tool": "invalid"}, "Reply with exactly one JSON object.", None))
                continue
            obs = sb.act(a)
            trace.append((a, obs, sb.files))
            if a.get("tool") == "done":
                break
        return trace, accepted(task, sb)
    finally:
        sb.close()


# -------------------------------------------------------------------------------------------------- the brain

def slots_of(text):
    return re.findall(r"`([^`]+)`", text)


def skeleton(text):
    n = iter(range(1, 99))
    return re.sub(r"`[^`]+`", lambda m: f"`<{next(n)}>`", text)


ESCAPES = {"\\" + c: chr(1 + i) for i, c in enumerate("bBsSwWdD")}


def abstract_str(s, slots, path=False, regex=False):
    """Write the task's names into a string as placeholders <1>, <2> ... - in code at identifier boundaries, in a path
    between any non-alphanumerics (tests/test_gcd.py)."""
    out = s
    if regex:                                    # \bname\( : the escape's letter is not part of the name
        for e, c in ESCAPES.items():
            out = out.replace(e, c)
    word = "A-Za-z0-9" if path else "A-Za-z0-9_"
    for i in sorted(range(len(slots)), key=lambda i: -len(slots[i])):
        v = slots[i]
        mark = f"\x00{i + 1}\x00"
        if re.fullmatch(r"[A-Za-z_]\w*", v):
            out = re.sub(rf"(?<![{word}]){re.escape(v)}(?![{word}])", mark, out)
        else:
            out = out.replace(v, mark)
    out = re.sub("\x00(\\d+)\x00", r"⟨\1⟩", out)
    if regex:
        for e, c in ESCAPES.items():
            out = out.replace(c, e)
    return out


def templated(s):
    """A plan can fill this string itself if it uses the task's names and adds little literal text of its own."""
    return "⟨" in s and len(re.sub(r"⟨[^⟩]+⟩", "", s)) <= 40


def abstract(trace, slots):
    """Accepted work -> a plan: its effective actions with the task's names as placeholders."""
    steps, files = [], None
    for a, obs, found in trace:
        t = a.get("tool")
        if t == "grep":
            steps.append({"tool": "grep", "pattern": abstract_str(a.get("pattern", ""), slots, regex=True),
                          "path": abstract_str(a.get("path") or ".", slots, True)})
            files = found
        elif t == "replace" and obs.startswith("replaced"):
            path = abstract_str(a["path"], slots, True)
            if files and a["path"].strip().lstrip("./") in files and "⟨" not in path:
                path = "⟨GREP⟩"
            old, new = abstract_str(a["old"], slots), abstract_str(a.get("new", ""), slots)
            ok = (templated(old) or not old.strip()) and (templated(new) or not new.strip()) and "⟨" in old + new
            steps.append({"tool": "replace", "path": path, "old": old, "new": new} if ok
                         else {"tool": "replace", "path": path, "write": True})
        elif t == "write" and obs == "written":
            c = str(a.get("content", ""))
            lines = {l.strip() for l in c.split("\n") if l.strip()}
            if files is not None and c.strip() == str(len(files)):
                content = "⟨GREPCOUNT⟩"
            elif files and lines == set(files):
                content = "⟨GREPFILES⟩"
            elif files and lines == {Path(f).stem for f in files}:
                content = "⟨GREPMODULES⟩"
            else:
                ac = abstract_str(c, slots)
                content = ac if templated(ac) else None
            wpath = abstract_str(a["path"], slots, True)
            steps.append({"tool": "write", "path": wpath, "content": content} if content
                         else {"tool": "write", "path": wpath, "write": True})
        elif t in ("test", "done"):
            steps.append({"tool": t})
    out = []
    for s in steps:
        if not out or out[-1] != s:
            out.append(s)
    if not out or out[-1] != {"tool": "done"}:
        out.append({"tool": "done"})
    return tuple(json.dumps(s, sort_keys=True, ensure_ascii=False) for s in out)


def fill(s, slots):
    return re.sub(r"⟨(\d+)⟩", lambda m: slots[int(m.group(1)) - 1] if int(m.group(1)) <= len(slots) else m.group(0), s)


def write_step(model, task, step, sb, temperature, stats):
    """A step the plan cannot fill: the model writes it - it sees the task, the file, and the action to complete."""
    path = step["path"]
    shown = sb.act({"tool": "read", "path": path}) if step["tool"] == "replace" else ""
    test = sb.act({"tool": "test"}) if task["kind"] == "fix a bug" else ""
    form = ('{"tool": "replace", "path": "%s", "old": "exact text", "new": "new text"}' % path if step["tool"] == "replace"
            else '{"tool": "write", "path": "%s", "content": "text"}' % path)
    prompt = (SYSTEM + f"\nTask: {task['text']}\n\n" + (f"Action: {json.dumps({'tool': 'test'})}\nResult:\n{test}\n\n" if test else "")
              + (f"Action: {json.dumps({'tool': 'read', 'path': path})}\nResult:\n{shown}\n\n" if shown else "")
              + f"The next action is a {step['tool']} in {path}, of the form {form}.\nAction:")
    a = parse_action(generate(model, prompt, temperature, 3000, stats)) or {}
    a.update(tool=step["tool"], path=path)
    return a


DERIVED = ("⟨GREPCOUNT⟩", "⟨GREPFILES⟩", "⟨GREPMODULES⟩")


def replay(plan, task, model, stats, temperature=0.0):
    """Run a plan on a fresh copy. -> (trace, accepted)"""
    slots = slots_of(task["text"])
    sb = Sandbox(task)
    trace, files = [], None
    try:
        for s in plan:
            step = json.loads(s)
            if step.get("write"):
                paths = files if step["path"] == "⟨GREP⟩" else [fill(step["path"], slots)]
                for p in (paths or [])[:3]:
                    a = write_step(model, task, dict(step, path=p), sb, temperature, stats)
                    trace.append((a, sb.act(a), None))
                continue
            stats["neo4d actions"] += 1
            a = {k: fill(v, slots) for k, v in step.items()}
            if a.get("content") in DERIVED:
                fs = files or []
                a["content"] = {"⟨GREPCOUNT⟩": str(len(fs)), "⟨GREPFILES⟩": "\n".join(fs),
                                "⟨GREPMODULES⟩": "\n".join(Path(f).stem for f in fs)}[a["content"]]
            if a.get("path") == "⟨GREP⟩":
                for p in files or []:
                    b = dict(a, path=p)
                    trace.append((b, sb.act(b), None))
                continue
            obs = sb.act(a)
            if a["tool"] == "grep":
                files = sb.files
            trace.append((a, obs, sb.files))
        return trace, accepted(task, sb)
    finally:
        sb.close()


class Brain:
    """neo4d's plans, one neuron per (kind of task as phrased, plan); the RELATE v2 law sets each one's strength."""

    def __init__(self, law):
        self.law = law
        self.level = defaultdict(int)
        self.nets = defaultdict(set)
        self.fires = defaultdict(int)
        self.good = defaultdict(int)
        self.plans = defaultdict(set)

    def ranked(self, text, lo, hi):
        sk = skeleton(text)
        return sorted((p for p in self.plans[sk] if lo <= self.level[(sk, p)] <= hi),
                      key=lambda p: (-self.level[(sk, p)], -self.good[(sk, p)], len(p)))

    def learn(self, task, trace, tried, shadow):
        sk = skeleton(task["text"])
        own = {(sk, abstract(trace, slots_of(task["text"])))} if trace else set()
        for p, ok in tried.items():
            self.fires[(sk, p)] += 1
            self.good[(sk, p)] += ok
        for k in own | {(sk, p) for p in tried} | {(sk, p) for p in shadow}:
            L = self.level[k]
            FIRE = int(k in own)
            NEWNET = int(FIRE and task["net"] not in self.nets[k])
            PRED = int(L >= 1 and bool(tried.get(k[1]) or shadow.get(k[1])))
            writes = sum('"write": true' in s for s in k[1])
            cheap, costly = writes == 0, len(k[1]) > RL.COSTLY[0]
            BAR = int(L >= 1 and self.fires[k] >= D.BARREN_FIRES and self.good[k] / self.fires[k] < RL.BARREN_YIELD)
            x = L | FIRE << 2 | NEWNET << 3 | PRED << 4 | int(cheap and not costly) << 5 | int(costly) << 6 | BAR << 7
            self.level[k] = self.law(x) & 3
            if FIRE:
                self.nets[k].add(task["net"])
                self.plans[sk].add(k[1])


# ---------------------------------------------------------------------------------------------------- solvers

def solve(solver, model, tasks, law, sample=()):
    stats = defaultdict(int)
    brain = Brain(law)
    rows = []
    t0 = time.time()
    for n, task in enumerate(tasks):
        before = dict(stats)
        how, trace, tried, shadow = None, None, {}, {}
        if solver == "neo4d + model":
            for plan in brain.ranked(task["text"], 2, 3)[:2]:
                tr, ok = replay(plan, task, model, stats)
                tried[plan] = ok
                if ok:
                    how, trace = "neo4d", tr
                    break
        if how is None:
            for k in range(1 if solver == "model alone" else ATTEMPTS):
                tr, ok = episode(model, task, 0.0 if k == 0 else 0.8, 1000 * (k + 1), stats)
                if ok:
                    how, trace = "model", tr
                    break
        if solver == "neo4d + model":
            for plan in [p for p in brain.ranked(task["text"], 1, 1) if p not in tried][:2]:
                if '"write": true' not in "".join(plan):
                    shadow[plan] = replay(plan, task, model, defaultdict(int))[1]
            brain.learn(task, trace, tried, shadow)
        row = dict(id=task["id"], kind=task["kind"], ok=how is not None, how=how,
                   calls=stats["model calls"] - before.get("model calls", 0),
                   neo_actions=stats["neo4d actions"] - before.get("neo4d actions", 0),
                   model_actions=stats["model actions"] - before.get("model actions", 0))
        if n in sample and solver == "neo4d + model":
            row["plans"] = [list(p) for p in brain.ranked(task["text"], 2, 3)[:2]]
        rows.append(row)
        if (n + 1) % 10 == 0:
            print(f"  {solver}: {n + 1}/{len(tasks)} accepted {sum(r['ok'] for r in rows)} calls {stats['model calls']} "
                  f"({time.time() - t0:.0f}s)", flush=True)
    return rows


def pct(rows, key="ok"):
    return sum(bool(r[key]) for r in rows) / max(1, len(rows))


def sample_ids(tasks):
    half = len(tasks) // 2
    rng = random.Random(7)
    out = []
    for kind in PHRASES:
        ids = [t["id"] for t in tasks[half:] if t["kind"] == kind]
        out += rng.sample(ids, min(SAMPLE, len(ids)))
    return sorted(out)


def report(model, tasks, res):
    n = len(tasks)
    half = n // 2
    out = ["# A small local model doing multi-step work, with neo4d as its brain", "",
           f"Generated by `neo4d/local_agent.py`. Local model: **{model}** (ollama, on this machine). A real project - "
           f"{len(list((BASE / 'qb').glob('*.py'))) - 1} QuixBugs programs as modules, one test file each - and **{n} "
           "tasks** of six kinds, the everyday work of a coding agent, in one seeded stream. Each needs several tool "
           "calls (ls, read, grep, replace, write, test, done - Claude's tools, reduced) and is accepted only by a check: "
           "the tests, plus a check of the result itself. Each kind is phrased two ways.", "",
           "| solver | **accepted** | first half of the stream | second half | model calls | actions decided by the model | by neo4d |",
           "|---|---|---|---|---|---|---|"]
    for label, rows in res.items():
        out.append(f"| {label} | **{pct(rows):.1%}** ({sum(r['ok'] for r in rows)}/{n}) | {pct(rows[:half]):.1%} | "
                   f"{pct(rows[half:]):.1%} | {sum(r['calls'] for r in rows)} | {sum(r['model_actions'] for r in rows)} | "
                   f"{sum(r['neo_actions'] for r in rows)} |")
    out += ["", "## Kind by kind", "", "| kind | tasks | " + " | ".join(res) + " | neo4d's plan did it, no model call |",
            "|---|---|" + "---|" * (len(res) + 1)]
    neo = res.get("neo4d + model", [])
    for kind in PHRASES:
        ks = [i for i, t in enumerate(tasks) if t["kind"] == kind]
        alone = sum(1 for i in ks if neo and neo[i]["how"] == "neo4d" and neo[i]["calls"] == 0)
        out.append(f"| {kind} | {len(ks)} | " + " | ".join(f"{pct([rows[i] for i in ks]):.0%}" for rows in res.values())
                   + f" | {alone} |")
    if neo:
        m1 = sum(r["how"] == "neo4d" for r in neo[:half])
        m2 = sum(r["how"] == "neo4d" for r in neo[half:])
        c1 = sum(r["calls"] for r in neo[:half])
        c2 = sum(r["calls"] for r in neo[half:])
        out += ["", "## neo4d as it learns", "", "| | first half | second half |", "|---|---|---|",
                f"| done by neo4d's plan | {m1} | **{m2}** |", f"| model calls | {c1} | **{c2}** |",
                f"| accepted | {pct(neo[:half]):.1%} | {pct(neo[half:]):.1%} |"]
    out += ["", "**What this does not show.** The project is small and the six kinds of task recur, so a plan learned "
            "once is used many times - work that repeats is where a learned plan pays. A plan is matched to a task by "
            "its phrasing with the names taken out, so each phrasing is learned separately. The check is the judge for "
            "every solver; in real use the check is the tests and whoever asked for the work."]
    return out


def put_section(heading, lines):
    """Replace one '## ' section of the report (or add it), keeping the others."""
    p = REPO / "results" / "LOCAL_AGENT.md"
    parts = p.read_text().rstrip("\n").split("\n## ") if p.exists() else ["# A small local model doing multi-step work"]
    body = "\n".join(lines).strip("\n")
    parts = [x for x in parts if not x.startswith(heading)] + [body[3:] if body.startswith("## ") else body]
    p.write_text("\n## ".join(parts) + "\n")


RUNS = BUILD / "agent_runs"


def agent_cli(args, tasks):
    """A large model as the agent, one action per command - the same tools, the same limit of actions, one try.

    --agent-start RUN ID          a fresh working copy for task ID; prints the task
    --agent-act RUN ID [ACTION]   one JSON action (argument or stdin) on that copy; prints the result
    """
    by = {t["id"]: t for t in tasks}
    flag = "--agent-start" if "--agent-start" in args else "--agent-act"
    i = args.index(flag)
    run, tid = args[i + 1], int(args[i + 2])
    d = RUNS / run / str(tid)
    if flag == "--agent-start":
        if d.exists():
            shutil.rmtree(d)
        d.mkdir(parents=True)
        shutil.copytree(BASE, d / "project")
        for rel, text in by[tid]["setup"].items():
            (d / "project" / rel).write_text(text)
        (d / "trace.json").write_text("[]")
        print(f"Task {tid}: {by[tid]['text']}\n\nAt most {MAX_STEPS} actions; finish with {{\"tool\": \"done\"}}.")
        return 0
    trace = json.loads((d / "trace.json").read_text())
    if trace and trace[-1][0].get("tool") == "done":
        print("This task is finished.")
        return 0
    if len(trace) >= MAX_STEPS:
        print("Action limit reached: this task is over.")
        return 0
    raw = args[i + 3] if len(args) > i + 3 else sys.stdin.read()
    a = parse_action(raw)
    if a is None:
        trace.append([{"tool": "invalid"}, "Not a JSON action.", None])
    else:
        sb = Sandbox.attach(d / "project")
        trace.append([a, sb.act(a), sb.files])
    (d / "trace.json").write_text(json.dumps(trace))
    print(trace[-1][1])
    return 0


def agent_score(runs, tasks, law):
    """Large models alone, and neo4d + each: neo4d runs its plans that need no model call; the model's own recorded work
    counts for every other task (a model starts each task fresh, so its work does not depend on neo4d)."""
    out = ["## Large models as the agent", "",
           "Claude Haiku and Claude Sonnet, each run as subagents working through the same stream with the same tools, "
           f"one action per command, at most {MAX_STEPS} actions a task, one try. **neo4d + model**: in stream order, "
           "neo4d runs its trusted plans that need no model call; the model's own work counts for every other task, "
           "and neo4d learns from it. Model actions are the large model's turns - each one a call.", "",
           "| solver | accepted | second half | tasks the large model was needed for | large-model actions | "
           "second half: tasks needing the model |", "|---|---|---|---|---|---|"]
    for run in runs:
        ids = [t["id"] for t in tasks if (RUNS / run / str(t["id"]) / "trace.json").exists()]
        tr = {i: json.loads((RUNS / run / str(i) / "trace.json").read_text()) for i in ids}
        ok = {}
        for i in ids:
            sb = Sandbox.attach(RUNS / run / str(i) / "project")
            ok[i] = accepted(next(t for t in tasks if t["id"] == i), sb)
        stream = [t for t in tasks if t["id"] in tr]
        half = len(stream) // 2
        brain, stats, rows = Brain(law), defaultdict(int), []
        for t in stream:
            tried, shadow, how, good = {}, {}, None, None
            for plan in [p for p in brain.ranked(t["text"], 2, 3) if '"write": true' not in "".join(p)][:2]:
                trace, a = replay(plan, t, None, stats)
                tried[plan] = a
                if a:
                    how, good = "neo4d", trace
                    break
            if how is None and ok[t["id"]]:
                how, good = "model", tr[t["id"]]
            for plan in [p for p in brain.ranked(t["text"], 1, 1) if p not in tried and '"write": true' not in "".join(p)][:2]:
                shadow[plan] = replay(plan, t, None, stats)[1]
            brain.learn(t, good, tried, shadow)
            rows.append(dict(ok=how is not None, need=how != "neo4d", acts=0 if how == "neo4d" else len(tr[t["id"]])))
        name = {"haiku": "Claude Haiku", "sonnet": "Claude Sonnet"}.get(run, run)
        alone = [ok[t["id"]] for t in stream]
        n = len(stream)
        out.append(f"| {name} alone | **{sum(alone)}/{n}** | {sum(alone[half:])}/{n - half} | {n} | "
                   f"{sum(len(tr[t['id']]) for t in stream)} | {n - half} |")
        out.append(f"| **neo4d + {name}** | **{sum(r['ok'] for r in rows)}/{n}** | {sum(r['ok'] for r in rows[half:])}/{n - half} | "
                   f"**{sum(r['need'] for r in rows)}** | **{sum(r['acts'] for r in rows)}** | "
                   f"**{sum(r['need'] for r in rows[half:])}** |")
    put_section("Large models as the agent", out)
    print("\n".join(out))
    return 0


def claude(args, tasks, model):
    """Claude on the comparison sample, in two rounds: read-only actions first, then the work itself, given what they showed."""
    ids = sample_ids(tasks)
    by = {t["id"]: t for t in tasks}
    if "--claude-dump" in args:
        out = [SYSTEM, "For each task: round 1 is a list of read-only actions (ls, read, grep).", ""]
        out += [f"### task {i}\n{by[i]['text']}\n" for i in ids]
        Path(args[args.index("--claude-dump") + 1]).write_text("\n".join(out))
        return 0
    if "--claude-explore" in args:
        acts = json.loads(Path(args[args.index("--claude-explore") + 1]).read_text())
        out = []
        for i in ids:
            sb = Sandbox(by[i])
            out.append(f"### task {i}\n{by[i]['text']}\n")
            for a in acts.get(str(i), []):
                if a.get("tool") in ("ls", "read", "grep"):
                    out.append(f"Action: {json.dumps(a)}\nResult:\n{sb.act(a)}\n")
            sb.close()
        Path(args[args.index("--out") + 1]).write_text("\n".join(out))
        return 0
    finals = json.loads(Path(args[args.index("--claude-score") + 1]).read_text())
    neo = {r["id"]: r for r in json.loads((BUILD / "agent_neo4d_plus_model.json").read_text())}
    res = {s: {r["id"]: r for r in json.loads((BUILD / f"agent_{s.replace(' ', '_').replace('+', 'plus')}.json").read_text())}
           for s in ("model alone", "model + checks", "neo4d + model")}
    mine = {}
    for i in ids:
        sb = Sandbox(by[i])
        for a in finals.get(str(i), []):
            sb.act(a)
        mine[i] = accepted(by[i], sb)
        sb.close()
    by_plan = {i: neo[i]["how"] == "neo4d" and neo[i]["calls"] == 0 for i in ids}
    rows = [(f"{model} alone", [res["model alone"][i]["ok"] for i in ids], len(ids)),
            (f"{model} + checks (3 tries)", [res["model + checks"][i]["ok"] for i in ids], len(ids)),
            (f"neo4d + {model}", [res["neo4d + model"][i]["ok"] for i in ids], len(ids)),
            ("Claude (two rounds, one try)", [mine[i] for i in ids], len(ids)),
            ("neo4d + Claude", [by_plan[i] or mine[i] for i in ids], sum(not by_plan[i] for i in ids))]
    out = ["", f"## Against Claude, on {len(ids)} of the same tasks", "",
           f"Up to {SAMPLE} tasks of each kind from the second half of the stream. Claude used the same tools under a "
           "handicap: two rounds instead of up to ten actions with results - first a list of read-only actions (ls, read, "
           "grep), then the work itself, given what those showed - and one try. **neo4d + Claude**: neo4d's plan where it "
           "did the task with no model call (in the run above), Claude's work otherwise.", "",
           "| solver | accepted | tasks that needed the large or small model |", "|---|---|---|"]
    for label, ok, need in rows:
        out.append(f"| {label} | **{sum(ok)}/{len(ids)}** | {need} |")
    out += ["", "| kind | " + " | ".join(r[0] for r in rows) + " |", "|---|" + "---|" * len(rows)]
    for kind in PHRASES:
        ks = [n for n, i in enumerate(ids) if by[i]["kind"] == kind]
        out.append(f"| {kind} | " + " | ".join(f"{sum(r[1][n] for n in ks)}/{len(ks)}" for r in rows) + " |")
    put_section("Against Claude", out)
    print("\n".join(out))
    return 0


def main() -> int:
    args = sys.argv[1:]
    model = args[args.index("--model") + 1] if "--model" in args else "phi4-mini"
    law = RL.load_law(str(KERNELS / "relate_v2.c"))
    if "--solver" in args or any(x.startswith(("--claude", "--agent")) for x in args):   # the project is already built
        meta = json.loads((BUILD / "agent_meta.json").read_text())
    else:
        meta = build_project()
        (BUILD / "agent_meta.json").write_text(json.dumps(meta))
    tasks = make_tasks(meta)
    if any(x.startswith("--claude") for x in args):
        return claude(args, tasks, model)
    if "--agent-start" in args or "--agent-act" in args:
        return agent_cli(args, tasks)
    if "--agent-score" in args:
        return agent_score(args[args.index("--agent-score") + 1].split(","), tasks, law)
    print(f"  {len(tasks)} tasks over {len(meta)} modules", flush=True)
    if "--solver" in args:
        solver = args[args.index("--solver") + 1]
        rows = solve(solver, model, tasks, law, set(sample_ids(tasks)))
        (BUILD / f"agent_{solver.replace(' ', '_').replace('+', 'plus')}.json").write_text(json.dumps(rows))
        return 0
    solvers = ("model alone", "model + checks", "neo4d + model")
    procs = [subprocess.Popen([sys.executable, "-u", "-m", "neo4d.local_agent", "--model", model, "--solver", s],
                              cwd=REPO, stdout=sys.stdout, stderr=sys.stderr) for s in solvers]
    for p in procs:
        p.wait()
    res = {s: json.loads((BUILD / f"agent_{s.replace(' ', '_').replace('+', 'plus')}.json").read_text()) for s in solvers}
    out = report(model, tasks, res)
    (REPO / "results" / "LOCAL_AGENT.md").write_text("\n".join(out) + "\n")
    print("\n".join(out))
    return 0


if __name__ == "__main__":
    sys.exit(main())
